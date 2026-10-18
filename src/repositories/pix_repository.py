import hashlib
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.pix_model import PixTransactionModel, PixDecisionModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from errors.custom_errors import ConflictError, NotFoundError, ServiceUnavailableError
from history_snapshot import PixHistory
from utils.pix_data import destination_key, parse_datetime, source_document

class PixRepository:

    def compute_payload_hash(self, payload_dict: dict) -> str:
        """Calcula o SHA-256 do payload normalizado para garantir idempotência."""
        normalized = json.dumps(payload_dict, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_transaction_by_id(self, session: Session, transaction_id: str):
        return session.query(PixTransactionModel).filter(PixTransactionModel.id == transaction_id).first()

    def get_source_history_snapshot(
        self,
        session: Session,
        payer: str,
        event_date: datetime,
        profile_start: datetime,
        count_start: datetime,
        destination: tuple[str, str, str],
        destination_doc: str,
        responsibility_id: str | None,
    ) -> dict:
        """Return a bounded projection, SQL window aggregates and lifetime counts.

        The event history is limited to the last 180 days plus the latest 20
        older events needed to build the trusted payer profile. JSONB columns
        are projected field by field so raw payload/context are never loaded.
        """
        row = session.execute(text("""
            WITH recent AS (
                SELECT p.id, p.amount, p.transaction_date, p.source_document,
                       p.destination_document, d.status AS decision_status, p.payload
                FROM pix_transactions AS p
                LEFT JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :profile_start AND :event_date
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
            ), profile_latest AS (
                SELECT p.id, p.amount, p.transaction_date, p.source_document,
                       p.destination_document, d.status AS decision_status, p.payload
                FROM pix_transactions AS p
                LEFT JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :count_start AND :event_date
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
                ORDER BY p.transaction_date DESC
                LIMIT 20
            ), trusted_latest AS (
                SELECT p.id, p.amount, p.transaction_date, p.source_document,
                       p.destination_document, d.status AS decision_status, p.payload
                FROM pix_transactions AS p
                JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :count_start AND :event_date
                  AND d.status != 'rejected'
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
                ORDER BY p.transaction_date DESC
                LIMIT 20
            ), successful_profile_latest AS (
                SELECT p.id, p.amount, p.transaction_date, p.source_document,
                       p.destination_document, d.status AS decision_status, p.payload
                FROM pix_transactions AS p
                JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :count_start AND :event_date
                  AND p.destination_document != :payer
                  AND d.status != 'rejected'
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
                ORDER BY p.transaction_date DESC
                LIMIT 20
            ), profile_median AS (
                SELECT percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY sample.amount::double precision
                ) AS profile_median
                FROM successful_profile_latest AS sample
            ), relevant AS (
                SELECT * FROM recent
                UNION
                SELECT * FROM profile_latest
                UNION
                SELECT * FROM trusted_latest
                UNION
                SELECT * FROM successful_profile_latest
            ), history_counts AS (
                SELECT COUNT(*) AS source_event_count,
                       COUNT(*) FILTER (
                           WHERE d.status IS NOT NULL AND d.status != 'rejected'
                       ) AS trusted_event_count,
                       COUNT(*) FILTER (
                           WHERE d.status IS NOT NULL AND d.status != 'rejected'
                             AND p.destination_document != :payer
                       ) AS successful_profile_count
                FROM pix_transactions AS p
                LEFT JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :count_start AND :event_date
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
            ), source_metrics AS (
                SELECT
                    COUNT(*) FILTER (
                        WHERE p.transaction_date >= :r2_start
                    ) AS r2_count,
                    COUNT(*) FILTER (
                        WHERE p.transaction_date >= :r3_start
                    ) AS r3_count,
                    COALESCE(SUM(p.amount) FILTER (
                        WHERE p.transaction_date >= :r3_start
                    ), 0) AS r3_sum,
                    COUNT(*) FILTER (
                        WHERE p.transaction_date >= :r8_start
                          AND p.amount < :r8_max_amount
                          AND p.payload #>> '{destination_account,participant}' = :participant
                          AND p.payload #>> '{destination_account,branch}' = :branch
                          AND p.payload #>> '{destination_account,account_number}' = :account_number
                    ) AS r8_count,
                    COALESCE(SUM(p.amount) FILTER (
                        WHERE p.transaction_date >= :r8_start
                          AND p.amount < :r8_max_amount
                          AND p.payload #>> '{destination_account,participant}' = :participant
                          AND p.payload #>> '{destination_account,branch}' = :branch
                          AND p.payload #>> '{destination_account,account_number}' = :account_number
                    ), 0) AS r8_sum
                    ,
                    COALESCE(SUM(p.amount) FILTER (
                        WHERE p.transaction_date >= :r20_start
                          AND NULLIF(p.payload #>> '{context,responsibility_id}', '') IS NULL
                    ), 0) AS r20_sum,
                    COUNT(*) FILTER (
                        WHERE p.transaction_date < :r30_recent_start
                          AND p.transaction_date >= :r30_baseline_start
                          AND NULLIF(p.payload #>> '{context,responsibility_id}', '') IS NULL
                    ) AS r30_baseline_count,
                    COALESCE(SUM(p.amount) FILTER (
                        WHERE p.transaction_date >= :r30_recent_start
                          AND NULLIF(p.payload #>> '{context,responsibility_id}', '') IS NULL
                    ), 0) AS r30_recent_sum
                FROM pix_transactions AS p
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :r30_baseline_start AND :event_date
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
            ), r29_metrics AS (
                SELECT
                    COUNT(*) FILTER (
                        WHERE p.transaction_date >= :r29_recent_start
                    ) AS r29_count,
                    COALESCE(SUM(p.amount) FILTER (
                        WHERE p.transaction_date >= :r29_recent_start
                    ), 0) AS r29_sum,
                    COUNT(DISTINCT (p.transaction_date AT TIME ZONE 'UTC')::date) FILTER (
                        WHERE p.transaction_date < :r29_recent_start
                          AND d.status IS NOT NULL AND d.status != 'rejected'
                    ) AS r29_prior_days,
                    MIN(p.transaction_date) FILTER (
                        WHERE p.transaction_date < :r29_recent_start
                          AND d.status IS NOT NULL AND d.status != 'rejected'
                    ) AS r29_prior_min,
                    COALESCE(MAX(p.amount) FILTER (
                        WHERE p.transaction_date < :r29_recent_start
                          AND d.status IS NOT NULL AND d.status != 'rejected'
                    ), 0) AS r29_prior_max
                FROM pix_transactions AS p
                LEFT JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.destination_document = :destination_doc
                  AND p.transaction_date BETWEEN :r29_start AND :event_date
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
            ), r23_metrics AS (
                SELECT
                    COUNT(*) AS r23_event_count,
                    COUNT(DISTINCT (
                        p.payload #>> '{destination_account,participant}',
                        p.payload #>> '{destination_account,branch}',
                        p.payload #>> '{destination_account,account_number}'
                    )) AS r23_destination_count,
                    COALESCE(BOOL_OR(
                        p.payload #>> '{destination_account,participant}' = :participant
                        AND p.payload #>> '{destination_account,branch}' = :branch
                        AND p.payload #>> '{destination_account,account_number}' = :account_number
                    ), FALSE) AS r23_current_destination_present
                FROM pix_transactions AS p
                JOIN fraud_analysis AS d ON d.transaction_id = p.id
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :r23_start AND :event_date
                  AND p.payload #>> '{context,event}' = 'request'
                  AND p.payload #>> '{context,responsibility_id}' = :responsibility_id
                  AND d.status != 'rejected'
            ), r30_daily AS (
                SELECT (p.transaction_date AT TIME ZONE 'UTC')::date AS event_day,
                       SUM(p.amount) AS amount_total
                FROM pix_transactions AS p
                WHERE p.source_document = :payer
                  AND p.transaction_date BETWEEN :r30_baseline_start AND :r30_recent_start
                  AND p.transaction_date < :r30_recent_start
                  AND NULLIF(p.payload #>> '{context,responsibility_id}', '') IS NULL
                  AND (p.payload #>> '{context,event}' IS NULL
                       OR p.payload #>> '{context,event}' = 'request')
                GROUP BY (p.transaction_date AT TIME ZONE 'UTC')::date
            ), r30_daily_totals AS (
                SELECT COALESCE(SUM(amount_total), 0) AS r30_daily_sum,
                       COALESCE(MAX(amount_total), 0) AS r30_daily_max
                FROM r30_daily
            )
            SELECT
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', r.id,
                            'amount', r.amount,
                            'transaction_date', r.transaction_date,
                            'source_document', r.source_document,
                            'destination_document', r.destination_document,
                            'decision_status', r.decision_status,
                            'payload', jsonb_build_object(
                                'source', jsonb_strip_nulls(jsonb_build_object(
                                    'device_id', r.payload #> '{source,device_id}',
                                    'geolocation', r.payload #> '{source,geolocation}',
                                    'ip', r.payload #> '{source,ip}'
                                )),
                                'destination_account', jsonb_build_object(
                                    'participant', r.payload #> '{destination_account,participant}',
                                    'branch', r.payload #> '{destination_account,branch}',
                                    'account_number', r.payload #> '{destination_account,account_number}',
                                    'opening_date', r.payload #> '{destination_account,opening_date}',
                                    'owner', jsonb_build_object(
                                        'document_number', r.destination_document
                                    )
                                ),
                                'context', jsonb_strip_nulls(jsonb_build_object(
                                    'event', r.payload #> '{context,event}',
                                    'responsibility_id', r.payload #> '{context,responsibility_id}',
                                    'author_id', r.payload #> '{context,author_id}',
                                    'company_id', r.payload #> '{context,company_id}',
                                    'origin', r.payload #> '{context,origin}',
                                    'request_id', r.payload #> '{context,request_id}',
                                    'request_hash', r.payload #> '{context,request_hash}'
                                ))
                            )
                        ) ORDER BY r.transaction_date
                    )
                    FROM relevant AS r
                ), '[]'::jsonb) AS events,
                hc.source_event_count,
                hc.trusted_event_count,
                hc.successful_profile_count,
                pm.profile_median,
                sm.r2_count, sm.r3_count, sm.r3_sum, sm.r8_count, sm.r8_sum,
                sm.r20_sum, sm.r30_baseline_count, sm.r30_recent_sum,
                r29.r29_count, r29.r29_sum, r29.r29_prior_max,
                COALESCE(
                    r29.r29_prior_days >= 3
                    AND r29.r29_prior_min <= :event_date - INTERVAL '14 days',
                    FALSE
                ) AS r29_prior_mature,
                r23.r23_event_count, r23.r23_destination_count,
                r23.r23_current_destination_present,
                r30.r30_daily_sum, r30.r30_daily_max,
                EXISTS (
                    SELECT 1
                    FROM pix_transactions AS p
                    JOIN fraud_analysis AS d ON d.transaction_id = p.id
                    WHERE p.source_document = :payer
                      AND p.transaction_date BETWEEN :count_start AND :event_date
                      AND p.payload #>> '{destination_account,participant}' = :participant
                      AND p.payload #>> '{destination_account,branch}' = :branch
                      AND p.payload #>> '{destination_account,account_number}' = :account_number
                      AND d.status != 'rejected'
                      AND (p.payload #>> '{context,event}' IS NULL
                           OR p.payload #>> '{context,event}' = 'request')
                ) AS seen_destination_account
            FROM history_counts AS hc
            CROSS JOIN source_metrics AS sm
            CROSS JOIN profile_median AS pm
            CROSS JOIN r29_metrics AS r29
            CROSS JOIN r23_metrics AS r23
            CROSS JOIN r30_daily_totals AS r30
        """), {
            "payer": payer,
            "event_date": event_date,
            "profile_start": profile_start,
            "count_start": count_start,
            "r2_start": event_date - timedelta(seconds=60),
            "r3_start": event_date - timedelta(minutes=10),
            "r8_start": event_date - timedelta(minutes=5),
            "r20_start": event_date - timedelta(hours=24),
            "r30_recent_start": event_date - timedelta(hours=24),
            "r30_baseline_start": event_date - timedelta(days=31),
            "r29_start": event_date - timedelta(days=180),
            "r29_recent_start": event_date - timedelta(minutes=60),
            "r23_start": event_date - timedelta(days=90),
            "r8_max_amount": 100_000,
            "destination_doc": destination_doc,
            "responsibility_id": responsibility_id,
            "participant": destination[0],
            "branch": destination[1],
            "account_number": destination[2],
        }).mappings().one()
        return dict(row)

    @staticmethod
    def _as_history_event(transaction: PixTransactionModel) -> dict:
        return {
            "id": transaction.id,
            "amount": int(transaction.amount),
            "transaction_date": transaction.transaction_date,
            "source_document": transaction.source_document,
            "destination_document": transaction.destination_document,
            "payload": dict(transaction.payload or {}),
        }

    def build_history(self, session: Session, event: dict) -> PixHistory:
        """Build one bounded, projected history snapshot for all pure rules."""
        event_date = parse_datetime(event["transaction_date"])
        payer = source_document(event)
        destination_doc = str(((event.get("destination_account") or {}).get("owner") or {}).get("document_number", ""))
        epp = event.get("context") or {}
        date_anchor = (
            epp.get("account_activated_at")
            or (event.get("source_account") or {}).get("opening_date")
        )
        count_start = parse_datetime(date_anchor) if date_anchor else event_date - timedelta(days=180)
        count_start = min(count_start, event_date)
        profile_start = max(event_date - timedelta(days=180), count_start)
        snapshot = self.get_source_history_snapshot(
            session,
            payer,
            event_date,
            profile_start,
            count_start,
            destination_key(event),
            destination_doc,
            epp.get("responsibility_id"),
        )
        source_events = tuple(snapshot["events"])
        trusted_events = tuple(
            tx for tx in source_events
            if tx.get("decision_status") is not None and tx["decision_status"] != "rejected"
        )
        source_metrics = {
            key: int(snapshot[key])
            for key in (
                "r2_count", "r3_count", "r3_sum", "r8_count", "r8_sum",
                "r20_sum", "r30_baseline_count", "r30_recent_sum",
                "r29_count", "r29_sum", "r29_prior_max", "r29_prior_mature",
                "r23_event_count", "r23_destination_count",
                "r23_current_destination_present",
                "r30_daily_sum", "r30_daily_max",
            )
        }

        destination_activity = {}
        device_payer_count = 0
        device_author_companies: frozenset[tuple[str, str]] = frozenset()
        recent_payer_count = 0
        destination_network_activity = {}
        partner_company_counts: dict[str, int] = {}
        event_device = (event.get("source") or {}).get("device_id")

        if not epp:
            destination_activity = self.aggregate_destination_account_activity(
                session,
                destination_key(event),
                payer,
                event_date - timedelta(minutes=60),
                event_date,
            )
            device_payer_count = self.count_recent_device_payers(
                session, event_device, payer,
                event_date - timedelta(hours=24), event_date,
            )
        else:
            device_author_companies = frozenset(self.get_recent_device_author_companies(
                session, event_device,
                event_date - timedelta(hours=24), event_date,
            ))

        if epp.get("event") == "request":
            recent_payer_count = self.count_recent_payers(
                session, event_date - timedelta(hours=24), event_date,
            )
            destination_network_activity = self.aggregate_destination_document_activity(
                session, destination_doc, epp.get("company_id"),
                event_date - timedelta(hours=24), event_date,
            )
            partner_docs = {str(value) for value in epp.get("partner_documents", [])}
            partner_company_counts = self.get_recent_partner_company_counts(
                session, partner_docs, epp.get("company_id"),
                event_date - timedelta(days=30), event_date,
            )

        request_event = None
        request_status = None
        has_prior_execution = False
        if epp.get("event") in ("vote", "execution") and epp.get("request_id"):
            request_row = self.get_transaction_by_id(session, str(epp["request_id"]))
            if request_row is not None:
                request_event = self._as_history_event(request_row)
                request_decision = self.get_decision_by_transaction_id(session, request_row.id)
                request_status = request_decision.status if request_decision else None
            if epp.get("event") == "execution":
                has_prior_execution = self.has_non_rejected_execution(
                    session,
                    str(epp["request_id"]),
                    event_date,
                    parse_datetime(request_row.transaction_date) if request_row is not None else None,
                )

        return PixHistory(
            source_events=source_events,
            trusted_events=trusted_events,
            source_event_count=int(snapshot["source_event_count"]),
            trusted_event_count=int(snapshot["trusted_event_count"]),
            successful_profile_count=int(snapshot["successful_profile_count"]),
            profile_median=float(snapshot["profile_median"]) if snapshot["profile_median"] is not None else None,
            source_metrics=source_metrics,
            seen_destination_account=bool(snapshot["seen_destination_account"]),
            destination_account_activity=destination_activity,
            device_payer_count=device_payer_count,
            device_author_companies=device_author_companies,
            recent_payer_count=recent_payer_count,
            destination_document_activity=destination_network_activity,
            partner_company_counts=partner_company_counts,
            request_event=request_event,
            request_status=request_status,
            has_prior_execution=has_prior_execution,
        )

    def aggregate_destination_account_activity(
        self,
        session: Session,
        destination_key: tuple[str, str, str],
        source_document: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        row = session.execute(text("""
            SELECT COUNT(DISTINCT source_document) AS sender_count,
                   COALESCE(SUM(amount), 0) AS amount_total,
                   COALESCE(BOOL_OR(source_document = :source_document), FALSE) AS current_sender_present
            FROM pix_transactions
            WHERE transaction_date BETWEEN :start_date AND :end_date
              AND payload #>> '{destination_account,participant}' = :participant
              AND payload #>> '{destination_account,branch}' = :branch
              AND payload #>> '{destination_account,account_number}' = :account_number
              AND (payload #>> '{context,event}' IS NULL OR payload #>> '{context,event}' = 'request')
        """), {
            "start_date": start_date,
            "end_date": end_date,
            "participant": destination_key[0],
            "branch": destination_key[1],
            "account_number": destination_key[2],
            "source_document": source_document,
        }).mappings().one()
        return dict(row)

    def count_recent_device_payers(self, session: Session, device_id: str | None, source_document: str, start_date: datetime, end_date: datetime) -> int:
        return session.execute(text("""
            SELECT COUNT(DISTINCT source_document)
                   + CASE WHEN COALESCE(BOOL_OR(source_document = :source_document), FALSE) THEN 0 ELSE 1 END
            FROM pix_transactions
            WHERE transaction_date BETWEEN :start_date AND :end_date
              AND payload #>> '{source,device_id}' IS NOT DISTINCT FROM :device_id
              AND (payload #>> '{context,event}' IS NULL OR payload #>> '{context,event}' = 'request')
        """), {"start_date": start_date, "end_date": end_date, "device_id": device_id, "source_document": source_document}).scalar_one()

    def get_recent_device_author_companies(self, session: Session, device_id: str | None, start_date: datetime, end_date: datetime) -> set[tuple[str, str]]:
        rows = session.execute(text("""
            SELECT DISTINCT payload #>> '{context,author_id}' AS author_id,
                            payload #>> '{context,company_id}' AS company_id
            FROM pix_transactions
            WHERE transaction_date BETWEEN :start_date AND :end_date
              AND payload #>> '{source,device_id}' IS NOT DISTINCT FROM :device_id
              AND payload #>> '{context,event}' = 'request'
              AND NULLIF(payload #>> '{context,author_id}', '') IS NOT NULL
              AND NULLIF(payload #>> '{context,company_id}', '') IS NOT NULL
        """), {"start_date": start_date, "end_date": end_date, "device_id": device_id}).all()
        return {(row.author_id, row.company_id) for row in rows}

    def count_recent_payers(self, session: Session, start_date: datetime, end_date: datetime) -> int:
        return session.execute(text("""
            SELECT COUNT(DISTINCT source_document)
            FROM pix_transactions
            WHERE transaction_date BETWEEN :start_date AND :end_date
              AND (payload #>> '{context,event}' IS NULL OR payload #>> '{context,event}' = 'request')
        """), {"start_date": start_date, "end_date": end_date}).scalar_one()

    def aggregate_destination_document_activity(
        self, session: Session, destination_document: str, company_id: str | None, start_date: datetime, end_date: datetime
    ) -> dict:
        row = session.execute(text("""
            SELECT COUNT(DISTINCT NULLIF(payload #>> '{context,company_id}', '')) AS company_count,
                   COALESCE(SUM(amount), 0) AS amount_total,
                   COALESCE(BOOL_OR(payload #>> '{context,company_id}' = :company_id), FALSE) AS current_company_present
            FROM pix_transactions
            WHERE transaction_date BETWEEN :start_date AND :end_date
              AND destination_document = :destination_document
              AND payload #>> '{context,event}' = 'request'
        """), {
            "start_date": start_date,
            "end_date": end_date,
            "destination_document": destination_document,
            "company_id": company_id,
        }).mappings().one()
        return dict(row)

    def get_recent_partner_company_counts(
        self, session: Session, partner_documents: set[str], company_id: str | None, start_date: datetime, end_date: datetime
    ) -> dict[str, int]:
        if not partner_documents:
            return {}
        rows = session.execute(text("""
            WITH requested_partners AS (
                SELECT unnest(CAST(:partner_documents AS text[])) AS partner_document
            )
            SELECT rp.partner_document,
                   COUNT(DISTINCT tp.company_id)
                       + CASE WHEN :company_id IS NULL
                                   OR COALESCE(BOOL_OR(tp.company_id = :company_id), FALSE)
                              THEN 0 ELSE 1 END AS company_count
            FROM requested_partners AS rp
            LEFT JOIN LATERAL (
                SELECT t.payload #>> '{context,company_id}' AS company_id
                FROM pix_transactions AS t
                WHERE t.transaction_date BETWEEN :start_date AND :end_date
                  AND t.payload #>> '{context,event}' = 'request'
                  AND NULLIF(t.payload #>> '{context,company_id}', '') IS NOT NULL
                  AND t.payload #> '{context,partner_documents}' @> jsonb_build_array(rp.partner_document)
            ) AS tp ON TRUE
            GROUP BY rp.partner_document
        """), {
            "partner_documents": sorted(partner_documents),
            "start_date": start_date,
            "end_date": end_date,
            "company_id": company_id,
        }).all()
        return {row.partner_document: row.company_count for row in rows}

    def has_non_rejected_execution(
        self, session: Session, request_id: str, event_date: datetime,
        request_date: datetime | None = None,
    ) -> bool:
        start_date = request_date or (event_date - timedelta(days=180))
        return bool(session.execute(text("""
            SELECT EXISTS (
                SELECT 1
                FROM pix_transactions AS t
                JOIN fraud_analysis AS d ON d.transaction_id = t.id
                WHERE t.transaction_date BETWEEN :start_date AND :event_date
                  AND t.payload #>> '{context,event}' = 'execution'
                  AND t.payload #>> '{context,request_id}' = :request_id
                  AND d.status != 'rejected'
            )
        """), {
            "start_date": start_date,
            "event_date": event_date,
            "request_id": request_id,
        }).scalar_one())

    def get_decision_by_transaction_id(self, session: Session, transaction_id: str):
        return session.query(PixDecisionModel).filter(PixDecisionModel.transaction_id == transaction_id).first()

    def lock_keys(self, session: Session, pix_id: str, payer: str, dest: str):
        """
        Adquire os locks na ordem estável da RFC: evento, pagador, conta destino.
        """
        # Namespaces prevent an id, payer and destination with equal text from sharing a lock.
        for kind, value in (("id", pix_id), ("payer", payer), ("dest", dest)):
            material = f"{kind}\0{value}".encode()
            lock_id = int.from_bytes(hashlib.md5(material).digest()[:8], "big", signed=True)
            try:
                session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
            except OperationalError as error:
                sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
                if sqlstate == "55P03" or "lock timeout" in str(error).lower():
                    raise ServiceUnavailableError(
                        "The event lock timed out. Retry this request with the same event id."
                    ) from error
                raise

    def save_analysis(
        self,
        session: Session,
        unit_of_work,
        transaction_data: dict,
        status: str,
        risk_score: int,
        metadata: dict,
        rule_hits: list,
        payload_hash: str,
    ):
        """Salva a transação, a decisão e as regras acionadas numa única transação de banco."""
        try:
            session.execute(text("""
                INSERT INTO fraud_rules (code, name, default_points)
                VALUES
                    ('R33', 'Degrau de início frio', 1),
                    ('C1', 'Integridade do pedido, voto e execução', 0)
                ON CONFLICT (code) DO NOTHING
            """))

            tx_model = PixTransactionModel(
                id=transaction_data["id"],
                amount=transaction_data["amount"],
                transaction_date=parse_datetime(transaction_data["transaction_date"]),
                source_document=transaction_data["source_account"]["owner"]["document_number"],
                destination_document=transaction_data["destination_account"]["owner"]["document_number"],
                payload=transaction_data,
            )
            session.add(tx_model)
            session.flush()

            decision_model = PixDecisionModel(
                transaction_id=transaction_data["id"],
                status=status,
                risk_score=risk_score,
                metadata_=metadata,
            )
            session.add(decision_model)
            session.flush()

            for hit in rule_hits:
                session.execute(
                    text("""
                        INSERT INTO rule_hits (analysis_key, rule_code, points, detail)
                        VALUES (:key, :code, :points, :detail)
                    """),
                    {
                        "key": decision_model.key,
                        "code": hit["code"],
                        "points": hit["points"],
                        "detail": hit["detail"],
                    },
                )

            unit_of_work.commit()
            return decision_model, True
        except IntegrityError:
            unit_of_work.rollback()
            existing = self.get_transaction_by_id(session, transaction_data["id"])
            if existing is None:
                raise
            stored_hash = self.compute_payload_hash(dict(existing.payload or {}))
            if stored_hash != payload_hash:
                raise ConflictError("Event id was already used with a different payload")
            decision = self.get_decision_by_transaction_id(session, transaction_data["id"])
            if decision is None:
                raise NotFoundError("A decisão deste evento ainda não está disponível.")
            return decision, False
