import json
import statistics
import math
from datetime import datetime, timezone, timedelta
from database import get_context
from repositories.pix_repository import PixRepository
from utils.logger import get_logger


logger = get_logger(__name__)


def _as_utc_datetime(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
            recent_24h_company = self.repository.get_transactions_in_minutes(
                session,
                source_doc,
                minutes=1440
            )
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

        # R14: Recriação após recusa (Mesmo destino, mesmo autor, valor 80-120% de um pedido anterior nas últimas 24h) -> 2 pontos
            if context_data.get("event") == "request":
                for tx in recent_24h_company:
                    # Ignora a transação atual
                    if str(tx.id) == str(pix_id):
                        continue
                        
                    tx_payload = getattr(tx, 'payload', {})
                    if isinstance(tx_payload, str):
                        import json
                        try: tx_payload = json.loads(tx_payload)
                        except: tx_payload = {}
                        
                    if isinstance(tx_payload, dict):
                        tx_context = tx_payload.get("context", {})
                        
                        # Procura outro "request" do mesmo autor nas últimas 24h
                        if tx_context.get("event") == "request" and tx_context.get("author_id") == author_id:
                            tx_dest_doc = tx_payload.get("destination_account", {}).get("owner", {}).get("document_number")
                            
                            # Se for para o mesmo destinatário, verificamos se o valor está na margem de manobra (80% a 120%)
                            if tx_dest_doc == dest_doc:
                                prev_amount = int(getattr(tx, 'amount', 0))
                                
                                if prev_amount > 0 and (prev_amount * 0.8) <= amount <= (prev_amount * 1.2):
                                    rule_hits.append({
                                        "code": "R14",
                                        "points": 2,
                                        "detail": f"Recriação de pedido: R$ {amount/100:.2f} está na margem de um pedido anterior de R$ {prev_amount/100:.2f} para o mesmo destino."
                                    })
                                    break  # Dispara a regra e sai do loop para não pontuar a dobrar
        
        # R15: Aprovação disfarçada (Voto com o mesmo device do autor, ou mesmo IP em < 10s) -> 3 pontos
            if context_data.get("event") == "vote":
                request_id = context_data.get("request_id")
                if request_id:
                    # Vai buscar o pedido original à base de dados
                    original_req = self.repository.get_transaction_by_id(session, request_id)
                    
                    if original_req:
                        req_payload = getattr(original_req, 'payload', {})
                        if isinstance(req_payload, str):
                            import json
                            try: req_payload = json.loads(req_payload)
                            except: req_payload = {}
                            
                        if isinstance(req_payload, dict):
                            orig_source = req_payload.get("source", {})
                            orig_device = orig_source.get("device_id")
                            orig_ip = orig_source.get("ip")
                            
                            curr_source = input_data.get("source", {})
                            curr_device = curr_source.get("device_id")
                            curr_ip = curr_source.get("ip")
                            
                            r15_triggered = False
                            detail_msg = ""
                            
                            # Condição A: Mesmo dispositivo (Muito forte, não importa o tempo)
                            if curr_device and orig_device and curr_device == orig_device:
                                r15_triggered = True
                                detail_msg = f"Aprovação disfarçada: Voto efetuado com o mesmo dispositivo ({curr_device}) que criou o pedido."
                            
                            # Condição B: Mesmo IP num curtíssimo espaço de tempo (< 10 segundos)
                            elif curr_ip and orig_ip and curr_ip == orig_ip:
                                try:
                                    orig_time = _as_utc_datetime(original_req.transaction_date)
                                    curr_time = _as_utc_datetime(input_data["transaction_date"])
                                    diff_seconds = (curr_time - orig_time).total_seconds()
                                    
                                    if 0 <= diff_seconds < 10:
                                        r15_triggered = True
                                        detail_msg = f"Aprovação disfarçada: Voto com o mesmo IP ({curr_ip}) apenas {diff_seconds:.1f}s após a criação do pedido."
                                except (AttributeError, TypeError, ValueError, OverflowError) as e:
                                    logger.warning("Falha ao calcular datas na R15: %s", e)
                                    
                            if r15_triggered:
                                rule_hits.append({
                                    "code": "R15",
                                    "points": 3,
                                    "detail": detail_msg
                                })

            # R16: Afrouxamento de controle seguido de uso (v5) -> 3 pontos
            control_loosened = context_data.get("control_loosened_at")
            company_opening = input_data.get("source_account", {}).get("opening_date")
            if control_loosened and company_opening and context_data.get("event") == "request":
                try:
                    company_opening_time = _as_utc_datetime(company_opening)
                    loosened_time = _as_utc_datetime(control_loosened)
                    current_time = _as_utc_datetime(input_data["transaction_date"])

                    company_age = current_time - company_opening_time
                    elapsed_since_loosened = current_time - loosened_time
                    if (
                        company_age >= timedelta(days=7)
                        and timedelta(0) <= elapsed_since_loosened <= timedelta(hours=24)
                    ):
                        diff_hours = elapsed_since_loosened.total_seconds() / 3600.0
                        rule_hits.append({
                            "code": "R16",
                            "points": 3,
                            "detail": f"Afrouxamento recente: pedido criado {diff_hours:.1f}h após alteração crítica de controles."
                        })
                except (AttributeError, TypeError, ValueError, OverflowError) as e:
                    logger.warning("Falha ao calcular datas na R16: %s", e)

            # Histórico de pedidos não rejeitados deste autor, usado por R17 e R18
            author_past_requests = []
            if author_id:
                for tx in user_history:
                    tx_payload = getattr(tx, "payload", {}) or {}
                    if isinstance(tx_payload, str):
                        try:
                            tx_payload = json.loads(tx_payload)
                        except json.JSONDecodeError:
                            logger.warning("Payload inválido em JSON no histórico do autor para R17/R18.")
                            continue

                    if not isinstance(tx_payload, dict):
                        continue

                    tx_context = tx_payload.get("context")
                    if (
                        isinstance(tx_context, dict)
                        and tx_context.get("author_id") == author_id
                        and tx_context.get("event") == "request"
                    ):
                        author_past_requests.append((tx, tx_payload))

            # R17: Dispositivo novo do sócio (valor >= R$ 500, histórico >= 3) -> 2 pontos
            if (
                context_data.get("event") == "request"
                and amount >= 50000
                and len(author_past_requests) >= 3
            ):
                recent_author_devices = {
                    tx_payload["source"]["device_id"]
                    for _, tx_payload in author_past_requests[:20]
                    if isinstance(tx_payload.get("source"), dict)
                    and tx_payload["source"].get("device_id")
                }
                current_device = input_data.get("source", {}).get("device_id")
                if current_device and current_device not in recent_author_devices:
                    rule_hits.append({
                        "code": "R17",
                        "points": 2,
                        "detail": f"Dispositivo novo do sócio: aparelho {current_device} não consta nos pedidos recentes deste autor."
                    })

        # R18: Deslocamento ou mudança de IP do sócio em até 12h -> 3 pontos
            if context_data.get("event") == "request" and author_past_requests:
                last_tx, last_payload = author_past_requests[0]
                current_source = input_data.get("source", {})
                last_source = last_payload.get("source")
                if isinstance(last_source, dict):
                    try:
                        previous_time = _as_utc_datetime(last_tx.transaction_date)
                        current_time = _as_utc_datetime(input_data["transaction_date"])
                        diff_hours = (current_time - previous_time).total_seconds() / 3600.0

                        if 0 < diff_hours <= 12:
                            current_geo = current_source.get("geolocation")
                            previous_geo = last_source.get("geolocation")
                            current_ip = current_source.get("ip")
                            previous_ip = last_source.get("ip")
                            triggered = False
                            detail = ""

                            if (
                                isinstance(current_geo, dict)
                                and isinstance(previous_geo, dict)
                                and all(key in current_geo for key in ("latitude", "longitude"))
                                and all(key in previous_geo for key in ("latitude", "longitude"))
                            ):
                                distance_km = calculate_distance_km(
                                    float(previous_geo["latitude"]),
                                    float(previous_geo["longitude"]),
                                    float(current_geo["latitude"]),
                                    float(current_geo["longitude"]),
                                )
                                if distance_km >= 50 and distance_km / diff_hours > 900:
                                    triggered = True
                                    detail = f"Deslocamento impossível do sócio: {distance_km:.1f} km em {diff_hours:.1f} h."
                            elif current_ip and previous_ip and current_ip != previous_ip:
                                triggered = True
                                detail = f"Mudança de IP do sócio ({previous_ip} para {current_ip}) em {diff_hours:.1f} h sem geolocalização."

                            if triggered:
                                rule_hits.append({
                                    "code": "R18",
                                    "points": 3,
                                    "detail": detail
                                })
                    except (AttributeError, TypeError, ValueError, OverflowError) as e:
                        logger.warning("Falha na avaliação da R18: %s", e)

        # R19
        # DESISTO

        # R20: Esvaziamento (saídas livres em 24h >= 70% do saldo e >= R$ 5.000) -> 2 pontos
            free_balance = context_data.get("free_balance")
            if (
                context_data.get("event") == "request"
                and isinstance(free_balance, (int, float))
                and not isinstance(free_balance, bool)
                and free_balance > 0
            ):
                recent_company_outflows = 0
                for tx in recent_24h_company:
                    tx_payload = getattr(tx, "payload", {}) or {}
                    if isinstance(tx_payload, str):
                        try:
                            tx_payload = json.loads(tx_payload)
                        except json.JSONDecodeError:
                            logger.warning("Payload inválido em JSON no histórico usado pela regra R20.")
                            continue

                    if not isinstance(tx_payload, dict):
                        continue

                    tx_context = tx_payload.get("context")
                    if (
                        isinstance(tx_context, dict)
                        and tx_context.get("event") == "request"
                        and not tx_context.get("responsibility_id")
                    ):
                        recent_company_outflows += int(getattr(tx, "amount", 0))

                total_outflow_24h = recent_company_outflows + amount
                original_free_balance = free_balance + recent_company_outflows
                if (
                    total_outflow_24h >= 500000
                    and total_outflow_24h >= original_free_balance * 0.70
                ):
                    rule_hits.append({
                        "code": "R20",
                        "points": 2,
                        "detail": f"Esvaziamento de conta: saídas em 24h (R$ {total_outflow_24h/100:.2f}) atingiram pelo menos 70% do saldo livre."
                    })

        # R21: Libertação de reserva seguida de saída (<= 30 min, >= 80% libertado, contraparte nova) -> 3 pontos
            if context_data.get("event") == "request":
                reserved_released = context_data.get("reserved_amount_released")
                released_at_str = context_data.get("reserved_released_at")
                
                if reserved_released and released_at_str:
                    # Verifica se o valor a transferir é pelo menos 80% do valor que foi libertado
                    if amount >= (reserved_released * 0.80):
                        try:
                            released_time = _as_utc_datetime(released_at_str)
                            curr_time = _as_utc_datetime(input_data["transaction_date"])
                            
                            diff_mins = (curr_time - released_time).total_seconds() / 60.0
                            
                            if 0 <= diff_mins <= 30:
                                # Vamos procurar no histórico se este destinatário (dest_doc) já recebeu dinheiro da empresa
                                dest_doc = input_data.get("destination_account", {}).get("owner", {}).get("document_number")
                                has_history = False
                                
                                for tx in user_history:
                                    tx_payload = getattr(tx, 'payload', {})
                                    if isinstance(tx_payload, str):
                                        import json
                                        try: tx_payload = json.loads(tx_payload)
                                        except: tx_payload = {}
                                        
                                    if isinstance(tx_payload, dict):
                                        past_dest_doc = tx_payload.get("destination_account", {}).get("owner", {}).get("document_number")
                                        if past_dest_doc == dest_doc:
                                            has_history = True
                                            break
                                            
                                if not has_history:
                                    rule_hits.append({
                                        "code": "R21",
                                        "points": 3,
                                        "detail": f"Evasão de reserva: Saída para novo destinatário apenas {diff_mins:.1f} min após libertação de R$ {reserved_released/100:.2f}."
                                    })
                        except Exception as e:
                            logger.warning("Falha na avaliação da R21: %s", e)

        # R22: Empresa recém-aberta (<= 30 dias) a realizar pedido de alto valor (>= R$ 5.000) -> 2 pontos
            if context_data.get("event") == "request" and amount >= 500000:
                opening_date_str = input_data.get("source_account", {}).get("opening_date")
                
                if opening_date_str:
                    try:
                        opening_date = _as_utc_datetime(opening_date_str)
                        curr_time = _as_utc_datetime(input_data["transaction_date"])
                        
                        # Calcula a diferença em dias
                        diff_days = (curr_time - opening_date).days
                        
                        # Dispara se a empresa tem 30 dias ou menos de vida
                        if 0 <= diff_days <= 30:
                            rule_hits.append({
                                "code": "R22",
                                "points": 2,
                                "detail": f"Maturidade suspeita: A empresa tem apenas {diff_days} dias de abertura e tenta transferir R$ {amount/100:.2f}."
                            })
                    except Exception as e:
                        logger.warning("Falha na avaliação da R22: %s", e)

        # R23: Destinatário recém-aberto (<= 30 dias) a receber pedido de alto valor (>= R$ 5.000) -> 2 pontos
            if context_data.get("event") == "request" and amount >= 500000:
                dest_opening_str = input_data.get("destination_account", {}).get("opening_date")
                
                if dest_opening_str:
                    try:
                        dest_opening = _as_utc_datetime(dest_opening_str)
                        curr_time = _as_utc_datetime(input_data["transaction_date"])
                        
                        # Calcula a diferença em dias
                        diff_days_dest = (curr_time - dest_opening).days
                        
                        # Dispara se a conta de destino tem 30 dias ou menos de vida
                        if 0 <= diff_days_dest <= 30:
                            rule_hits.append({
                                "code": "R23",
                                "points": 2,
                                "detail": f"Destinatário recente: A conta de destino tem apenas {diff_days_dest} dias de abertura."
                            })
                    except Exception as e:
                        logger.warning("Falha na avaliação da R23: %s", e)
        
        # R24: Primeiro envio para destinatário inédito acima de R$ 5.000 -> 2 pontos
            if context_data.get("event") == "request" and amount >= 500000:
                destination = input_data.get("destination_account", {})
                owner = destination.get("owner", {}) if isinstance(destination, dict) else {}
                dest_doc = owner.get("document_number") if isinstance(owner, dict) else None

                if dest_doc:
                    has_prior_transfer = False
                    for tx in user_history:
                        tx_payload = getattr(tx, "payload", {}) or {}
                        if isinstance(tx_payload, str):
                            try:
                                tx_payload = json.loads(tx_payload)
                            except json.JSONDecodeError as e:
                                logger.warning("Payload inválido no histórico usado pela regra R24: %s", e)
                                continue
                        if not isinstance(tx_payload, dict):
                            continue

                        past_destination = tx_payload.get("destination_account")
                        past_owner = past_destination.get("owner", {}) if isinstance(past_destination, dict) else {}
                        if isinstance(past_owner, dict) and past_owner.get("document_number") == dest_doc:
                            has_prior_transfer = True
                            break

                    if not has_prior_transfer:
                        rule_hits.append({
                            "code": "R24",
                            "points": 2,
                            "detail": f"Maturidade suspeita: primeira transferência da empresa para o destinatário inédito {dest_doc}."
                        })

        # R25: Pulverização / fan-out (3 destinatários distintos em até 30 min) -> 3 pontos
            if context_data.get("event") == "request":
                try:
                    curr_time = _as_utc_datetime(input_data["transaction_date"])
                except (KeyError, TypeError, ValueError, OverflowError) as e:
                    logger.warning("Data inválida na avaliação da R25: %s", e)
                else:
                    destination = input_data.get("destination_account", {})
                    owner = destination.get("owner", {}) if isinstance(destination, dict) else {}
                    curr_dest = owner.get("document_number") if isinstance(owner, dict) else None
                    if curr_dest:
                        recent_dests = {curr_dest}
                        for tx in recent_24h_company:
                            tx_payload = getattr(tx, "payload", {}) or {}
                            if isinstance(tx_payload, str):
                                try:
                                    tx_payload = json.loads(tx_payload)
                                except json.JSONDecodeError as e:
                                    logger.warning("Payload inválido no histórico usado pela regra R25: %s", e)
                                    continue
                            if not isinstance(tx_payload, dict):
                                continue

                            tx_context = tx_payload.get("context")
                            if not isinstance(tx_context, dict) or tx_context.get("event") != "request":
                                continue
                            try:
                                tx_time = _as_utc_datetime(tx.transaction_date)
                            except (AttributeError, TypeError, ValueError, OverflowError) as e:
                                logger.warning("Data inválida no histórico usado pela regra R25: %s", e)
                                continue

                            diff_mins = (curr_time - tx_time).total_seconds() / 60.0
                            if 0 <= diff_mins <= 30:
                                tx_destination = tx_payload.get("destination_account")
                                tx_owner = tx_destination.get("owner", {}) if isinstance(tx_destination, dict) else {}
                                tx_dest = tx_owner.get("document_number") if isinstance(tx_owner, dict) else None
                                if tx_dest:
                                    recent_dests.add(tx_dest)

                        if len(recent_dests) >= 3:
                            rule_hits.append({
                                "code": "R25",
                                "points": 3,
                                "detail": f"Pulverização detetada: transferências para {len(recent_dests)} destinatários distintos em até 30 minutos."
                            })

        # R26: Ping de valor até R$ 2,00 para destinatário inédito -> 2 pontos
            if context_data.get("event") == "request" and amount <= 200:
                destination = input_data.get("destination_account", {})
                owner = destination.get("owner", {}) if isinstance(destination, dict) else {}
                dest_doc_r26 = owner.get("document_number") if isinstance(owner, dict) else None

                if dest_doc_r26:
                    has_prior_r26 = False
                    for tx in user_history:
                        tx_payload = getattr(tx, "payload", {}) or {}
                        if isinstance(tx_payload, str):
                            try:
                                tx_payload = json.loads(tx_payload)
                            except json.JSONDecodeError as e:
                                logger.warning("Payload inválido no histórico usado pela regra R26: %s", e)
                                continue
                        if not isinstance(tx_payload, dict):
                            continue

                        past_destination = tx_payload.get("destination_account")
                        past_owner = past_destination.get("owner", {}) if isinstance(past_destination, dict) else {}
                        if isinstance(past_owner, dict) and past_owner.get("document_number") == dest_doc_r26:
                            has_prior_r26 = True
                            break

                    if not has_prior_r26:
                        rule_hits.append({
                            "code": "R26",
                            "points": 2,
                            "detail": f"Teste de invasão (ping): envio de valor irrisório (R$ {amount/100:.2f}) para destinatário inédito."
                        })

        # R27: Evasão de fim de semana para destinatário inédito -> 3 pontos
            # DESISTO

        # R30: Saída da empresa fora do padrão (v5) -> 2 pontos
            if context_data.get("event") == "request":
                # Verifica isenção: ignora pagamento coberto por reserva e execução agendada
                is_scheduled_execution = context_data.get("event") == "execution" and context_data.get("origin") == "scheduled"
                is_reserved = bool(context_data.get("responsibility_id"))
                
                if not is_scheduled_execution and not is_reserved:
                    company_opening_str = input_data.get("source_account", {}).get("opening_date")
                    if company_opening_str:
                        try:
                            company_opening = _as_utc_datetime(company_opening_str)
                            curr_time = _as_utc_datetime(input_data["transaction_date"])
                            company_age_days = (curr_time - company_opening).days
                            
                            # A empresa tem de ter pelo menos 30 dias de ativação
                            if company_age_days >= 30:
                                # Busca histórico de 31 dias (44.640 minutos)
                                recent_31d = self.repository.get_transactions_in_minutes(session, source_doc, minutes=44640)
                                
                                outflows_24h = amount
                                outflows_prior_30d = 0
                                count_prior_30d = 0
                                
                                for tx in recent_31d:
                                    # Evita contar o próprio evento atual, caso já tenha passado no lock
                                    if str(tx.id) == str(pix_id):
                                        continue
                                        
                                    tx_time = _as_utc_datetime(tx.transaction_date)
                                    diff_hours = (curr_time - tx_time).total_seconds() / 3600.0
                                    
                                    tx_payload = getattr(tx, 'payload', {})
                                    if isinstance(tx_payload, str):
                                        try: tx_payload = json.loads(tx_payload)
                                        except: tx_payload = {}
                                        
                                    if isinstance(tx_payload, dict):
                                        ctx = tx_payload.get("context", {})
                                        tx_is_scheduled_exec = ctx.get("event") == "execution" and ctx.get("origin") == "scheduled"
                                        tx_is_reserved = bool(ctx.get("responsibility_id"))
                                        
                                        # Só contabiliza saídas livres
                                        if not tx_is_scheduled_exec and not tx_is_reserved:
                                            tx_amt = int(getattr(tx, "amount", 0))
                                            
                                            # Saídas nas últimas 24 horas
                                            if 0 <= diff_hours <= 24:
                                                outflows_24h += tx_amt
                                            # Saídas nos 30 dias anteriores à janela de 24h
                                            elif 24 < diff_hours <= (31 * 24):
                                                outflows_prior_30d += tx_amt
                                                count_prior_30d += 1
                                                
                                # Exige pelo menos 10 saídas no período base para ter média confiável
                                if count_prior_30d >= 10:
                                    daily_avg_30d = outflows_prior_30d / 30.0
                                    
                                    if outflows_24h >= 1000000 and outflows_24h >= 3 * daily_avg_30d:
                                        rule_hits.append({
                                            "code": "R30",
                                            "points": 2,
                                            "detail": f"Saída fora do padrão: R$ {outflows_24h/100:.2f} em 24h supera 3x a média diária (R$ {daily_avg_30d/100:.2f}) do histórico."
                                        })
                        except Exception as e:
                            logger.warning("Falha na avaliação da R30: %s", e)

        # R31: Destino ligado a sócio (v5) -> 2 pontos
            if context_data.get("event") == "request" and amount >= 200000:
                source_partners = context_data.get("partner_documents", [])
                dest_partners = context_data.get("destination_partner_documents", [])
                
                is_linked = False
                # Interseção entre os sócios da origem e do destino
                if source_partners and dest_partners:
                    if set(source_partners).intersection(set(dest_partners)):
                        is_linked = True
                        
                if is_linked:
                    dest_doc_r31 = input_data.get("destination_account", {}).get("owner", {}).get("document_number")
                    is_exempt_r31 = False
                    
                    # Verifica isenção: Contraparte Recorrente (v6) com valor ±20% do pró-labore
                    past_txs_r31 = []
                    for tx in user_history:
                        tx_payload = getattr(tx, 'payload', {})
                        if isinstance(tx_payload, str):
                            try: tx_payload = json.loads(tx_payload)
                            except: tx_payload = {}
                        if isinstance(tx_payload, dict):
                            past_dest = tx_payload.get("destination_account", {}).get("owner", {}).get("document_number")
                            if past_dest == dest_doc_r31:
                                past_txs_r31.append(tx)
                                
                    if len(past_txs_r31) >= 3:
                        try:
                            first_tx_time = min(_as_utc_datetime(tx.transaction_date) for tx in past_txs_r31)
                            curr_time = _as_utc_datetime(input_data["transaction_date"])
                            
                            # Relação com 30 dias ou mais
                            if (curr_time - first_tx_time).days >= 30:
                                sum_past = sum(getattr(tx, "amount", 0) for tx in past_txs_r31)
                                if sum_past >= 100000:
                                    max_past = max(getattr(tx, "amount", 0) for tx in past_txs_r31)
                                    # Margem estrita de 80% a 120% do maior Pix já pago
                                    if (max_past * 0.8) <= amount <= (max_past * 1.2):
                                        is_exempt_r31 = True
                        except Exception as e:
                            logger.warning("Falha na isenção recorrente da R31: %s", e)
                            
                    if not is_exempt_r31:
                        rule_hits.append({
                            "code": "R31",
                            "points": 2,
                            "detail": "Destino ligado a sócio: A conta destino possui vínculos societários cruzados com a empresa pagadora."
                        })

        # R32: Credencial trocada seguida de saída (v5) -> 2 pontos
            if context_data.get("event") == "request" and context_data.get("origin") == "immediate" and amount >= 200000:
                credential_changed_str = context_data.get("credential_changed_at")
                
                if credential_changed_str:
                    try:
                        changed_time = _as_utc_datetime(credential_changed_str)
                        curr_time = _as_utc_datetime(input_data["transaction_date"])
                        
                        # Verifica se a troca foi nas últimas 24h
                        diff_hours = (curr_time - changed_time).total_seconds() / 3600.0
                        
                        if 0 <= diff_hours <= 24:
                            # Ignora se a credencial foi criada há < 7 dias. 
                            # Como a API não define 'author_created_at', usamos a abertura da conta da empresa como proxy conservador
                            account_opening_str = input_data.get("source_account", {}).get("opening_date")
                            is_recent_credential = False
                            
                            if account_opening_str:
                                opening_time = _as_utc_datetime(account_opening_str)
                                if (curr_time - opening_time).days < 7:
                                    is_recent_credential = True
                            
                            if not is_recent_credential:
                                rule_hits.append({
                                    "code": "R32",
                                    "points": 2,
                                    "detail": f"Risco de Invasão (ATO): Pedido de R$ {amount/100:.2f} efetuado apenas {diff_hours:.1f}h após alteração crítica de credenciais."
                                })
                    except Exception as e:
                        logger.warning("Falha na avaliação da R32: %s", e)

        # R33: Salto de valor na contraparte (v6) -> 2 pontos
        if amount >= 100000:
            # Verifica isenção EPP (execução de agendamento não pontua)
            is_scheduled_execution = context_data and context_data.get("event") == "execution" and context_data.get("origin") == "scheduled"
            
            if not is_scheduled_execution:
                dest_doc_r33 = input_data.get("destination_account", {}).get("owner", {}).get("document_number")
                if dest_doc_r33:
                    past_txs_dest_r33 = []
                    curr_time = _as_utc_datetime(input_data["transaction_date"])
                    
                    # Procura no histórico aprovado (user_history) transferências para este destino nos últimos 180 dias
                    for tx in user_history:
                        try:
                            tx_time = _as_utc_datetime(tx.transaction_date)
                            if (curr_time - tx_time).days <= 180:
                                tx_payload = getattr(tx, 'payload', {})
                                if isinstance(tx_payload, str):
                                    try: tx_payload = json.loads(tx_payload)
                                    except: tx_payload = {}
                                    
                                if isinstance(tx_payload, dict):
                                    past_dest = tx_payload.get("destination_account", {}).get("owner", {}).get("document_number")
                                    if past_dest == dest_doc_r33:
                                        past_txs_dest_r33.append(tx)
                        except Exception as e:
                            logger.warning("Falha na extração de datas da R33: %s", e)
                            
                    if len(past_txs_dest_r33) >= 1:
                        # Qual foi o maior valor que já enviámos a este gajo?
                        max_past_amount = max(getattr(tx, "amount", 0) for tx in past_txs_dest_r33)
                        
                        # O valor atual é 5x superior a esse máximo?
                        if max_past_amount > 0 and amount >= (5 * max_past_amount):
                            rule_hits.append({
                                "code": "R33",
                                "points": 2,
                                "detail": f"Salto de valor: R$ {amount/100:.2f} é >= 5x o maior valor já enviado a esta contraparte (R$ {max_past_amount/100:.2f})."
                            })

        # Agrupamento e tetos por família
        value_rules = [h for h in rule_hits if h["code"] in ["R1", "R3", "R4", "R28", "R33"]]        
        frac_rules = [h for h in rule_hits if h["code"] in ["R8", "R29"]]
        internal_controls_rules = [h for h in rule_hits if h["code"] in ["R13", "R14", "R16"]]        
        session_rules = [h for h in rule_hits if h["code"] in ["R17", "R18", "R19", "R32"]]        
        account_behavior_rules = [h for h in rule_hits if h["code"] in ["R20", "R21"]]
        maturity_rules = [h for h in rule_hits if h["code"] in ["R23", "R24"]]
        linked_destination_rules = [h for h in rule_hits if h["code"] in ["R22", "R31"]]
        company_outflow_rules = [h for h in rule_hits if h["code"] == "R30"]
        anomaly_rules = [h for h in rule_hits if h["code"] in ["R25", "R26", "R27"]]

        grouped_rule_codes = {
            "R1", "R3", "R4", "R28", "R33",
            "R8", "R29",
            "R13", "R14", "R16", "R30",
            "R17", "R18", "R19", "R32",
            "R20", "R21",
            "R22", "R23", "R24",
            "R25", "R26", "R27", "R31"
        }
        other_rules = [h for h in rule_hits if h["code"] not in grouped_rule_codes]

        value_points = min(3, sum(h["points"] for h in value_rules))
        frac_points = min(2, sum(h["points"] for h in frac_rules))
        internal_points = min(3, sum(h["points"] for h in internal_controls_rules))
        session_points = min(4, sum(h["points"] for h in session_rules))
        account_behavior_points = min(3, sum(h["points"] for h in account_behavior_rules))
        maturity_points = min(3, sum(h["points"] for h in maturity_rules))
        linked_destination_points = min(2, sum(h["points"] for h in linked_destination_rules))
        company_outflow_points = sum(h["points"] for h in company_outflow_rules)
        anomaly_points = min(4, sum(h["points"] for h in anomaly_rules))
        other_points = sum(h["points"] for h in other_rules)

        total_score = (
            value_points
            + frac_points
            + internal_points
            + session_points
            + account_behavior_points
            + maturity_points
            + linked_destination_points
            + company_outflow_points
            + anomaly_points
            + other_points
        )
        
        # O código a partir daqui deve ser aquele onde gravas os hits na base de dados (se for o caso)
        # e onde devolves a resposta final ao utilizador (rejected / approved / etc).

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