from concurrent.futures import ThreadPoolExecutor

from tests.utils import ObjectGenerator, PayloadGenerator
from tests.utils.request_generator import RequestGenerator as Rq


class TestEmpresa:
    def test_cria_empresa_com_conta_em_aprovacao(self):
        emp = ObjectGenerator.empresa(ativa=False)
        conta = ObjectGenerator.conta(emp.conta_id, emp.joao)
        assert conta["saldo_total_centavos"] == 0
        assert conta["status"] == "EM_APROVACAO"

    def test_cnpj_invalido(self):
        p = PayloadGenerator.empresa()
        p["cnpj"] = "11111111111111"
        status, body = Rq.call("POST", "/empresa", p)
        assert status in (400, 422)
        assert "code" in body

    def test_participacao_precisa_somar_100(self):
        p = PayloadGenerator.empresa([PayloadGenerator.socio(participacao_bp=4000)])
        status, _ = Rq.call("POST", "/empresa", p)
        assert status in (400, 422)

    def test_cnpj_duplicado_concorrente(self):
        p = PayloadGenerator.empresa()
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda _: Rq.call("POST", "/empresa", p)[0], range(4)))
        assert res.count(201) == 1
        assert all(s == 409 for s in res if s != 201)

    def test_sem_token_interno(self):
        status, _ = Rq.call("POST", "/empresa", PayloadGenerator.empresa(), token=False)
        assert status == 403

    def test_pessoa_desconhecida(self):
        emp = ObjectGenerator.empresa()
        status, body = Rq.call("GET", f"/conta/{emp.conta_id}", pessoa="00000000-0000-0000-0000-000000000000")
        assert status == 401
        assert body["code"] == "PESSOA_NAO_IDENTIFICADA"

    def test_estranho_nao_ve_conta(self):
        a, b = ObjectGenerator.empresa(), ObjectGenerator.empresa()
        status, _ = Rq.call("GET", f"/conta/{a.conta_id}", pessoa=b.joao)
        assert status in (403, 404)


class TestContaStatus:
    def test_conta_inativa_nao_movimenta(self):
        emp = ObjectGenerator.empresa(ativa=False)
        status, body = Rq.call("POST", "/transacao", PayloadGenerator.pix_entrada(emp.conta_id, 100))
        assert status == 422
        assert body["code"] == "CONTA_NAO_ATIVA"

    def test_bloqueio_barra_saida(self):
        emp = ObjectGenerator.empresa(saldo=10000)
        s, _ = Rq.call("PATCH", f"/conta/{emp.conta_id}/status", {"status": "BLOQUEADA"})
        assert s == 200
        status, body = Rq.call(
            "POST", "/transacao", PayloadGenerator.pix_saida(emp.conta_id, 100), pessoa=emp.joao, key=Rq.new_key()
        )
        assert status == 422
        assert body["code"] == "CONTA_NAO_ATIVA"
