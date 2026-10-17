class PagamentoProgramadoDTO:
    @staticmethod
    def obj_to_dict(pagamento, tarifa_centavos: int, votos: list = None, transacao_id=None) -> dict:
        """`votos` é [(Aprovacao, nome)]: as aprovações recebidas até agora."""
        votos = votos or []

        return {
            "pagamento_programado_id": pagamento.pagamento_programado_id,
            "conta_id": pagamento.conta_id,
            "responsabilidade_id": pagamento.responsabilidade_id,
            "autor_empresa_socio_id": pagamento.autor_empresa_socio_id,
            "meio": pagamento.meio,
            "contraparte": pagamento.contraparte,
            "referencia_externa": pagamento.referencia_externa,
            "valor_centavos": pagamento.valor_centavos,
            "tarifa_centavos": tarifa_centavos,
            "total_comprometido_centavos": pagamento.valor_centavos + tarifa_centavos,
            "data_prevista": pagamento.data_prevista.isoformat(),
            "status": pagamento.status,
            "aprovacoes_exigidas": pagamento.aprovacoes_exigidas,
            "aprovacoes_registradas": sum(1 for voto, _ in votos if voto.decisao == "APROVADA"),
            "aprovacoes": [
                {
                    "empresa_socio_id": voto.empresa_socio_id,
                    "nome": nome,
                    "decisao": voto.decisao,
                    "criado_em": voto.criado_em.isoformat(),
                }
                for voto, nome in votos
            ],
            "categoria": pagamento.categoria,
            "descricao": pagamento.descricao,
            "motivo": pagamento.motivo,
            "transacao_id": transacao_id,
            "criado_em": pagamento.criado_em.isoformat(),
        }

    @staticmethod
    def vote_to_dict(voto, pedido_status: str, aprovacoes_registradas: int, aprovacoes_exigidas: int) -> dict:
        return {
            "aprovacao_id": voto.aprovacao_id,
            "decisao": voto.decisao,
            "status_do_pedido": pedido_status,
            "aprovacoes_registradas": aprovacoes_registradas,
            "aprovacoes_exigidas": aprovacoes_exigidas,
        }
