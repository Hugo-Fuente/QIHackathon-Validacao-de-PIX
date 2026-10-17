class EmpresaDTO:
    """O JSON da empresa: dados, sócios (com papel e participação) e as
    permissões de cada sócio."""

    @staticmethod
    def only_ids(empresa_id: str, conta_id: str, vinculos: list = ()) -> dict:
        """A resposta do cadastro: os ids da RFC (empresa_id, conta_id) e, de
        quebra, os ids dos sócios — sem eles ninguém saberia que X-Pessoa-Id
        mandar nas rotas seguintes (login está fora do escopo)."""
        return {
            "empresa_id": empresa_id,
            "conta_id": conta_id,
            "socios": [
                {"cpf": cpf, "pessoa_id": vinculo.pessoa_id, "empresa_socio_id": vinculo.empresa_socio_id, "papel": vinculo.papel}
                for vinculo, cpf in vinculos
            ],
        }

    @staticmethod
    def obj_to_dict(empresa, conta, socios_com_permissoes: list) -> dict:
        socios = []

        for socio, pessoa, permissoes in socios_com_permissoes:
            socios.append(
                {
                    "empresa_socio_id": socio.empresa_socio_id,
                    "pessoa_id": pessoa.pessoa_id,
                    "cpf": pessoa.cpf,
                    "nome": pessoa.nome,
                    "email": pessoa.email,
                    "data_nascimento": pessoa.data_nascimento.isoformat(),
                    "papel": socio.papel,
                    "participacao_bp": socio.participacao_bp,
                    "permissoes": [PermissaoDTO.obj_to_dict(permissao) for permissao in permissoes],
                }
            )

        return {
            "empresa_id": empresa.empresa_id,
            "cnpj": empresa.cnpj,
            "razao_social": empresa.razao_social,
            "conta_id": conta.conta_id,
            "socios": socios,
        }


class PermissaoDTO:
    @staticmethod
    def obj_to_dict(permissao) -> dict:
        return {
            "permissao_id": permissao.permissao_id,
            "empresa_socio_id": permissao.empresa_socio_id,
            "acao": permissao.acao,
            "escopo": permissao.escopo,
            "limite_transacao_centavos": permissao.limite_transacao_centavos,
        }
