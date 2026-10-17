from concurrent.futures import ThreadPoolExecutor

from tests.utils import ObjectGenerator, PayloadGenerator
from tests.utils.request_generator import RequestGenerator as Rq


def saida(emp, valor, pessoa=None, key=None, **extra):
    body = {**PayloadGenerator.pix_saida(emp.conta_id, valor), **extra}
    return Rq.call("POST", "/transacao", body, pessoa=pessoa or emp.joao, key=key or Rq.new_key())


class TestSaida:
    def test_saida_debita_saldo(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        status, _ = saida(emp, 40000)
        assert status == 201
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 60000

    def test_saldo_insuficiente(self):
        emp = ObjectGenerator.empresa(saldo=1000)
        status, body = saida(emp, 5000)
        assert status == 422
        assert body["code"] == "SALDO_LIVRE_INSUFICIENTE"

    def test_exige_idempotency_key(self):
        emp = ObjectGenerator.empresa(saldo=1000)
        status, _ = Rq.call("POST", "/transacao", PayloadGenerator.pix_saida(emp.conta_id, 100), pessoa=emp.joao)
        assert status == 400

    def test_socio_sem_permissao_executar(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        status, body = saida(emp, 100, pessoa=emp.ana)
        assert status == 403
        assert body["code"] == "PERMISSAO_NEGADA"

    def test_limite_por_transacao(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        s, d = Rq.call(
            "PUT",
            f"/empresa/{emp.empresa_id}/socio/{emp.maria_es}/permissao/EXECUTAR_PAGAMENTO",
            {"escopo": "TODAS", "limite_transacao_centavos": 5000},
            pessoa=emp.joao,
        )
        assert s == 200, d
        assert saida(emp, 6000, pessoa=emp.maria)[0] == 422
        assert saida(emp, 5000, pessoa=emp.maria)[0] == 201


class TestIdempotencia:
    def test_replay_mesma_chave_mesmo_corpo(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        key = Rq.new_key()
        s1, b1 = saida(emp, 1000, key=key)
        s2, b2 = saida(emp, 1000, key=key)
        assert (s1, s2) == (201, 200)
        assert b1["transacao_id"] == b2["transacao_id"]
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 99000

    def test_mesma_chave_corpo_diferente(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        key = Rq.new_key()
        assert saida(emp, 1000, key=key)[0] == 201
        assert saida(emp, 2000, key=key)[0] == 409

    def test_entrada_referencia_externa_duplicada(self):
        emp = ObjectGenerator.empresa()
        p = PayloadGenerator.pix_entrada(emp.conta_id, 5000)
        assert Rq.call("POST", "/transacao", p)[0] == 201
        assert Rq.call("POST", "/transacao", p)[0] == 200
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 5000

    def test_entrada_concorrente_mesma_referencia_credita_uma_vez(self):
        emp = ObjectGenerator.empresa()
        p = PayloadGenerator.pix_entrada(emp.conta_id, 5000)
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda _: Rq.call("POST", "/transacao", p)[0], range(6)))
        assert res.count(201) == 1 and res.count(200) == 5
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 5000


class TestConcorrencia:
    def test_dois_pix_de_80_com_saldo_100(self):
        emp = ObjectGenerator.empresa(saldo=10000)
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda _: saida(emp, 8000)[0], range(2)))
        assert sorted(res) == [201, 422]
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 2000

    def test_muitos_pix_nunca_estouram(self):
        emp = ObjectGenerator.empresa(saldo=10000)
        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(lambda _: saida(emp, 3000)[0], range(10)))
        assert res.count(201) == 3
        assert ObjectGenerator.conta(emp.conta_id, emp.joao)["saldo_total_centavos"] == 1000

    def test_transferencia_cruzada_sem_deadlock(self):
        a, b = ObjectGenerator.empresa(saldo=100000), ObjectGenerator.empresa(saldo=100000)

        def mover(args):
            origem, destino, pessoa = args
            body = {"meio": "INTERNO", "valor_centavos": 100, "conta_origem_id": origem.conta_id,
                    "conta_destino_id": destino.conta_id}
            return Rq.call("POST", "/transacao", body, pessoa=pessoa, key=Rq.new_key())[0]

        jobs = [(a, b, a.joao), (b, a, b.joao)] * 10
        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(mover, jobs))
        assert all(s == 201 for s in res), res
        total = ObjectGenerator.conta(a.conta_id, a.joao)["saldo_total_centavos"] + ObjectGenerator.conta(
            b.conta_id, b.joao
        )["saldo_total_centavos"]
        assert total == 200000


class TestExtrato:
    def test_extrato_pagina_e_fecha_saldo(self):
        emp = ObjectGenerator.empresa(saldo=100000)
        for _ in range(4):
            assert saida(emp, 1000)[0] == 201
        itens, cursor = [], None
        while True:
            params = {"limite": 2}
            if cursor:
                params["cursor"] = cursor
            s, d = Rq.call("GET", f"/conta/{emp.conta_id}/extrato", pessoa=emp.joao, params=params)
            assert s == 200, d
            itens += d["itens"]
            cursor = d.get("proximo_cursor")
            if not cursor:
                break
        assert len({i["transacao_id"] for i in itens}) == len(itens) == 5
        conta = ObjectGenerator.conta(emp.conta_id, emp.joao)
        assert conta["saldo_total_centavos"] == 100000 - 4000
