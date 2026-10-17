from tests.utils.payload_generator import PayloadGenerator
from tests.utils.request_generator import RequestGenerator as Rq


class Empresa:
    def __init__(self, data: dict):
        self.empresa_id = data["empresa_id"]
        self.conta_id = data["conta_id"]
        self.socios = data["socios"]
        self.joao, self.maria, self.ana = (s["pessoa_id"] for s in self.socios[:3]) if len(self.socios) >= 3 else (None,) * 3
        self.joao_es, self.maria_es, self.ana_es = (s["empresa_socio_id"] for s in self.socios[:3]) if len(self.socios) >= 3 else (None,) * 3


class ObjectGenerator:
    @staticmethod
    def empresa(ativa=True, saldo=0) -> Empresa:
        status, data = Rq.call("POST", "/empresa", PayloadGenerator.empresa())
        assert status == 201, data
        emp = Empresa(data)
        if ativa:
            s, d = Rq.call("PATCH", f"/conta/{emp.conta_id}/status", {"status": "ATIVA"})
            assert s == 200, d
        if saldo:
            ObjectGenerator.deposito(emp.conta_id, saldo)
        return emp

    @staticmethod
    def deposito(conta_id, valor) -> dict:
        s, d = Rq.call("POST", "/transacao", PayloadGenerator.pix_entrada(conta_id, valor))
        assert s == 201, d
        return d

    @staticmethod
    def conta(conta_id, pessoa) -> dict:
        s, d = Rq.call("GET", f"/conta/{conta_id}", pessoa=pessoa)
        assert s == 200, d
        return d
