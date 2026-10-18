import json
import statistics
import math
from datetime import datetime, timezone, timedelta
from database import get_context
from repositories.pix_repository import PixRepository
from utils.logger import get_logger


logger = get_logger(__name__)

def calculate_distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    a = max(0.0, min(1.0, a))
    c = 2 * math.asin(math.sqrt(a))
    return R * c


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

        # 3. Execução do Motor de Pontuação (Acumulando todas as regras R1 a R5 + Velocity)
        rule_hits = []

        # R1: Valor moderadamente alto (R$ 5.000,00 até R$ 10.000,00) -> 2 pontos
        if 500000 <= amount < 1000000:
            rule_hits.append({
                "code": "R1",
                "points": 2,
                "detail": f"Valor elevado: R$ {amount/100:.2f}"
            })

        # R2: Volume expressivo (Acima de R$ 10.000,00) -> 3 pontos
        elif amount >= 1000000:
            rule_hits.append({
                "code": "R2",
                "points": 3,
                "detail": f"Volume expressivo crítico: R$ {amount/100:.2f}"
            })

        # R_VELOCITY / R_CRITICAL: Frequência e rajadas
        recent_count = self.repository.count_recent_transactions_by_source(session, source_doc, minutes=10)
        if recent_count >= 5:
            rule_hits.append({
                "code": "R_CRITICAL",
                "points": 5,
                "detail": f"Rajada crítica detectada: {recent_count} transações recentes."
            })
        elif recent_count >= 1:
            rule_hits.append({
                "code": "R_VELOCITY",
                "points": 3,
                "detail": "Múltiplas transações recentes do mesmo remetente."
            })

        # R3: Montante acumulado (Soma em 10 min >= R$ 10.000, com pelo menos 2 Pix) -> 2 pontos
        recent_10m = self.repository.get_transactions_in_minutes(session, source_doc, minutes=10)
        sum_amount = sum(tx.amount for tx in recent_10m) + amount
        total_count = len(recent_10m) + 1
        if sum_amount >= 1000000 and total_count >= 2:
            rule_hits.append({
                "code": "R3",
                "points": 2,
                "detail": f"Montante acumulado alto em 10 min: R$ {sum_amount/100:.2f} ({total_count} transações)"
            })

        # Histórico útil do pagador para R4 e R5
        user_history = self.repository.get_user_successful_history(session, source_doc, limit=20)
        history_count = len(user_history)

        # R4: Desvio de perfil (amount >= 5x mediana dos últimos 20 Pix, histórico >= 5 e amount >= R$ 500) -> 2 pontos[cite: 19]
        if history_count >= 5 and amount >= 50000:
            amounts = [tx.amount for tx in user_history]
            median_amount = statistics.median(amounts) if amounts else 0
            if median_amount > 0 and amount >= 5 * median_amount:
                rule_hits.append({
                    "code": "R4",
                    "points": 2,
                    "detail": f"Desvio de perfil: valor de R$ {amount/100:.2f} é >= 5x a mediana do histórico."
                })

        # R5: Contraparte nova (Sem Pix anterior para esse destino, histórico >= 3 e amount >= R$ 1.000) -> 1 ponto[cite: 19]
        if history_count >= 3 and amount >= 100000:
            has_history_with_dest = self.repository.has_previous_transaction_with_destination(session, source_doc, dest_doc)
            if not has_history_with_dest:
                rule_hits.append({
                    "code": "R5",
                    "points": 1,
                    "detail": "Contraparte nova: primeira transferência para este destinatário com valor relevante."
                })

        # R6: Destino recém-aberto (até 30 dias e amount >= R$ 1.000) -> 2 pontos
        dest_opening_date_str = input_data["destination_account"].get("opening_date")
        if dest_opening_date_str and amount >= 100000:
            dest_opening_date = datetime.fromisoformat(dest_opening_date_str.replace("Z", "+00:00"))
            tx_date = datetime.fromisoformat(input_data["transaction_date"].replace("Z", "+00:00"))
            if dest_opening_date.tzinfo is None:
                dest_opening_date = dest_opening_date.replace(tzinfo=timezone.utc)
            if tx_date.tzinfo is None:
                tx_date = tx_date.replace(tzinfo=timezone.utc)

            elapsed = tx_date.astimezone(timezone.utc) - dest_opening_date.astimezone(timezone.utc)
            if timedelta(0) <= elapsed <= timedelta(days=30):
                rule_hits.append({
                    "code": "R6",
                    "points": 2,
                    "detail": f"Conta destino recém-aberta ({elapsed.days} dias) com valor relevante de R$ {amount/100:.2f}"
                })

        # R7: Dispositivo novo (fora dos últimos 20 Pix do pagador, histórico >= 3 e amount >= R$ 500) -> 2 pontos
        if history_count >= 3 and amount >= 50000:
            recent_devices = set()
            for tx in user_history[:20]:
                payload = tx.payload
                if isinstance(payload, dict):
                    source = payload.get("source")
                    if isinstance(source, dict) and source.get("device_id"):
                        recent_devices.add(source["device_id"])

            current_device = input_data.get("source", {}).get("device_id")

            if current_device and current_device not in recent_devices:
                rule_hits.append({
                    "code": "R7",
                    "points": 2,
                    "detail": f"Dispositivo novo ({current_device}) detetado para pagador com histórico e valor relevante."
                })

        # R8: Fracionamento (>= 3 Pix para a mesma conta destino em 5 min, cada um < R$ 1.000, soma da janela >= R$ 2.000) -> 2 pontos
        dest_acc_num = input_data["destination_account"]["account_number"]
        recent_dest_txs = self.repository.get_transactions_by_source_and_destination(
            session,
            source_doc,
            dest_acc_num,
            minutes=5
        )

        # Filtra para considerar apenas transações com valor < R$ 1.000 (100000 centavos)
        small_txs = [tx for tx in recent_dest_txs if tx.amount < 100000]

        # Se houver pelo menos 2 transações anteriores + a atual (total >= 3), verifica a soma
        if len(small_txs) >= 2 and amount < 100000:
            sum_small_amount = sum(tx.amount for tx in small_txs) + amount
            if sum_small_amount >= 200000:
                rule_hits.append({
                    "code": "R8",
                    "points": 2,
                    "detail": f"Fracionamento detetado: {len(small_txs) + 1} Pix pequenos somando R$ {sum_small_amount/100:.2f} em 5 min."
                })

        # R9: Destino concentrador (5 pagadores em 60 min e soma >= R$ 10.000) -> 3 pontos
        if source_doc != dest_doc:
            recent_destination_txs = self.repository.get_destination_recent_activity(
                session,
                dest_acc_num,
                minutes=60
            )
            senders = {tx.source_document for tx in recent_destination_txs}
            senders.add(source_doc)
            sum_destination_amount = sum(tx.amount for tx in recent_destination_txs) + amount

            clean_destination_document = "".join(filter(str.isdigit, dest_doc))
            is_old_cnpj = False
            dest_opening_date = input_data["destination_account"].get("opening_date")
            if len(clean_destination_document) == 14 and dest_opening_date:
                if isinstance(dest_opening_date, str):
                    dest_opening_date = datetime.fromisoformat(dest_opening_date.replace("Z", "+00:00"))
                tx_date = input_data["transaction_date"]
                if isinstance(tx_date, str):
                    tx_date = datetime.fromisoformat(tx_date.replace("Z", "+00:00"))

                if dest_opening_date.tzinfo is None:
                    dest_opening_date = dest_opening_date.replace(tzinfo=timezone.utc)
                if tx_date.tzinfo is None:
                    tx_date = tx_date.replace(tzinfo=timezone.utc)

                is_old_cnpj = (
                    tx_date.astimezone(timezone.utc)
                    - dest_opening_date.astimezone(timezone.utc)
                ) > timedelta(days=30)

            if len(senders) >= 5 and sum_destination_amount >= 1000000 and not is_old_cnpj:
                rule_hits.append({
                    "code": "R9",
                    "points": 3,
                    "detail": f"Destino concentrador: recebeu de {len(senders)} pagadores distintos, somando R$ {sum_destination_amount/100:.2f} em 60 min."
                })

        # R10: Pagador recente (Conta pagadora com <= 30 dias e amount >= R$ 2.000) -> 1 ponto, ou 2 pontos se sem histórico (< 3 Pix)
        source_opening_date_str = input_data["source_account"].get("opening_date")
        if source_opening_date_str and amount >= 200000:
            try:
                source_opening_date = datetime.fromisoformat(source_opening_date_str.replace("Z", "+00:00"))
                tx_date = datetime.fromisoformat(input_data["transaction_date"].replace("Z", "+00:00"))
                delta_days = (tx_date - source_opening_date).days
                
                if 0 <= delta_days <= 30:
                    # Se tiver menos de 3 Pix no histórico, pesa 2 pontos; senão, 1 ponto
                    r10_points = 2 if history_count < 3 else 1
                    rule_hits.append({
                        "code": "R10",
                        "points": r10_points,
                        "detail": f"Conta pagadora recém-aberta ({delta_days} dias) com valor relevante de R$ {amount/100:.2f} (Histórico: {history_count} Pix)."
                    })
            except Exception:
                pass

        # R11: Deslocamento impossível (geolocalização, Pix anterior <= 60 min, dist >= 50 km, vel > 900 km/h) -> 3 pontos
        current_geo = input_data.get("source", {}).get("geolocation")
        if current_geo and "latitude" in current_geo and "longitude" in current_geo:
            # Busca TODAS as transações dos últimos 60 minutos do pagador (não apenas as aprovadas)
            recent_60m = self.repository.get_transactions_in_minutes(session, source_doc, minutes=60)
            
            last_tx_with_geo = None
            last_lat, last_lon = None, None
            
            for tx in recent_60m:
                lat, lon = getattr(tx, 'latitude', None), getattr(tx, 'longitude', None)
                
                # Se não existirem colunas nativas, vai buscar ao JSON do payload
                if lat is None or lon is None:
                    payload = getattr(tx, 'payload', {}) or {}
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except json.JSONDecodeError:
                            logger.warning("Payload inválido em JSON no histórico usado pela regra R11.")
                            payload = {}

                    if isinstance(payload, dict):
                        source = payload.get("source")
                        if isinstance(source, dict):
                            geo = source.get("geolocation")
                            if isinstance(geo, dict):
                                lat, lon = geo.get("latitude"), geo.get("longitude")
                
                if lat is not None and lon is not None:
                    last_tx_with_geo = tx
                    last_lat, last_lon = float(lat), float(lon)
                    break
            
            if last_tx_with_geo and hasattr(last_tx_with_geo, 'transaction_date'):
                try:
                    prev_time = last_tx_with_geo.transaction_date
                    if isinstance(prev_time, str):
                        prev_time = datetime.fromisoformat(prev_time.replace("Z", "+00:00"))

                    curr_time = datetime.fromisoformat(input_data["transaction_date"].replace("Z", "+00:00"))
                    
                    # Garante que as datas conversam no mesmo timezone UTC
                    if prev_time.tzinfo is None:
                        prev_time = prev_time.replace(tzinfo=timezone.utc)
                    else:
                        prev_time = prev_time.astimezone(timezone.utc)
                    if curr_time.tzinfo is None:
                        curr_time = curr_time.replace(tzinfo=timezone.utc)
                    else:
                        curr_time = curr_time.astimezone(timezone.utc)
                    
                    diff_hours = (curr_time - prev_time).total_seconds() / 3600.0
                    
                    if 0 < diff_hours <= 1.0:
                        dist_km = calculate_distance_km(
                            last_lat, last_lon,
                            float(current_geo["latitude"]), float(current_geo["longitude"])
                        )
                        
                        if dist_km >= 50.0:
                            implied_speed = dist_km / diff_hours
                            if implied_speed > 900.0:
                                rule_hits.append({
                                    "code": "R11",
                                    "points": 3,
                                    "detail": f"Deslocamento impossível: {dist_km:.1f} km em {diff_hours*60:.1f} min (Velocidade: {implied_speed:.0f} km/h)."
                                })
                except (AttributeError, TypeError, ValueError, OverflowError) as e:
                    logger.warning("Não foi possível avaliar as datas/coordenadas da regra R11: %s", e)

        # R12: Horário de risco (Madrugada: 20:00 às 06:00 BRT) com valor >= R$ 1.000 -> 2 pontos
        try:
            tx_date_utc = datetime.fromisoformat(input_data["transaction_date"].replace("Z", "+00:00"))
            
            # Subtrai 3 horas para encontrar o horário de Brasília (UTC-3) de forma simples
            # Se a tua API usar pytz ou zoneinfo, podes fazer a conversão de timezone direto, 
            # mas com timedelta garantimos que não há erros de dependência.
            local_time_brt = tx_date_utc + timedelta(hours=-3)
            
            # Verifica se a hora local é >= 20 (20h, 21h, 22h, 23h) ou < 6 (00h, 01h, 02h, 03h, 04h, 05h)
            if (local_time_brt.hour >= 20 or local_time_brt.hour < 6) and amount >= 100000:
                rule_hits.append({
                    "code": "R12",
                    "points": 2,
                    "detail": f"Transação em horário de risco ({local_time_brt.strftime('%H:%M')} BRT) com valor de R$ {amount/100:.2f}."
                })
        except (AttributeError, TypeError, ValueError, OverflowError) as e:
            logger.warning("Não foi possível avaliar o horário na regra R12: %s", e)

        # R28: Valor colado no piso (>= 3 Pix em 24h, entre R$ 4.500 e R$ 4.999,99) -> 2 pontos
        if 450000 <= amount <= 499999:
            # 1440 minutos = 24 horas
            recent_24h = self.repository.get_transactions_in_minutes(session, source_doc, minutes=1440)
            
            # Filtra apenas os Pix da janela que também estão "colados no piso"
            # O getattr extrai o valor real e evita que o Pylance confunda com a Column do SQLAlchemy
            floor_hugging_txs = [tx for tx in recent_24h if 450000 <= getattr(tx, 'amount', 0) <= 499999]
            
            # Conta com o atual
            if len(floor_hugging_txs) + 1 >= 3:
                rule_hits.append({
                    "code": "R28",
                    "points": 2,
                    "detail": f"Valor colado no piso: {len(floor_hugging_txs) + 1} Pix entre R$ 4.500 e R$ 4.999 em 24h."
                })

        # R29: Fracionamento por documento (>= 4 Pix p/ mesmo CPF/CNPJ destino em 60 min, soma >= R$ 5.000) -> 2 pontos
        dest_doc = input_data["destination_account"]["owner"]["document_number"]
        recent_60m = self.repository.get_transactions_in_minutes(session, source_doc, minutes=60)
        
        txs_same_dest_doc_60m = []
        for tx in recent_60m:
            payload = getattr(tx, 'payload', {})
            if isinstance(payload, str):
                import json
                try: payload = json.loads(payload)
                except: payload = {}
            
            if isinstance(payload, dict):
                doc = payload.get("destination_account", {}).get("owner", {}).get("document_number")
                if doc == dest_doc:
                    txs_same_dest_doc_60m.append(tx)

        if len(txs_same_dest_doc_60m) + 1 >= 4:
            sum_r29 = sum(getattr(tx, 'amount', 0) for tx in txs_same_dest_doc_60m) + amount
            if sum_r29 >= 500000:
                # Verifica se é recorrente: tem de ter >= 3 Pix para este doc ANTES desta janela de 60 min
                recurrent_count = 0
                for tx in user_history:
                    # Se está no histórico mas não nos últimos 60 min, então é um Pix antigo (anterior à janela)
                    if tx not in recent_60m:
                        payload = getattr(tx, 'payload', {})
                        if isinstance(payload, str):
                            import json
                            try: payload = json.loads(payload)
                            except: payload = {}
                        if isinstance(payload, dict):
                            doc = payload.get("destination_account", {}).get("owner", {}).get("document_number")
                            if doc == dest_doc:
                                recurrent_count += 1
                                
                if recurrent_count < 3:
                    rule_hits.append({
                        "code": "R29",
                        "points": 2,
                        "detail": f"Fracionamento por documento: {len(txs_same_dest_doc_60m) + 1} Pix p/ o mesmo destinatário (contas diferentes) somando R$ {sum_r29/100:.2f} em 60 min."
                    })

        # ==========================================
        # CONTEXTO EPP (R13 - R27, R30 - R32)
        # ==========================================
        context_data = input_data.get("context")

        if context_data:
            author_id = context_data.get("author_id")
            author_limit = context_data.get("author_limit")
            approval_trigger = context_data.get("approval_trigger")
            limits = [
                limit
                for limit in (author_limit, approval_trigger)
                if isinstance(limit, (int, float)) and not isinstance(limit, bool)
            ]

            if limits and author_id:
                min_limit = min(limits)
                lower_bound = int(min_limit * 0.90)
                upper_bound = int(min_limit * 0.999)

                if lower_bound <= amount <= upper_bound:
                    recent_24h_company = self.repository.get_transactions_in_minutes(
                        session,
                        source_doc,
                        minutes=1440
                    )
                    hugging_author_txs = []
                    for tx in recent_24h_company:
                        tx_payload = getattr(tx, "payload", {}) or {}
                        if isinstance(tx_payload, str):
                            try:
                                tx_payload = json.loads(tx_payload)
                            except json.JSONDecodeError:
                                logger.warning("Payload inválido em JSON no histórico usado pela regra R13.")
                                continue

                        if not isinstance(tx_payload, dict):
                            continue

                        tx_context = tx_payload.get("context")
                        if not isinstance(tx_context, dict) or tx_context.get("author_id") != author_id:
                            continue

                        tx_amount = getattr(tx, "amount", 0)
                        if lower_bound <= tx_amount <= upper_bound:
                            hugging_author_txs.append(tx)

                    if len(hugging_author_txs) + 1 >= 3:
                        recurrent_company_count = 0
                        for tx in user_history:
                            if tx in recent_24h_company:
                                continue

                            tx_payload = getattr(tx, "payload", {}) or {}
                            if isinstance(tx_payload, str):
                                try:
                                    tx_payload = json.loads(tx_payload)
                                except json.JSONDecodeError:
                                    logger.warning("Payload inválido em JSON no histórico de recorrência da regra R13.")
                                    continue

                            if not isinstance(tx_payload, dict):
                                continue

                            destination = tx_payload.get("destination_account")
                            owner = destination.get("owner") if isinstance(destination, dict) else None
                            if isinstance(owner, dict) and owner.get("document_number") == dest_doc:
                                recurrent_company_count += 1

                        if recurrent_company_count < 3:
                            rule_hits.append({
                                "code": "R13",
                                "points": 2,
                                "detail": f"Teste de limite EPP: {len(hugging_author_txs) + 1} pedidos colados no teto de R$ {min_limit/100:.2f}."
                            })

        # Agrupamento e Tetos por Família (Conforme RFC)
        value_rules = [h for h in rule_hits if h["code"] in ["R1", "R3", "R4", "R28"]]
        frac_rules = [h for h in rule_hits if h["code"] in ["R8", "R29"]]
        internal_controls_rules = [h for h in rule_hits if h["code"] in ["R13", "R14", "R16"]]
        other_rules = [h for h in rule_hits if h["code"] not in ["R1", "R3", "R4", "R28", "R8", "R29", "R13", "R14", "R16"]]

        value_points = min(3, sum(h["points"] for h in value_rules))
        frac_points = min(2, sum(h["points"] for h in frac_rules))
        internal_points = min(3, sum(h["points"] for h in internal_controls_rules))
        other_points = sum(h["points"] for h in other_rules)
        total_score = value_points + frac_points + internal_points + other_points

        # 5. Mapeamento de Status baseado no Score total acumulado
        # 0-1: approved | 2-4: two_factor_required | >=5: rejected[cite: 20]
        if total_score >= 5:
            status = "rejected"
        elif total_score >= 2:
            status = "two_factor_required"
        else:
            status = "approved"

        metadata = {
            "risk_score": total_score,
            "rules_version": "v1.0-hackathon",
            "rules_triggered": [h["code"] for h in rule_hits]
        }

        # 6. Persistência atômica no banco de dados
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