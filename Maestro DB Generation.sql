CREATE TABLE status(
	statusId SMALLSERIAL,
	statusNome VARCHAR(20) NOT NULL,
	
	CONSTRAINT pk_status PRIMARY KEY (statusId)
);


CREATE TABLE termo(
	termoId SERIAL,
	termoTitulo TEXT NOT NULL,
	termoPath TEXT NOT NULL, -- O DOCUMENTO QUE O ADMIN CADASTRAR!!!!! NAO O QUE O MAESTRO GERAR.
	criadoEm TIMESTAMPTZ DEFAULT NOW(),
	termoStatus SMALLINT NOT NULL,
	
	CONSTRAINT pk_termo PRIMARY KEY (termoId),
	CONSTRAINT fk_termo_status FOREIGN KEY (termoStatus) REFERENCES status(statusId)
);
CREATE INDEX idx_termo ON termo(termoTitulo); -- Acredito que a coisa que mais seja pesquisada seja justamente o nome, pelo usuario


-- Depois de feito isso, vamos montar a parte do usuario

CREATE TABLE permissoes(
	permId SMALLSERIAL,
	permName VARCHAR(50) NOT NULL,
	
	CONSTRAINT pk_perms PRIMARY KEY (permId)
);

CREATE TABLE tipoUsuario(
	tipoId SMALLSERIAL, -- Ja que teremos valores predefinidos (0 - usuario / 1 - financeiro...) vou botar smallint
	tipoPerfil VARCHAR(50) NOT NULL, -- NOME do tipo de perfil
	
	CONSTRAINT pk_tipousuario PRIMARY KEY (tipoId)
);

CREATE TABLE permissoesUsuario(
	permsUserId SERIAL,
	tipoUserId SMALLINT NOT NULL,
	permId SMALLINT NOT NULL,
	
	CONSTRAINT pk_perms_user PRIMARY KEY (permsUserId),
	CONSTRAINT fk_permsuser_tipousuario FOREIGN KEY (tipoUserId) REFERENCES tipoUsuario(tipoId),
	CONSTRAINT fk_permsuser_perm FOREIGN KEY (permId) REFERENCES permissoes(permId)
);

CREATE TABLE usuario(
	userId SERIAL,
	userName VARCHAR(100) NOT NULL,
	hashPass TEXT NOT NULL,
	email VARCHAR(100) NOT NULL,
	tipoUsuarioId SMALLINT NOT NULL,
	
	CONSTRAINT pk_user PRIMARY KEY (userId),
	CONSTRAINT fk_user_tipo FOREIGN KEY (tipoUsuarioId) REFERENCES tipoUsuario(tipoId)
);

CREATE TABLE analisadoPor(
	analId SERIAL,
	userId INTEGER,
	termoId INTEGER,
	analisadoEm TIMESTAMPTZ DEFAULT NOW(),
	
	CONSTRAINT pk_anal_por PRIMARY KEY (analId),
	CONSTRAINT fk_anal_user FOREIGN KEY (userId) REFERENCES usuario(userId),
	CONSTRAINT fk_anal_term FOREIGN KEY (termoId) REFERENCES termo(termoId)
);

-- Gere conforme o diagrama, pra nao dar merda :)