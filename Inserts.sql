-- Status basicos do termo
INSERT INTO status (statusNome) VALUES
('Pendente'),
('Aprovado'),
('Cancelado');


-- Tipos de usuario conforme as personas do projeto
INSERT INTO tipoUsuario (tipoPerfil) VALUES
('Usuario Tecnico'),
('Administrador'),
('Juridico');


-- Permissoes baseadas nas funcionalidades descritas na documentacao
INSERT INTO permissoes (permName) VALUES
('ACESSAR_SISTEMA'),
('USAR_CHAT_IA'),
('VISUALIZAR_TR'),
('EDITAR_TR'),
('EXPORTAR_TR'),
('UPLOAD_DOCUMENTO_BASE'),
('GERENCIAR_BASE_CONHECIMENTO'),
('GERENCIAR_USUARIOS'),
('GERENCIAR_PERMISSOES'),
('AJUSTAR_PARAMETROS_MODELO'),
('REVISAR_TR'),
('VALIDAR_CONFORMIDADE'),
('HOMOLOGAR_TR');


-- Relacao entre tipo de usuario e permissoes
-- Assumindo:
-- 1 = Usuario Tecnico
-- 2 = Administrador
-- 3 = Juridico

-- Usuario Tecnico
INSERT INTO permissoesUsuario (tipoUserId, permId) VALUES
(1, 1), -- ACESSAR_SISTEMA
(1, 2), -- USAR_CHAT_IA
(1, 3), -- VISUALIZAR_TR
(1, 4), -- EDITAR_TR
(1, 5); -- EXPORTAR_TR

-- Administrador
INSERT INTO permissoesUsuario (tipoUserId, permId) VALUES
(2, 1),  -- ACESSAR_SISTEMA
(2, 3),  -- VISUALIZAR_TR
(2, 4),  -- EDITAR_TR
(2, 5),  -- EXPORTAR_TR
(2, 6),  -- UPLOAD_DOCUMENTO_BASE
(2, 7),  -- GERENCIAR_BASE_CONHECIMENTO
(2, 8),  -- GERENCIAR_USUARIOS
(2, 9),  -- GERENCIAR_PERMISSOES
(2, 10); -- AJUSTAR_PARAMETROS_MODELO

-- Juridico
INSERT INTO permissoesUsuario (tipoUserId, permId) VALUES
(3, 1),  -- ACESSAR_SISTEMA
(3, 3),  -- VISUALIZAR_TR
(3, 4),  -- EDITAR_TR
(3, 5),  -- EXPORTAR_TR
(3, 11), -- REVISAR_TR
(3, 12), -- VALIDAR_CONFORMIDADE
(3, 13); -- HOMOLOGAR_TR