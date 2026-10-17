from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from tests.utils import ObjectGenerator
from tests.utils.clock import today
from tests.utils.request_generator import RequestGenerator as Rq


def nova_responsabilidade(emp, valor_reservado=0):
    s, d = Rq.call(
        "POST",
        "/responsabilidade",
        {"conta_id": emp.conta_id, "nome": "Freelas", "responsavel_empresa_socio_id": emp.joao_es},
        pessoa=emp.maria,
    )
    assert s == 201, d
    if valor_reservado:
        s, m = Rq.call(
            "POST",
            "/movimento_reserva",
            {"tipo": "RESERVA", "responsabilidade_destino_id": d["responsabilidade_id"], "valor_centavos": valor_reservado},
            pessoa=emp.maria,
            key=Rq.new_key(),
        )
        assert s == 201, m
    return d["responsabilidade_id"]


def agendar(emp, valor, dia, pessoa=None, resp=None):
    body = {"conta_id": emp.conta_id, "meio": "PIX", "valor_centavos": valor, "contraparte": {"chave": "p@x.com"},
            "data_prevista": dia.isoformat()}
    if resp:
        body["responsabilidade_id"] = resp
    return Rq.call("POST", "/pagamento_programado", body, pessoa=pessoa or emp.joao, key=Rq.new_key())


class TestReserva:
    def test_reserva_reduz_saldo_livre_e_fecha_com_responsabilidades(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        resp = nova_responsabilidade(emp, 30000)
        conta = ObjectGenerator.conta(emp.conta_id, emp.joao)
        assert conta["saldo_reservado_centavos"] == 30000
        assert conta["saldo_livre_centavos"] == 70000
        s, r = Rq.call("GET", f"/responsabilidade/{resp}", pessoa=emp.maria)
        assert s == 200 and r["saldo_reservado_centavos"] == 30000

    def test_reserva_acima_do_livre(self):
        emp = ObjectGenerator.empresa(saldo=1000)
        s, d = Rq.call(
            "POST", "/movimento_reserva",
            {"tipo": "RESERVA", "responsabilidade_destino_id": nova_responsabilidade(emp), "valor_centavos": 5000},
            pessoa=emp.maria, key=Rq.new_key(),
        )
        assert s == 422 and d["code"] == "SALDO_LIVRE_INSUFICIENTE"


class TestPagamentoProgramado:
    def test_data_futura_nao_executa(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        s, pp = agendar(emp, 5000, today() + timedelta(days=3))
        assert s == 201, pp
        s, d = Rq.call("POST", f"/pagamento_programado/{pp['pagamento_programado_id']}/execucao")
        assert s == 422 and d["code"] == "DATA_NAO_CHEGOU"
        conta = ObjectGenerator.conta(emp.conta_id, emp.joao)
        assert conta["saldo_comprometido_centavos"] == 5000
        assert conta["saldo_livre_centavos"] == 95000

    def test_execucao_idempotente(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        s, pp = agendar(emp, 5000, today())
        pid = pp["pagamento_programado_id"]
        r = [Rq.call("POST", f"/pagamento_programado/{pid}/execucao") for _ in range(2)]
        assert [x[0] for x in r] == [201, 200]
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 95000

    def test_execucao_concorrente_debita_uma_vez(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        pid = agendar(emp, 5000, today())[1]["pagamento_programado_id"]
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda _: Rq.call("POST", f"/pagamento_programado/{pid}/execucao")[0], range(6)))
        assert res.count(201) == 1 and res.count(200) == 5
        conta = ObjectGenerator.conta(emp.conta_id, emp.joao)
        assert conta["saldo_total_centavos"] == 95000 and conta["saldo_comprometido_centavos"] == 0

    def test_cancelamento_devolve_comprometido(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        pid = agendar(emp, 5000, today() + timedelta(days=2))[1]["pagamento_programado_id"]
        s, d = Rq.call("POST", f"/pagamento_programado/{pid}/cancelamento", {}, pessoa=emp.joao)
        assert s in (200, 201), d
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_comprometido_centavos"] == 0

    def test_cancelamento_vs_execucao_corrida(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        pid = agendar(emp, 5000, today())[1]["pagamento_programado_id"]

        def cancelar(_):
            return Rq.call("POST", f"/pagamento_programado/{pid}/cancelamento", {}, pessoa=emp.joao)[0]

        def executar(_):
            return Rq.call("POST", f"/pagamento_programado/{pid}/execucao")[0]

        with ThreadPoolExecutor(2) as ex:
            f1, f2 = ex.submit(cancelar, 0), ex.submit(executar, 0)
            f1.result(), f2.result()
        conta = ObjectGenerator.conta(emp.conta_id, emp.joao)
        assert conta["saldo_comprometido_centavos"] == 0
        assert conta["saldo_total_centavos"] in (95000, 100000)


class TestAprovacao:
    def regra(self, emp, acima=10000, n=1):
        s, d = Rq.call(
            "PUT", f"/empresa/{emp.empresa_id}/regra_aprovacao",
            {"acao": "PAGAMENTO", "acima_de_centavos": acima, "aprovacoes_necessarias": n}, pessoa=emp.joao,
        )
        assert s == 200, d

    def test_valor_alto_exige_pagamento_programado(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        self.regra(emp)
        s, d = Rq.call("POST", "/transacao",
                       {"meio": "PIX", "valor_centavos": 20000, "conta_origem_id": emp.conta_id, "contraparte": {"chave": "x"}},
                       pessoa=emp.joao, key=Rq.new_key())
        assert s == 422 and d["code"] == "APROVACAO_NECESSARIA"

    def test_autor_nao_aprova_e_aprovacao_libera(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        self.regra(emp)
        pid = agendar(emp, 20000, today())[1]["pagamento_programado_id"]
        s, d = Rq.call("POST", f"/pagamento_programado/{pid}/execucao")
        assert s == 422
        s, d = Rq.call("POST", f"/pagamento_programado/{pid}/aprovacao", {"decisao": "APROVADA"}, pessoa=emp.joao)
        assert s == 422 and d["code"] == "AUTOR_NAO_APROVA_O_PROPRIO"
        s, d = Rq.call("POST", f"/pagamento_programado/{pid}/aprovacao", {"decisao": "APROVADA"}, pessoa=emp.maria)
        assert s == 201 and d["status_do_pedido"] == "AGENDADO"
        assert Rq.call("POST", f"/pagamento_programado/{pid}/execucao")[0] == 201

    def test_voto_duplicado_concorrente(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        s, d = Rq.call("PUT", f"/empresa/{emp.empresa_id}/socio/{emp.ana_es}/permissao/APROVAR",
                       {"escopo": "TODAS"}, pessoa=emp.joao)
        assert s == 200, d
        self.regra(emp, n=2)
        pid = agendar(emp, 20000, today())[1]["pagamento_programado_id"]
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(
                lambda _: Rq.call("POST", f"/pagamento_programado/{pid}/aprovacao", {"decisao": "APROVADA"}, pessoa=emp.maria)[0],
                range(4)))
        assert res.count(201) == 1

    def test_recusa_cancela_e_libera_comprometido(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        self.regra(emp)
        pid = agendar(emp, 20000, today())[1]["pagamento_programado_id"]
        s, d = Rq.call("POST", f"/pagamento_programado/{pid}/aprovacao", {"decisao": "RECUSADA"}, pessoa=emp.maria)
        assert s == 201, d
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_comprometido_centavos"] == 0
