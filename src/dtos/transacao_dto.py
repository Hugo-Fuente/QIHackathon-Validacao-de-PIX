class TransacaoDTO:
    """A transação como o cliente a vê."""

    @staticmethod
    def obj_to_dict(transacao, tarifa_centavos: int = 0, autor_nome=None, responsabilidade_nome=None) -> dict:
        return {
            "transacao_id": transacao.transacao_id,
            "natureza": transacao.natureza,
            "meio": transacao.meio,
            "conta_origem_id": transacao.conta_origem_id,
            "conta_destino_id": transacao.conta_destino_id,
            "contraparte": transacao.contraparte,
            "referencia_externa": transacao.referencia_externa,
            "valor_centavos": transacao.valor_centavos,
            "tarifa_centavos": tarifa_centavos or 0,
            "saldo_origem_apos_centavos": transacao.saldo_origem_apos_centavos,
            "saldo_destino_apos_centavos": transacao.saldo_destino_apos_centavos,
            "autor_empresa_socio_id": transacao.autor_empresa_socio_id,
            "autor_nome": autor_nome,
            "responsabilidade_id": transacao.responsabilidade_id,
            "responsabilidade_nome": responsabilidade_nome,
            "pagamento_programado_id": transacao.pagamento_programado_id,
            "categoria": transacao.categoria,
            "descricao": transacao.descricao,
            "criado_em": transacao.criado_em.isoformat(),
        }

    @staticmethod
    def row_to_extrato_item(row, conta_id: str) -> dict:
        """Um item do extrato, do ponto de vista da conta consultada.

        O valor sai COM SINAL: negativo quando a conta é a origem (saiu
        dinheiro), positivo quando é o destino (entrou). A tarifa só existe
        para quem pagou. O saldo "após" é o da ponta que é esta conta — por
        isso o extrato mostra o saldo corrido sem ninguém precisar somar tudo.

        Invariante (testada): soma(valor_centavos) - soma(tarifa_centavos) de
        todo o extrato == saldo_total_centavos da conta.
        """
        transacao = row.Transacao
        is_origin = transacao.conta_origem_id == conta_id

        autor = None
        if transacao.autor_empresa_socio_id is not None:
            autor = {"empresa_socio_id": transacao.autor_empresa_socio_id, "nome": row.autor_nome}

        responsabilidade = None
        if transacao.responsabilidade_id is not None:
            responsabilidade = {
                "responsabilidade_id": transacao.responsabilidade_id,
                "nome": row.responsabilidade_nome,
            }

        return {
            "transacao_id": transacao.transacao_id,
            "criado_em": transacao.criado_em.isoformat(),
            "natureza": transacao.natureza,
            "meio": transacao.meio,
            "contraparte": transacao.contraparte,
            "conta_origem_id": transacao.conta_origem_id,
            "conta_destino_id": transacao.conta_destino_id,
            "valor_centavos": -transacao.valor_centavos if is_origin else transacao.valor_centavos,
            "tarifa_centavos": (row.tarifa_centavos or 0) if is_origin else 0,
            "categoria": transacao.categoria,
            "descricao": transacao.descricao,
            "autor": autor,
            "responsabilidade": responsabilidade,
            "pagamento_programado_id": transacao.pagamento_programado_id,
            "saldo_apos_centavos": (
                transacao.saldo_origem_apos_centavos if is_origin else transacao.saldo_destino_apos_centavos
            ),
        }
