class ResponsabilidadeDTO:
    @staticmethod
    def only_id(responsabilidade) -> dict:
        return {"responsabilidade_id": responsabilidade.responsabilidade_id}

    @staticmethod
    def obj_to_dict(responsabilidade, responsavel: dict, substituto_vigente, substituicao, orcamento_do_mes) -> dict:
        """`responsavel` e `substituto_vigente` são {empresa_socio_id, nome};
        `substituicao` é a janela cadastrada (pode estar no futuro ou no
        passado); `orcamento_do_mes` é o orçamento da competência atual."""
        return {
            "responsabilidade_id": responsabilidade.responsabilidade_id,
            "conta_id": responsabilidade.conta_id,
            "nome": responsabilidade.nome,
            "responsavel": responsavel,
            "substituto_vigente": substituto_vigente,
            "substituicao": substituicao,
            "saldo_reservado_centavos": responsabilidade.saldo_reservado_centavos,
            "saldo_comprometido_centavos": responsabilidade.saldo_comprometido_centavos,
            "orcamento_do_mes": orcamento_do_mes,
        }

    @staticmethod
    def orcamento_to_dict(orcamento) -> dict:
        return {
            "orcamento_id": orcamento.orcamento_id,
            "responsabilidade_id": orcamento.responsabilidade_id,
            "competencia": orcamento.competencia,
            "valor_centavos": orcamento.valor_centavos,
            "utilizado_centavos": orcamento.utilizado_centavos,
            "disponivel_centavos": orcamento.valor_centavos - orcamento.utilizado_centavos,
        }
