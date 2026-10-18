-- Read-only payer history for SQL clients; this does not add an API endpoint.
CREATE INDEX IF NOT EXISTS ix_rule_hits_analysis_key
    ON rule_hits (analysis_key);

CREATE OR REPLACE VIEW v_historico_pagador AS
SELECT
    t.source_document,
    t.id,
    t.transaction_date,
    t.created_at,
    t.amount,
    t.destination_document,
    a.status,
    a.risk_score,
    (a.status = 'approved') AS dinheiro_liberado,
    COALESCE(
        (
            SELECT array_agg(h.rule_code ORDER BY h.rule_code)
            FROM rule_hits AS h
            WHERE h.analysis_key = a.key
        ),
        ARRAY[]::varchar[]
    ) AS regras
FROM pix_transactions AS t
JOIN fraud_analysis AS a ON a.transaction_id = t.id;
