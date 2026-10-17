-- ============================================================================
--  Conta compartilhada para EPP — schema do banco (RFC v6)
--
--  16 tabelas, na ordem das dependências. Convenções:
--    * dinheiro é sempre inteiro em centavos (bigint) — nunca decimal/float;
--    * PK uuid gerado pelo banco (gen_random_uuid), exceto STATUS e TARIFA;
--    * as UNIQUE e os CHECK são a ÚLTIMA barreira da RFC: o controller
--      confere antes, mas quem garante é o banco (concorrência, retentativa,
--      bug). Por isso todas as restrições têm nome — a API traduz o nome da
--      restrição violada no erro HTTP certo.
--
--  ATENÇÃO: este arquivo roda via psycopg2 sem parâmetros (tests/utils/
--  db_utils.py). Não escreva o caractere de porcentagem aqui dentro.
-- ============================================================================


-- ----------------------------------------------------------------------------
--  Funções de apoio
-- ----------------------------------------------------------------------------

-- Tabelas de "fato" e de histórico só recebem INSERT. Alterar ou apagar uma
-- linha delas é bug, e o banco recusa em vez de confiar no código.
CREATE FUNCTION proibir_alteracao() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'A tabela ' || TG_TABLE_NAME || ' e imutavel: ' || TG_OP || ' nao permitido',
        ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;


-- ----------------------------------------------------------------------------
--  1. Pessoas, empresas e sócios
-- ----------------------------------------------------------------------------

CREATE TABLE pessoa (
    pessoa_id        uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    cpf              varchar(11)  NOT NULL,
    nome             varchar(120) NOT NULL,
    email            varchar(120) NOT NULL,
    data_nascimento  date         NOT NULL,
    CONSTRAINT uq_pessoa_cpf   UNIQUE (cpf),
    CONSTRAINT uq_pessoa_email UNIQUE (email)
);

CREATE TABLE empresa (
    empresa_id    uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    cnpj          varchar(14)  NOT NULL,
    razao_social  varchar(150) NOT NULL,
    CONSTRAINT uq_empresa_cnpj UNIQUE (cnpj)
);

-- A razão social é única comparada SEM maiúsculas e SEM espaços sobrando.
CREATE UNIQUE INDEX uq_empresa_razao_social
    ON empresa (lower(regexp_replace(btrim(razao_social), '\s+', ' ', 'g')));

CREATE TABLE empresa_socio (
    empresa_socio_id  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id        uuid        NOT NULL REFERENCES empresa (empresa_id),
    pessoa_id         uuid        NOT NULL REFERENCES pessoa (pessoa_id),
    papel             varchar(20) NOT NULL,
    participacao_bp   int         NOT NULL,
    CONSTRAINT uq_empresa_socio_pessoa UNIQUE (empresa_id, pessoa_id),
    CONSTRAINT ck_empresa_socio_papel  CHECK (papel IN ('SOCIO', 'SOCIO_ADMINISTRADOR')),
    CONSTRAINT ck_empresa_socio_bp     CHECK (participacao_bp BETWEEN 1 AND 10000)
);

CREATE INDEX ix_empresa_socio_pessoa ON empresa_socio (pessoa_id);

CREATE TABLE permissao_socio (
    permissao_id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_socio_id           uuid        NOT NULL REFERENCES empresa_socio (empresa_socio_id),
    acao                       varchar(30) NOT NULL,
    escopo                     varchar(10) NOT NULL,
    limite_transacao_centavos  bigint,
    CONSTRAINT uq_permissao_socio_acao UNIQUE (empresa_socio_id, acao),
    CONSTRAINT ck_permissao_acao   CHECK (acao IN (
        'CONSULTAR', 'EXECUTAR_PAGAMENTO', 'APROVAR',
        'GERIR_RESPONSABILIDADE', 'LIBERAR_RESERVA', 'GERIR_GOVERNANCA')),
    CONSTRAINT ck_permissao_escopo CHECK (escopo IN ('PROPRIAS', 'TODAS')),
    CONSTRAINT ck_permissao_limite CHECK (limite_transacao_centavos IS NULL OR limite_transacao_centavos > 0)
);

-- Acima de X, N aprovações (ou todos). A regra com meio vence a sem meio.
CREATE TABLE regra_aprovacao (
    regra_id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id              uuid        NOT NULL REFERENCES empresa (empresa_id),
    acao                    varchar(30) NOT NULL,
    meio                    varchar(20),
    acima_de_centavos       bigint      NOT NULL,
    exige_todos             boolean     NOT NULL DEFAULT false,
    aprovacoes_necessarias  int,
    CONSTRAINT uq_regra_aprovacao UNIQUE NULLS NOT DISTINCT (empresa_id, acao, meio, acima_de_centavos),
    CONSTRAINT ck_regra_acao  CHECK (acao IN ('PAGAMENTO', 'RESERVA', 'LIBERACAO_RESERVA')),
    CONSTRAINT ck_regra_meio  CHECK (meio IS NULL OR meio IN ('PIX', 'TED', 'BOLETO', 'INTERNO')),
    CONSTRAINT ck_regra_acima CHECK (acima_de_centavos >= 0),
    -- exatamente um entre "todos" e "N aprovações"
    CONSTRAINT ck_regra_quorum CHECK (
        (exige_todos AND aprovacoes_necessarias IS NULL)
        OR (NOT exige_todos AND aprovacoes_necessarias >= 1))
);


-- ----------------------------------------------------------------------------
--  2. Conta, status e tarifa
-- ----------------------------------------------------------------------------

CREATE TABLE status (
    status_id  int         PRIMARY KEY,
    codigo     varchar(20) NOT NULL,
    descricao  varchar(60) NOT NULL,
    CONSTRAINT uq_status_codigo UNIQUE (codigo)
);

INSERT INTO status (status_id, codigo, descricao) VALUES
    (1, 'EM_APROVACAO', 'Conta cadastrada, aguardando aprovacao do back-office'),
    (2, 'ATIVA',        'Conta ativa: movimenta dinheiro'),
    (3, 'BLOQUEADA',    'Conta bloqueada: nao movimenta dinheiro'),
    (4, 'ENCERRADA',    'Conta encerrada (estado final)');

-- Uma empresa, uma conta (a UNIQUE em empresa_id é a regra desta entrega).
CREATE SEQUENCE conta_numero_seq START 1000;


CREATE TABLE conta (
    conta_id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id                   uuid        NOT NULL REFERENCES empresa (empresa_id),
    status_id                    int         NOT NULL REFERENCES status (status_id),
    agencia                      varchar(4)  NOT NULL,
    numero                       varchar(10) NOT NULL,
    saldo_total_centavos         bigint      NOT NULL DEFAULT 0,
    saldo_reservado_centavos     bigint      NOT NULL DEFAULT 0,
    saldo_comprometido_centavos  bigint      NOT NULL DEFAULT 0,
    CONSTRAINT uq_conta_empresa        UNIQUE (empresa_id),
    CONSTRAINT uq_conta_agencia_numero UNIQUE (agencia, numero),
    -- Os baldes nunca se sobrepõem: total >= reservado + comprometido.
    CONSTRAINT ck_conta_reservado     CHECK (saldo_reservado_centavos >= 0),
    CONSTRAINT ck_conta_comprometido  CHECK (saldo_comprometido_centavos >= 0),
    CONSTRAINT ck_conta_baldes        CHECK (saldo_total_centavos >= saldo_reservado_centavos + saldo_comprometido_centavos)
);

CREATE TABLE conta_status_evento (
    evento_id  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    conta_id   uuid         NOT NULL REFERENCES conta (conta_id),
    status_id  int          NOT NULL REFERENCES status (status_id),
    motivo     varchar(140),
    criado_em  timestamptz  NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ix_conta_status_evento_conta ON conta_status_evento (conta_id, criado_em);

CREATE TRIGGER tg_conta_status_evento_imutavel
    BEFORE UPDATE OR DELETE ON conta_status_evento
    FOR EACH ROW EXECUTE FUNCTION proibir_alteracao();

-- Tarifa versionada e imutável: mudar o preço cria uma linha nova.
CREATE TABLE tarifa (
    tarifa_id      int          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    meio           varchar(20)  NOT NULL,
    valor_centavos bigint       NOT NULL,
    vigente_desde  timestamptz  NOT NULL,
    CONSTRAINT ck_tarifa_meio  CHECK (meio IN ('PIX', 'TED', 'BOLETO')),
    CONSTRAINT ck_tarifa_valor CHECK (valor_centavos >= 0)
);

CREATE INDEX ix_tarifa_vigencia ON tarifa (meio, vigente_desde DESC);

CREATE TRIGGER tg_tarifa_imutavel
    BEFORE UPDATE OR DELETE ON tarifa
    FOR EACH ROW EXECUTE FUNCTION proibir_alteracao();

INSERT INTO tarifa (meio, valor_centavos, vigente_desde) VALUES
    ('PIX',      0, '2000-01-01T00:00:00Z'),
    ('TED',    900, '2000-01-01T00:00:00Z'),
    ('BOLETO', 350, '2000-01-01T00:00:00Z');


-- ----------------------------------------------------------------------------
--  3. Como o dinheiro da empresa é organizado (responsabilidade e orçamento)
-- ----------------------------------------------------------------------------

-- Responsabilidade NÃO é subconta: é só uma divisão lógica do saldo.
-- Os saldos daqui somam os da CONTA (reservado) — há teste automatizado.
CREATE TABLE responsabilidade (
    responsabilidade_id           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    conta_id                      uuid         NOT NULL REFERENCES conta (conta_id),
    nome                          varchar(80)  NOT NULL,
    responsavel_empresa_socio_id  uuid         NOT NULL REFERENCES empresa_socio (empresa_socio_id),
    substituto_empresa_socio_id   uuid         REFERENCES empresa_socio (empresa_socio_id),
    substituicao_inicio           timestamptz,
    substituicao_fim              timestamptz,
    saldo_reservado_centavos      bigint       NOT NULL DEFAULT 0,
    saldo_comprometido_centavos   bigint       NOT NULL DEFAULT 0,
    CONSTRAINT uq_responsabilidade_conta_nome UNIQUE (conta_id, nome),
    CONSTRAINT ck_responsabilidade_reservado    CHECK (saldo_reservado_centavos >= 0),
    CONSTRAINT ck_responsabilidade_comprometido CHECK (saldo_comprometido_centavos >= 0),
    -- substituto e janela andam juntos; fim depois do início
    CONSTRAINT ck_responsabilidade_substituicao CHECK (
        (substituto_empresa_socio_id IS NULL AND substituicao_inicio IS NULL AND substituicao_fim IS NULL)
        OR (substituto_empresa_socio_id IS NOT NULL AND substituicao_inicio IS NOT NULL
            AND substituicao_fim IS NOT NULL AND substituicao_fim > substituicao_inicio))
);

CREATE TABLE orcamento (
    orcamento_id         uuid     PRIMARY KEY DEFAULT gen_random_uuid(),
    responsabilidade_id  uuid     NOT NULL REFERENCES responsabilidade (responsabilidade_id),
    competencia          char(7)  NOT NULL,
    valor_centavos       bigint   NOT NULL,
    utilizado_centavos   bigint   NOT NULL DEFAULT 0,
    CONSTRAINT uq_orcamento_competencia UNIQUE (responsabilidade_id, competencia),
    CONSTRAINT ck_orcamento_competencia CHECK (competencia ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    CONSTRAINT ck_orcamento_valor       CHECK (valor_centavos > 0),
    CONSTRAINT ck_orcamento_utilizado   CHECK (utilizado_centavos >= 0 AND utilizado_centavos <= valor_centavos)
);


-- ----------------------------------------------------------------------------
--  4. Intenção (pagamento programado, movimento de reserva) e fato (transação)
-- ----------------------------------------------------------------------------

-- Intenção futura de pagar: compromete o dinheiro, mas nada saiu.
CREATE TABLE pagamento_programado (
    pagamento_programado_id  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    conta_id                 uuid         NOT NULL REFERENCES conta (conta_id),
    responsabilidade_id      uuid         REFERENCES responsabilidade (responsabilidade_id),
    autor_empresa_socio_id   uuid         NOT NULL REFERENCES empresa_socio (empresa_socio_id),
    meio                     varchar(20)  NOT NULL,
    contraparte              jsonb        NOT NULL,
    referencia_externa       varchar(80),
    valor_centavos           bigint       NOT NULL,
    tarifa_id                int          NOT NULL REFERENCES tarifa (tarifa_id),
    data_prevista            date         NOT NULL,
    status                   varchar(25)  NOT NULL,
    aprovacoes_exigidas      int          NOT NULL DEFAULT 0,
    chave_idempotencia       varchar(80)  NOT NULL,
    hash_requisicao          char(64)     NOT NULL,
    categoria                varchar(40),
    descricao                varchar(140),
    motivo                   varchar(140),
    criado_em                timestamptz  NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_pp_autor_chave UNIQUE (autor_empresa_socio_id, chave_idempotencia),
    CONSTRAINT ck_pp_meio    CHECK (meio IN ('PIX', 'TED', 'BOLETO')),
    CONSTRAINT ck_pp_valor   CHECK (valor_centavos > 0),
    CONSTRAINT ck_pp_status  CHECK (status IN (
        'AGUARDANDO_APROVACAO', 'AGENDADO', 'EXECUTADO', 'RECUSADO', 'CANCELADO', 'FALHOU')),
    CONSTRAINT ck_pp_aprovacoes CHECK (aprovacoes_exigidas >= 0)
);

-- O mesmo boleto não entra em dois pedidos ativos (a UK é parcial).
CREATE UNIQUE INDEX uq_pp_boleto_ativo
    ON pagamento_programado (meio, referencia_externa)
    WHERE referencia_externa IS NOT NULL AND status IN ('AGUARDANDO_APROVACAO', 'AGENDADO');

CREATE INDEX ix_pp_conta ON pagamento_programado (conta_id, criado_em DESC, pagamento_programado_id DESC);

-- Histórico de cada mexida na reserva (reservar, liberar, transferir).
CREATE TABLE movimento_reserva (
    movimento_id                  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    conta_id                      uuid         NOT NULL REFERENCES conta (conta_id),
    tipo                          varchar(15)  NOT NULL,
    responsabilidade_origem_id    uuid         REFERENCES responsabilidade (responsabilidade_id),
    responsabilidade_destino_id   uuid         REFERENCES responsabilidade (responsabilidade_id),
    valor_centavos                bigint       NOT NULL,
    autor_empresa_socio_id        uuid         NOT NULL REFERENCES empresa_socio (empresa_socio_id),
    status                        varchar(25)  NOT NULL,
    aprovacoes_exigidas           int          NOT NULL DEFAULT 0,
    chave_idempotencia            varchar(80)  NOT NULL,
    hash_requisicao               char(64)     NOT NULL,
    motivo                        varchar(140),
    criado_em                     timestamptz  NOT NULL DEFAULT clock_timestamp(),
    decidido_em                   timestamptz,
    CONSTRAINT uq_movimento_autor_chave UNIQUE (autor_empresa_socio_id, chave_idempotencia),
    CONSTRAINT ck_movimento_valor  CHECK (valor_centavos > 0),
    CONSTRAINT ck_movimento_status CHECK (status IN ('AGUARDANDO_APROVACAO', 'APLICADO', 'RECUSADO')),
    CONSTRAINT ck_movimento_tipo   CHECK (
        (tipo = 'RESERVA'       AND responsabilidade_origem_id IS NULL     AND responsabilidade_destino_id IS NOT NULL)
        OR (tipo = 'LIBERACAO'  AND responsabilidade_origem_id IS NOT NULL AND responsabilidade_destino_id IS NULL)
        OR (tipo = 'TRANSFERENCIA' AND responsabilidade_origem_id IS NOT NULL AND responsabilidade_destino_id IS NOT NULL
            AND responsabilidade_origem_id <> responsabilidade_destino_id))
);

-- O fato financeiro. Depósito, saída, Pix, TED, boleto e transferência interna
-- são a MESMA tabela: o que varia é natureza (sentido) e meio (canal).
CREATE TABLE transacao (
    transacao_id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    natureza                    varchar(10)  NOT NULL,
    meio                        varchar(20)  NOT NULL,
    conta_origem_id             uuid         REFERENCES conta (conta_id),
    conta_destino_id            uuid         REFERENCES conta (conta_id),
    contraparte                 jsonb,
    referencia_externa          varchar(80),
    autor_empresa_socio_id      uuid         REFERENCES empresa_socio (empresa_socio_id),
    responsabilidade_id         uuid         REFERENCES responsabilidade (responsabilidade_id),
    pagamento_programado_id     uuid         REFERENCES pagamento_programado (pagamento_programado_id),
    chave_idempotencia          varchar(80),
    hash_requisicao             char(64),
    valor_centavos              bigint       NOT NULL,
    tarifa_id                   int          REFERENCES tarifa (tarifa_id),
    categoria                   varchar(40),
    descricao                   varchar(140),
    saldo_origem_apos_centavos  bigint,
    saldo_destino_apos_centavos bigint,
    criado_em                   timestamptz  NOT NULL DEFAULT clock_timestamp(),
    -- um pedido gera no máximo uma transação
    CONSTRAINT uq_transacao_pagamento_programado UNIQUE (pagamento_programado_id),
    -- o mesmo boleto / a mesma notificação do parceiro não vale duas vezes
    CONSTRAINT uq_transacao_meio_referencia UNIQUE (meio, referencia_externa),
    CONSTRAINT uq_transacao_autor_chave UNIQUE (autor_empresa_socio_id, chave_idempotencia),
    CONSTRAINT ck_transacao_valor    CHECK (valor_centavos > 0),
    CONSTRAINT ck_transacao_natureza CHECK (natureza IN ('ENTRADA', 'SAIDA', 'INTERNA')),
    CONSTRAINT ck_transacao_meio     CHECK (meio IN ('PIX', 'TED', 'BOLETO', 'INTERNO')),
    -- coerência natureza x pontas x meio x autor
    CONSTRAINT ck_transacao_coerente CHECK (
        (natureza = 'ENTRADA' AND conta_origem_id IS NULL AND conta_destino_id IS NOT NULL AND meio <> 'INTERNO')
        OR (natureza = 'SAIDA' AND conta_origem_id IS NOT NULL AND conta_destino_id IS NULL AND meio <> 'INTERNO')
        OR (natureza = 'INTERNA' AND conta_origem_id IS NOT NULL AND conta_destino_id IS NOT NULL
            AND conta_origem_id <> conta_destino_id AND contraparte IS NULL AND meio = 'INTERNO')),
    CONSTRAINT ck_transacao_autor CHECK (autor_empresa_socio_id IS NOT NULL OR natureza = 'ENTRADA'),
    -- o saldo "após" existe exatamente nas pontas que existem
    CONSTRAINT ck_transacao_saldo_origem  CHECK ((conta_origem_id IS NULL)  = (saldo_origem_apos_centavos IS NULL)),
    CONSTRAINT ck_transacao_saldo_destino CHECK ((conta_destino_id IS NULL) = (saldo_destino_apos_centavos IS NULL))
);

-- Índices de leitura do extrato paginado por cursor (criado_em, transacao_id).
CREATE INDEX ix_transacao_origem  ON transacao (conta_origem_id,  criado_em DESC, transacao_id DESC);
CREATE INDEX ix_transacao_destino ON transacao (conta_destino_id, criado_em DESC, transacao_id DESC);

CREATE TRIGGER tg_transacao_imutavel
    BEFORE UPDATE OR DELETE ON transacao
    FOR EACH ROW EXECUTE FUNCTION proibir_alteracao();


-- ----------------------------------------------------------------------------
--  5. Governança: votos e auditoria
-- ----------------------------------------------------------------------------

-- Um voto aponta para EXATAMENTE um alvo (pagamento programado OU movimento
-- de reserva). A UK impede o mesmo sócio de votar duas vezes no mesmo alvo.
CREATE TABLE aprovacao (
    aprovacao_id             uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_socio_id         uuid         NOT NULL REFERENCES empresa_socio (empresa_socio_id),
    pagamento_programado_id  uuid         REFERENCES pagamento_programado (pagamento_programado_id),
    movimento_reserva_id     uuid         REFERENCES movimento_reserva (movimento_id),
    decisao                  varchar(10)  NOT NULL,
    criado_em                timestamptz  NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_aprovacao_socio_pp        UNIQUE (empresa_socio_id, pagamento_programado_id),
    CONSTRAINT uq_aprovacao_socio_movimento UNIQUE (empresa_socio_id, movimento_reserva_id),
    CONSTRAINT ck_aprovacao_decisao CHECK (decisao IN ('APROVADA', 'RECUSADA')),
    CONSTRAINT ck_aprovacao_alvo    CHECK ((pagamento_programado_id IS NULL) <> (movimento_reserva_id IS NULL))
);

CREATE INDEX ix_aprovacao_pp ON aprovacao (pagamento_programado_id) WHERE pagamento_programado_id IS NOT NULL;
CREATE INDEX ix_aprovacao_movimento ON aprovacao (movimento_reserva_id) WHERE movimento_reserva_id IS NOT NULL;

-- Só recebe linhas: quem mudou permissão, regra, substituição ou responsabilidade.
CREATE TABLE evento_auditoria (
    evento_id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id              uuid         NOT NULL REFERENCES empresa (empresa_id),
    autor_empresa_socio_id  uuid         NOT NULL REFERENCES empresa_socio (empresa_socio_id),
    acao                    varchar(40)  NOT NULL,
    alvo_tipo               varchar(30)  NOT NULL,
    alvo_id                 uuid         NOT NULL,
    dados                   jsonb        NOT NULL DEFAULT '{}'::jsonb,
    criado_em               timestamptz  NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ix_evento_auditoria_empresa ON evento_auditoria (empresa_id, criado_em DESC);

CREATE TRIGGER tg_evento_auditoria_imutavel
    BEFORE UPDATE OR DELETE ON evento_auditoria
    FOR EACH ROW EXECUTE FUNCTION proibir_alteracao();
