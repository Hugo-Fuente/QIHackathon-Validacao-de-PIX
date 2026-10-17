-- Tabela para registar o histórico de Pix recebidos
CREATE TABLE pix_transactions (
    id VARCHAR(50) PRIMARY KEY,
    amount BIGINT NOT NULL,
    transaction_date TIMESTAMPTZ NOT NULL,
    source_document VARCHAR(20) NOT NULL,
    destination_document VARCHAR(20) NOT NULL,
    payload JSONB NOT NULL, -- Guardamos o JSON completo para auditoria ou regras complexas
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Tabela para registar a decisão do motor antifraude
CREATE TABLE pix_decisions (
    key UUID PRIMARY KEY,
    transaction_id VARCHAR(50) REFERENCES pix_transactions(id) UNIQUE NOT NULL,
    status VARCHAR(30) NOT NULL, -- 'approved', 'rejected', 'two_factor_required'
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);