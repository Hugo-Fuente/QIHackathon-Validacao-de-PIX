from datetime import datetime


class ContaDTO:
    """A conta com os três baldes (e o livre derivado) e o histórico de status."""

    @staticmethod
    def obj_to_dict(conta, status_codigo: str, eventos: list, now: datetime) -> dict:
        """`eventos` é [(ContaStatusEvento, codigo)] em ordem cronológica. Cada
        status vai de `desde` até `ate` (o início do seguinte; nulo no atual),
        e `tempo_segundos` é quanto a conta ficou nele (até agora, no atual)."""
        historico = []

        for index, (evento, codigo) in enumerate(eventos):
            end = eventos[index + 1][0].criado_em if index + 1 < len(eventos) else None
            elapsed = (end or now) - evento.criado_em

            historico.append(
                {
                    "status": codigo,
                    "desde": evento.criado_em.isoformat(),
                    "ate": end.isoformat() if end else None,
                    "tempo_segundos": max(0.0, round(elapsed.total_seconds(), 3)),
                    "motivo": evento.motivo,
                }
            )

        return {
            "conta_id": conta.conta_id,
            "empresa_id": conta.empresa_id,
            "agencia": conta.agencia,
            "numero": conta.numero,
            "saldo_total_centavos": conta.saldo_total_centavos,
            "saldo_reservado_centavos": conta.saldo_reservado_centavos,
            "saldo_comprometido_centavos": conta.saldo_comprometido_centavos,
            "saldo_livre_centavos": conta.saldo_livre_centavos,
            "status": status_codigo,
            "status_desde": historico[-1]["desde"] if historico else None,
            "historico": historico,
        }
