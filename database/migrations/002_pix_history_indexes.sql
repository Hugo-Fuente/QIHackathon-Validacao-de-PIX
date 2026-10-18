-- Query support for bounded payer, company, author and counterparty history.
CREATE INDEX IF NOT EXISTS ix_pix_transactions_company_date
    ON pix_transactions ((payload #>> '{context,company_id}'), transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_author_date
    ON pix_transactions ((payload #>> '{context,author_id}'), transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_source_destination_date
    ON pix_transactions (source_document, destination_document, transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_source_destination_account_date
    ON pix_transactions (
        source_document,
        (payload #>> '{destination_account,participant}'),
        (payload #>> '{destination_account,branch}'),
        (payload #>> '{destination_account,account_number}'),
        transaction_date
    );
CREATE INDEX IF NOT EXISTS ix_pix_transactions_responsibility_date
    ON pix_transactions ((payload #>> '{context,responsibility_id}'), transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_outflow_date_source
    ON pix_transactions (transaction_date, source_document)
    WHERE (payload #>> '{context,event}' IS NULL
           OR payload #>> '{context,event}' = 'request');
CREATE INDEX IF NOT EXISTS ix_pix_transactions_partner_documents_gin
    ON pix_transactions USING GIN ((payload #> '{context,partner_documents}') jsonb_path_ops)
    WHERE payload #>> '{context,event}' = 'request';
