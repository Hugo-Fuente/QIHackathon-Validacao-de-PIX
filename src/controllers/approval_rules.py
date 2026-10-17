from errors import RegraInatingivel


class ApprovalRules:
    """Regras de aprovação: qual regra vale para um pedido, quem pode votar e
    quantos votos são exigidos. Mixin: exige `self.governanca_repository`,
    `self.empresa_repository` e o AccessControl.
    """

    def resolve_rule(self, empresa_id: str, acao: str, meio, valor_centavos: int):
        """A regra que alcança o pedido, ou None se ele não precisa de aprovação.

        Uma regra alcança o pedido quando o valor ULTRAPASSA o `acima_de` (R$
        1.000,00 exatos não exige aprovação numa regra "acima de R$ 1.000,00")
        e o meio bate (regra sem meio vale para todos). Entre as que alcançam,
        a regra COM meio vence a sem meio, e depois vence a de maior acima_de.
        """
        candidates = []

        for rule in self.governanca_repository.list_regras(empresa_id, acao):
            if valor_centavos > rule.acima_de_centavos and (rule.meio is None or rule.meio == meio):
                candidates.append(rule)

        if not candidates:
            return None

        return max(candidates, key=lambda rule: (rule.meio is not None, rule.acima_de_centavos))

    def eligible_approvers(self, empresa_id: str, author_socio_id: str, responsabilidades) -> list:
        """Os sócios que PODEM votar neste pedido: têm APROVAR no escopo das
        responsabilidades envolvidas e não são o autor (ninguém aprova o
        próprio pedido)."""
        eligible = []

        for socio, permissao in self.empresa_repository.list_aprovadores(empresa_id):
            if socio.empresa_socio_id == author_socio_id:
                continue

            if not self.scope_covers(permissao, socio, responsabilidades):
                continue

            eligible.append(socio)

        return eligible

    def approvals_for(self, rule, empresa_id: str, author_socio_id: str, responsabilidades) -> int:
        """Quantas aprovações o pedido exige — número que fica CONGELADO nele
        (mudar a regra depois não altera pedidos em andamento). `exige_todos`
        vira o número de sócios elegíveis na hora do pedido. Se a regra pede
        mais votos do que sócios elegíveis existem, o pedido nunca andaria:
        422 REGRA_INATINGIVEL."""
        eligible = self.eligible_approvers(empresa_id, author_socio_id, responsabilidades)
        needed = len(eligible) if rule.exige_todos else rule.aprovacoes_necessarias

        if needed < 1 or needed > len(eligible):
            raise RegraInatingivel(f"a regra exige {needed} aprovação(ões) e há {len(eligible)} sócio(s) elegível(is)")

        return needed
