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
('R14', 'Cerca Virtual (Geofence)', 5);

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

-- 4. Histórico da Decisão do Motor
CREATE TABLE pix_decisions (
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
    analysis_key UUID REFERENCES pix_decisions(key),
    rule_code VARCHAR(10) REFERENCES fraud_rules(code),
    points SMALLINT NOT NULL,
    detail TEXT -- Ex: "A Padaria só abre às 06:00, mas o Pix ocorreu às 03:00"
);