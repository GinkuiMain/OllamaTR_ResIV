"""
rag/conversation_store.py
Estado de conversa do chat — agora PERSISTENTE.

Cada conversa pertence a um usuário (userId) e guarda:
  - título (estilo ChatGPT, derivado da 1ª mensagem);
  - histórico de mensagens (role + conteúdo);
  - o documento (TR) atualmente ativo na conversa;
  - arquivos enviados como contexto exclusivo daquela sessão.

Isto é o que viabiliza o pedido: o usuário gera um TR, o chat fica SALVO,
e mais tarde ele pode reabrir aquele chat e continuar editando o TR — e cada
edição continua passando pela IA/LLM (ver document_editor.py).

DOIS BACKENDS, MESMA INTERFACE
------------------------------
  - PostgresConversationStore  -> produção. Salva no banco (tabelas conversa,
                                  mensagem, conversaContexto). Sobrevive a
                                  reinícios do servidor.
  - InMemoryConversationStore  -> protótipo/testes. Vive em RAM.

Qual entra em uso é decidido no fim do arquivo pela variável de ambiente
CONV_STORE ("postgres" por padrão; use "memory" em testes).

Como a interface é idêntica, rag.py e app.py não sabem (nem precisam saber)
qual backend está ativo.
"""
import os
import copy
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers comuns
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value) -> Optional[str]:
    """Converte datetime -> ISO string; deixa o resto como está."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def derive_title(text: str, limit: int = 60) -> str:
    """Gera um título curto a partir da primeira mensagem (estilo ChatGPT)."""
    text = " ".join((text or "").split())
    if not text:
        return "Nova conversa"
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


# ===========================================================================
# Backend 1: PostgreSQL (persistente)
# ===========================================================================
class PostgresConversationStore:
    """
    Persiste conversas no PostgreSQL.

    Abre uma conexão por operação (mesmo padrão de auth/auth.py) e fecha em
    seguida — simples e seguro para o volume esperado. Se um dia virar gargalo,
    troca-se por um pool sem alterar a interface.
    """

    # --- infra -------------------------------------------------------------
    @staticmethod
    def _connect():
        # Import tardio: mantém o módulo importável mesmo sem psycopg2 quando
        # se usa apenas o backend em memória (ex.: testes de lógica).
        from auth.database import get_connection
        return get_connection()

    @staticmethod
    def _as_int(conversation_id) -> Optional[int]:
        try:
            return int(conversation_id)
        except (TypeError, ValueError):
            return None

    # --- ciclo de vida da conversa ----------------------------------------
    def create(self, user_id: int, titulo: Optional[str] = None) -> str:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO conversa (userId, titulo) VALUES (%s, %s) "
                    "RETURNING conversaId",
                    (user_id, titulo or "Nova conversa"),
                )
                new_id = cur.fetchone()["conversaid"]
            conn.commit()
            return str(new_id)
        finally:
            conn.close()

    def ensure(self, conversation_id: Optional[str], user_id: int) -> str:
        """
        Garante uma conversa válida E pertencente ao usuário.

        - vazio/None          -> cria uma nova para o usuário.
        - id inexistente      -> LookupError.
        - id de outro usuário -> PermissionError.
        - id do próprio       -> devolve como está.
        """
        if not conversation_id:
            return self.create(user_id)

        cid = self._as_int(conversation_id)
        if cid is None:
            raise LookupError("Conversa não encontrada.")

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT userId FROM conversa WHERE conversaId = %s", (cid,)
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if row is None:
            raise LookupError("Conversa não encontrada.")
        if int(row["userid"]) != int(user_id):
            raise PermissionError("Esta conversa não pertence ao usuário.")
        return str(cid)

    def delete(self, conversation_id: str) -> None:
        cid = self._as_int(conversation_id)
        if cid is None:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # ON DELETE CASCADE remove mensagens e contexto juntos.
                cur.execute("DELETE FROM conversa WHERE conversaId = %s", (cid,))
            conn.commit()
        finally:
            conn.close()

    # --- leitura -----------------------------------------------------------
    def get(self, conversation_id: str) -> Optional[dict]:
        cid = self._as_int(conversation_id)
        if cid is None:
            return None

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT conversaId, userId, titulo, documentoAtual, "
                    "criadoEm, atualizadoEm FROM conversa WHERE conversaId = %s",
                    (cid,),
                )
                convo = cur.fetchone()
                if convo is None:
                    return None

                cur.execute(
                    "SELECT role, conteudo, criadoEm FROM mensagem "
                    "WHERE conversaId = %s ORDER BY mensagemId ASC",
                    (cid,),
                )
                messages = cur.fetchall()

                cur.execute(
                    "SELECT nomeArquivo, criadoEm FROM conversaContexto "
                    "WHERE conversaId = %s ORDER BY contextoId ASC",
                    (cid,),
                )
                contexts = cur.fetchall()
        finally:
            conn.close()

        return {
            "conversation_id": str(convo["conversaid"]),
            "user_id": convo["userid"],
            "titulo": convo["titulo"],
            "created_at": _iso(convo["criadoem"]),
            "updated_at": _iso(convo["atualizadoem"]),
            "current_document": convo["documentoatual"],  # jsonb -> dict (ou None)
            "messages": [
                {
                    "role": m["role"],
                    "content": m["conteudo"],
                    "at": _iso(m["criadoem"]),
                }
                for m in messages
            ],
            "context_files": [
                {"filename": c["nomearquivo"], "at": _iso(c["criadoem"])}
                for c in contexts
            ],
        }

    def list_for_user(self, user_id: int) -> list[dict]:
        """Conversas do usuário, mais recentes primeiro (tela 'Listar Chats')."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT conversaId, titulo, criadoEm, atualizadoEm, "
                    "(documentoAtual->>'type') = 'tr' AS tem_tr "
                    "FROM conversa WHERE userId = %s "
                    "ORDER BY atualizadoEm DESC",
                    (user_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            {
                "conversation_id": str(r["conversaid"]),
                "titulo": r["titulo"],
                "created_at": _iso(r["criadoem"]),
                "updated_at": _iso(r["atualizadoem"]),
                "has_tr": bool(r["tem_tr"]),
            }
            for r in rows
        ]

    def get_current_document(self, conversation_id: str) -> Optional[dict]:
        cid = self._as_int(conversation_id)
        if cid is None:
            return None
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT documentoAtual FROM conversa WHERE conversaId = %s",
                    (cid,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return row["documentoatual"]  # já vem como dict (ou None)

    def has_active_tr(self, conversation_id: str) -> bool:
        doc = self.get_current_document(conversation_id)
        return bool(doc and doc.get("type") == "tr")

    # --- escrita -----------------------------------------------------------
    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        cid = self._as_int(conversation_id)
        if cid is None:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO mensagem (conversaId, role, conteudo) "
                    "VALUES (%s, %s, %s)",
                    (cid, role, content),
                )
                cur.execute(
                    "UPDATE conversa SET atualizadoEm = NOW() WHERE conversaId = %s",
                    (cid,),
                )
            conn.commit()
        finally:
            conn.close()

    def set_current_document(self, conversation_id: str, document: dict) -> None:
        cid = self._as_int(conversation_id)
        if cid is None:
            return
        from psycopg2.extras import Json
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE conversa SET documentoAtual = %s, atualizadoEm = NOW() "
                    "WHERE conversaId = %s",
                    (Json(document), cid),
                )
            conn.commit()
        finally:
            conn.close()

    def set_title(self, conversation_id: str, titulo: str) -> None:
        cid = self._as_int(conversation_id)
        if cid is None:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE conversa SET titulo = %s WHERE conversaId = %s",
                    (titulo, cid),
                )
            conn.commit()
        finally:
            conn.close()

    # --- contexto por sessão ----------------------------------------------
    def add_context(self, conversation_id: str, filename: str, text: str) -> None:
        cid = self._as_int(conversation_id)
        if cid is None:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO conversaContexto (conversaId, nomeArquivo, conteudo) "
                    "VALUES (%s, %s, %s)",
                    (cid, filename, text),
                )
                cur.execute(
                    "UPDATE conversa SET atualizadoEm = NOW() WHERE conversaId = %s",
                    (cid,),
                )
            conn.commit()
        finally:
            conn.close()

    def get_context_text(self, conversation_id: str) -> str:
        """Junta o texto de todos os arquivos de contexto da conversa."""
        cid = self._as_int(conversation_id)
        if cid is None:
            return ""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nomeArquivo, conteudo FROM conversaContexto "
                    "WHERE conversaId = %s ORDER BY contextoId ASC",
                    (cid,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return "\n\n".join(
            f"[Arquivo: {r['nomearquivo']}]\n{r['conteudo']}" for r in rows
        )


# ===========================================================================
# Backend 2: em memória (protótipo / testes)
# ===========================================================================
def _new_conversation(conversation_id: str, user_id: int, titulo: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "titulo": titulo or "Nova conversa",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "messages": [],            # [{role, content, at}]
        "current_document": None,  # dict do TR ativo, ou None
        "context_files": [],       # [{filename, text, at}]
    }


class InMemoryConversationStore:
    """Implementação baseada em dicionário, segura para threads. Não persiste."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, user_id: int, titulo: Optional[str] = None) -> str:
        conversation_id = uuid.uuid4().hex
        with self._lock:
            self._data[conversation_id] = _new_conversation(
                conversation_id, user_id, titulo
            )
        return conversation_id

    def ensure(self, conversation_id: Optional[str], user_id: int) -> str:
        if not conversation_id:
            return self.create(user_id)
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                raise LookupError("Conversa não encontrada.")
            if int(convo["user_id"]) != int(user_id):
                raise PermissionError("Esta conversa não pertence ao usuário.")
        return conversation_id

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._data.pop(conversation_id, None)

    def get(self, conversation_id: str) -> Optional[dict]:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return None
            convo = copy.deepcopy(convo)
        # Não devolve o texto cru dos arquivos (pode ser grande); só metadados.
        convo["context_files"] = [
            {"filename": c["filename"], "at": c["at"]}
            for c in convo.get("context_files", [])
        ]
        return convo

    def list_for_user(self, user_id: int) -> list[dict]:
        with self._lock:
            convos = [
                copy.deepcopy(c)
                for c in self._data.values()
                if int(c["user_id"]) == int(user_id)
            ]
        convos.sort(key=lambda c: c["updated_at"], reverse=True)
        return [
            {
                "conversation_id": c["conversation_id"],
                "titulo": c["titulo"],
                "created_at": c["created_at"],
                "updated_at": c["updated_at"],
                "has_tr": bool(
                    c.get("current_document")
                    and c["current_document"].get("type") == "tr"
                ),
            }
            for c in convos
        ]

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return
            convo["messages"].append(
                {"role": role, "content": content, "at": _now_iso()}
            )
            convo["updated_at"] = _now_iso()

    def set_current_document(self, conversation_id: str, document: dict) -> None:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return
            convo["current_document"] = copy.deepcopy(document)
            convo["updated_at"] = _now_iso()

    def get_current_document(self, conversation_id: str) -> Optional[dict]:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None or convo.get("current_document") is None:
                return None
            return copy.deepcopy(convo["current_document"])

    def has_active_tr(self, conversation_id: str) -> bool:
        doc = self.get_current_document(conversation_id)
        return bool(doc and doc.get("type") == "tr")

    def set_title(self, conversation_id: str, titulo: str) -> None:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return
            convo["titulo"] = titulo

    def add_context(self, conversation_id: str, filename: str, text: str) -> None:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return
            convo["context_files"].append(
                {"filename": filename, "text": text, "at": _now_iso()}
            )
            convo["updated_at"] = _now_iso()

    def get_context_text(self, conversation_id: str) -> str:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return ""
            files = list(convo.get("context_files", []))
        return "\n\n".join(
            f"[Arquivo: {c['filename']}]\n{c['text']}" for c in files
        )


# ===========================================================================
# Seleção do backend (singleton de módulo)
# ===========================================================================
def _build_store():
    backend = os.getenv("CONV_STORE", "postgres").strip().lower()
    if backend == "memory":
        return InMemoryConversationStore()
    return PostgresConversationStore()


STORE = _build_store()
