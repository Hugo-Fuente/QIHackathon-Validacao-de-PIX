class MovimentoReservaDTO:
    @staticmethod
    def obj_to_dict(movimento) -> dict:
        return {
            "movimento_id": movimento.movimento_id,
            "conta_id": movimento.conta_id,
            "tipo": movimento.tipo,
            "responsabilidade_origem_id": movimento.responsabilidade_origem_id,
            "responsabilidade_destino_id": movimento.responsabilidade_destino_id,
            "valor_centavos": movimento.valor_centavos,
            "autor_empresa_socio_id": movimento.autor_empresa_socio_id,
            "status": movimento.status,
            "aprovacoes_exigidas": movimento.aprovacoes_exigidas,
            "motivo": movimento.motivo,
            "criado_em": movimento.criado_em.isoformat(),
            "decidido_em": movimento.decidido_em.isoformat() if movimento.decidido_em else None,
        }
