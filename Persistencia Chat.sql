-- Persistencia Chat.sql
-- Tabelas que dão PERSISTÊNCIA ao chat conversacional.
-- Antes, o estado vivia só em memória (sumia ao reiniciar o servidor).
-- Agora cada conversa pertence a um usuário e fica salva, com seu histórico
-- de mensagens e o TR atualmente ativo — para que o usuário possa reabrir o
-- chat depois e continuar editando o TR.


    conversaId      SERIAL,
    userId          INTEGER NOT NULL,
    titulo          TEXT NOT NULL DEFAULT 'Nova conversa',
    documentoAtual  JSONB,                       -- o TR ativo (título, seções, html, fontes...)
    criadoEm        TIMESTAMPTZ DEFAULT NOW(),
    atualizadoEm    TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT pk_conversa PRIMARY KEY (conversaId),
    CONSTRAINT fk_conversa_user FOREIGN KEY (userId) REFERENCES usuario(userId)
);
-- A tela "Listar Chats" busca as conversas do usuário logado, mais recentes primeiro.
CREATE INDEX IF NOT EXISTS idx_conversa_user ON conversa(userId, atualizadoEm DESC);



CREATE TABLE IF NOT EXISTS mensagem (
    mensagemId  SERIAL,
    conversaId  INTEGER NOT NULL,
    role        VARCHAR(16) NOT NULL,            -- 'user' | 'assistant'
    conteudo    TEXT NOT NULL,
    criadoEm    TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT pk_mensagem PRIMARY KEY (mensagemId),
    CONSTRAINT fk_mensagem_conversa FOREIGN KEY (conversaId)
        REFERENCES conversa(conversaId) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mensagem_conversa ON mensagem(conversaId, mensagemId);


-- ---------------------------------------------------------------------------
-- conversaContexto: arquivos enviados como contexto EXCLUSIVO de uma conversa
-- (o "drag and drop" da tela de chat). Guardamos o texto extraído para injetar
-- no prompt daquela sessão, sem poluir a base vetorial global.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversaContexto (
    contextoId   SERIAL,
    conversaId   INTEGER NOT NULL,
    nomeArquivo  TEXT NOT NULL,
    conteudo     TEXT NOT NULL,                  -- texto extraído do arquivo
    criadoEm     TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT pk_contexto PRIMARY KEY (contextoId),
    CONSTRAINT fk_contexto_conversa FOREIGN KEY (conversaId)
        REFERENCES conversa(conversaId) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_contexto_conversa ON conversaContexto(conversaId, contextoId);
