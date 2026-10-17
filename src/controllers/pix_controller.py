from database import get_context
from repositories.pix_repository import PixRepository

class PixController:

    def __init__(self):
        self.repository = PixRepository()

    def process_transaction(self, input_data: dict) -> dict:
        context = get_context()
        session = context.get_or_create_session()

        pix_id = input_data["id"]
        source_doc = input_data["source_account"]["owner"]["document_number"]
        dest_doc = input_data["destination_account"]["owner"]["document_number"]
        amount = input_data["amount"]

        # 1. Aplicação de Advisory Locks para concorrência segura (conforme RFC)
        self.repository.acquire_advisory_locks(session, pix_id, source_doc, dest_doc)

        # 2. Verificação de Idempotência
        existing_tx = self.repository.get_transaction_by_id(session, pix_id)
        payload_hash = self.repository.compute_payload_hash(input_data)

        if existing_tx:
            # Se já existe, checa o hash para validar se é o mesmo payload ou conflito (409)
            existing_hash = self.repository.compute_payload_hash(dict(existing_tx.payload or {})) # type: ignore
            if existing_hash != payload_hash:
                from fastapi import HTTPException
                raise HTTPException(status_code=409, detail="Conflito: Mesmo ID de Pix enviado com payload diferente.")
            
            decision = self.repository.get_decision_by_transaction_id(session, pix_id)
            return {
                "key": str(decision.key),
                "status": decision.status,
                "metadata": decision.metadata_ or {}
            }

        # 3. Execução das Regras Antifraude (Motor de Pontuação)
        rule_hits = []
        total_score = 0

        # R1: Limite Absoluto (R$ 5.000,00 = 500000 centavos)
        if amount >= 500000:
            rule_hits.append({"code": "R1", "points": 2, "detail": f"Valor alto: R$ {amount/100:.2f}"})

        # R4: Velocity simulada / Exemplo prático para o Hackathon
        # (No futuro, podemos consultar o histórico real do pagador na base)
        if amount > 1000000: # Acima de 10 mil centavos ganha mais um alerta base
            rule_hits.append({"code": "R2", "points": 2, "detail": "Volume expressivo detectado na transação"})

        # Regra de Teto para a Família de Valor (conforme RFC: teto de 3 pontos para valor)
        value_family_points = sum(hit["points"] for hit in rule_hits if hit["code"] in ["R1", "R2", "R4"])
        if value_family_points > 3:
            # Aplicação do teto de 3 pontos
            diff = value_family_points - 3
            total_score = sum(hit["points"] for hit in rule_hits) - diff
        else:
            total_score = sum(hit["points"] for hit in rule_hits)

        # 4. Mapeamento de Status baseado no Score total
        # 0-1: approved | 2-4: two_factor_required | >=5: rejected
        if total_score >= 5:
            status = "rejected"
        elif total_score >= 2:
            status = "two_factor_required"
        else:
            status = "approved"

        metadata = {
            "risk_score": total_score,
            "rules_triggered": [h["code"] for h in rule_hits],
            "rules_version": "v1.0-hackathon"
        }

        # 5. Persistência atômica no banco de dados
        decision = self.repository.save_analysis(
            session=session,
            transaction_data=input_data,
            payload_hash=payload_hash,
            status=status,
            risk_score=total_score,
            metadata=metadata,
            rule_hits=rule_hits
        )

        return {
            "key": str(decision.key),
            "status": decision.status,
            "metadata": decision.metadata_
        }

    def get_transaction_analysis(self, transaction_id: str) -> dict:
        context = get_context()
        session = context.get_or_create_session()

        decision = self.repository.get_decision_by_transaction_id(session, transaction_id)
        if not decision:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Análise não encontrada para este ID de Pix.")

        return {
            "key": str(decision.key),
            "status": decision.status,
            "metadata": decision.metadata_ or {}
        }