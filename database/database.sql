-- 1. Catálogo das Regras Antifraude (Para podermos mudar os pontos sem mexer no código)
CREATE TABLE fraud_rules (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    default_points SMALLINT NOT NULL,
    is_active BOOLEAN DEFAULT true
);

-- Preenchendo as 14 regras que definimos
INSERT INTO fraud_rules (code, name, default_points) VALUES
('R1', 'Limite Absoluto Alto', 2),
('R2', 'Velocity / Rajada', 2),
('R3', 'Montante Acumulado Rápido', 2),
('R4', 'Desvio de Perfil', 2),
('R5', 'Contraparte Inédita', 1),
('R6', 'Destino Recém-Aberto', 2),
('R7', 'Dispositivo Novo', 2),
('R8', 'Fracionamento Suspeito', 2),
('R9', 'Destino Concentrador', 3),
('R10', 'Pagador Recente', 1),
('R11', 'Deslocamento Impossível', 3),
('R12', 'Dispositivo Compartilhado', 2),
('R13', 'Horário Fora do Padrão (Time-fence)', 3),
('R14', 'Cerca Virtual (Geofence)', 5),
('R15', 'Aprovação disfarçada', 3),
('R16', 'Afrouxamento de controle', 3),
('R17', 'Dispositivo novo do sócio', 2),
('R18', 'Deslocamento do sócio', 3),
('R19', 'Horário atípico do sócio', 1),
('R20', 'Esvaziamento de saldo livre', 2),
('R21', 'Libertação de reserva seguida de saída', 3),
('R22', 'Regra R22 (a definir)', 1),
('R23', 'Regra R23 (a definir)', 1),
('R24', 'Regra R24 (a definir)', 1),
('R25', 'Regra R25 (a definir)', 1),
('R26', 'Regra R26 (a definir)', 1),
('R27', 'Regra R27 (a definir)', 1),
('R28', 'Valor colado no piso', 2),
('R29', 'Fracionamento por documento', 2),
('R30', 'Regra R30 (a definir)', 1),
('R31', 'Regra R31 (a definir)', 1),
('R32', 'Regra R32 (a definir)', 1),
('R33', 'Degrau de início frio', 1),
('C1', 'Integridade do pedido, voto e execução', 0),
('R_VELOCITY', 'Velocity por remetente', 3),
('R_CRITICAL', 'Bloqueio por rajada crítica', 5);

-- 2. Políticas Customizadas por Cliente (Ex: Padaria)
CREATE TABLE client_fraud_policies (
    document_number VARCHAR(20) PRIMARY KEY, -- CPF ou CNPJ do recebedor
    check_business_hours BOOLEAN DEFAULT false,
    business_hour_start TIME,     
    business_hour_end TIME,       
    check_geolocation BOOLEAN DEFAULT false,
    anchor_latitude FLOAT,        
    anchor_longitude FLOAT,       
    max_radius_km FLOAT           
);

-- 3. Histórico de Transações Pix
CREATE TABLE pix_transactions (
    id VARCHAR(50) PRIMARY KEY,
    amount BIGINT NOT NULL,
    transaction_date TIMESTAMPTZ NOT NULL,
    source_document VARCHAR(20) NOT NULL,
    destination_document VARCHAR(20) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_pix_transactions_source_date
    ON pix_transactions (source_document, transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_destination_date
    ON pix_transactions (destination_document, transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_date_source
    ON pix_transactions (transaction_date, source_document);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_device_date
    ON pix_transactions ((payload #>> '{source,device_id}'), transaction_date);
CREATE INDEX IF NOT EXISTS ix_pix_transactions_destination_account_date
    ON pix_transactions (
        (payload #>> '{destination_account,participant}'),
        (payload #>> '{destination_account,branch}'),
        (payload #>> '{destination_account,account_number}'),
        transaction_date
    );
CREATE INDEX IF NOT EXISTS ix_pix_transactions_request_date
    ON pix_transactions ((payload #>> '{context,request_id}'), transaction_date)
    WHERE payload #>> '{context,event}' = 'execution';
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

-- 4. Histórico da Decisão do Motor
CREATE TABLE fraud_analysis (
    key UUID PRIMARY KEY,
    transaction_id VARCHAR(50) REFERENCES pix_transactions(id) UNIQUE NOT NULL,
    status VARCHAR(30) NOT NULL, -- 'approved', 'rejected', 'two_factor_required'
    risk_score SMALLINT NOT NULL, -- A soma total dos pontos
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. Regras Acionadas por Decisão (Para auditoria: "Quais regras bloquearam este Pix?")
CREATE TABLE rule_hits (
    id BIGSERIAL PRIMARY KEY,
    analysis_key UUID REFERENCES fraud_analysis(key),
    rule_code VARCHAR(10) REFERENCES fraud_rules(code),
    points SMALLINT NOT NULL,
    detail TEXT -- Ex: "A Padaria só abre às 06:00, mas o Pix ocorreu às 03:00"
);

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
