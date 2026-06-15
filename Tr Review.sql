-- =====================================================================
-- Migração: Esteira de Revisão de TRs (Kanban)
-- Cria a tabela dos TRs GERADOS pela IA que entram no fluxo de revisão.
--
-- Importante: é uma tabela NOVA, separada de `termo`. A tabela `termo`
-- existente guarda os DOCUMENTOS-BASE que o admin cadastra (conforme o
-- comentário no schema original); aqui guardamos o que a IA GERA e que
-- precisa ser aprovado/reprovado.
--
-- Pré-requisitos: rode depois de "Maestro DB Generation.sql" (tabela
-- usuario) e de "chat_persistence.sql" (tabela conversa).
--
--   psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f tr_review.sql
-- =====================================================================

CREATE TABLE IF NOT EXISTS trGerado (
    trId              SERIAL,
    titulo            TEXT        NOT NULL,
    categoria         TEXT        DEFAULT 'Não classificado',
    criadoEm          TIMESTAMPTZ DEFAULT NOW(),
    geradoPor         VARCHAR(10) NOT NULL DEFAULT 'ai',   -- 'ai' | 'human'
    status            VARCHAR(10) NOT NULL DEFAULT 'pending',
    versao            INTEGER     NOT NULL DEFAULT 1,

    -- Conteúdo
    preview           TEXT,            -- resumo curto para o card do Kanban
    conteudo          JSONB,           -- documento estruturado (sections, html, etc.)
    fullContent       TEXT,            -- versão em texto/markdown (o front consome isto)

    -- Transparência / Ground Truth
    analiseResumo     TEXT,            -- analysisSummary (como a IA montou o TR)
    fontes            JSONB DEFAULT '[]'::jsonb,  -- sourceDocuments [{id,name,type,size}]

    -- Auditoria de revisão
    criadoPorId       INTEGER,         -- autor (usuario)
    revisadoPor       TEXT,            -- nome de quem revisou (desnormalizado p/ o front)
    revisadoPorId     INTEGER,         -- id de quem revisou
    revisadoEm        TIMESTAMPTZ,
    motivoReprovacao  TEXT,            -- obrigatório quando status = 'rejected'

    -- Vínculo opcional com o chat que originou o TR
    conversaId        INTEGER,

    CONSTRAINT pk_tr_gerado PRIMARY KEY (trId),
    CONSTRAINT ck_tr_status CHECK (status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT ck_tr_geradopor CHECK (geradoPor IN ('ai', 'human')),
    CONSTRAINT fk_tr_autor   FOREIGN KEY (criadoPorId)   REFERENCES usuario(userId),
    CONSTRAINT fk_tr_revisor FOREIGN KEY (revisadoPorId) REFERENCES usuario(userId),
    CONSTRAINT fk_tr_conversa FOREIGN KEY (conversaId)   REFERENCES conversa(conversaId) ON DELETE SET NULL
);

-- Listagem do Kanban: por status e mais recentes primeiro.
CREATE INDEX IF NOT EXISTS idx_tr_status ON trGerado(status, criadoEm DESC);
-- Listagem geral por data.
CREATE INDEX IF NOT EXISTS idx_tr_criadoem ON trGerado(criadoEm DESC);
-- Busca textual simples por título (ILIKE).
CREATE INDEX IF NOT EXISTS idx_tr_titulo ON trGerado(titulo);
