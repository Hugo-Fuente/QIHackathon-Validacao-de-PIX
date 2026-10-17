from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    @staticmethod
    def socio(papel="SOCIO_ADMINISTRADOR", participacao_bp=5000, nome="Fulano") -> dict:
        return {
            "cpf": RandomGenerator.generate_cpf(),
            "nome": nome,
            "email": f"s{uuid4().hex[:8]}@exemplo.com.br",
            "data_nascimento": "1988-04-02",
            "papel": papel,
            "participacao_bp": participacao_bp,
        }

    @staticmethod
    def empresa(socios=None) -> dict:
        if socios is None:
            socios = [
                PayloadGenerator.socio(nome="Joao", participacao_bp=5000),
                PayloadGenerator.socio(nome="Maria", participacao_bp=3000),
                PayloadGenerator.socio(papel="SOCIO", nome="Ana", participacao_bp=2000),
            ]
        return {
            "cnpj": RandomGenerator.generate_cnpj(),
            "razao_social": f"Empresa {uuid4().hex[:8]} LTDA",
            "socios": socios,
        }

    @staticmethod
    def pix_saida(conta_id, valor, chave="fornecedor@exemplo.com") -> dict:
        return {"meio": "PIX", "valor_centavos": valor, "conta_origem_id": conta_id, "contraparte": {"chave": chave}}

    @staticmethod
    def pix_entrada(conta_id, valor, referencia=None) -> dict:
        return {
            "meio": "PIX",
            "valor_centavos": valor,
            "conta_destino_id": conta_id,
            "contraparte": {"chave": "pagador"},
            "referencia_externa": referencia or f"E-{uuid4().hex[:12]}",
        }
