"""
rag/conversation_store.py
Estado de conversa em memória (versão protótipo).

Guarda, por conversation_id:
  - histórico de mensagens (role + conteúdo);
  - o documento (TR) atualmente ativo na conversa.

Isto é o que viabiliza o fluxo conversacional pedido pelo mentor:
o usuário gera um TR, e nas mensagens seguintes pode pedir alterações
sem reenviar todo o contexto — o último TR fica guardado aqui.

LIMITAÇÃO CONHECIDA:
  Tudo vive em RAM. Reiniciar o servidor zera as conversas.
  A interface foi desenhada para ser trocada por PostgreSQL depois
  (tabelas chat_session / chat_message / generated_document) sem alterar
  quem a consome (rag.py e app.py). Basta criar outra implementação com
  os mesmos métodos e substituir a instância STORE no final do arquivo.
"""
import copy
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_conversation(conversation_id: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "created_at": _now(),
        "messages": [],          # [{role, content, at}]
        "current_document": None,  # dict do TR ativo, ou None
    }


class InMemoryConversationStore:
    """Implementação simples baseada em dicionário, segura para threads."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        """Cria uma conversa nova e devolve o seu id."""
        conversation_id = uuid.uuid4().hex
        with self._lock:
            self._data[conversation_id] = _new_conversation(conversation_id)
        return conversation_id

    def ensure(self, conversation_id: Optional[str]) -> str:
        """
        Garante que exista uma conversa válida.

        - conversation_id vazio/None  -> cria uma nova e devolve o id.
        - conversation_id desconhecido -> registra esse id (cliente trouxe o seu).
        - conversation_id existente    -> devolve como está.
        """
        if not conversation_id:
            return self.create()

        with self._lock:
            if conversation_id not in self._data:
                self._data[conversation_id] = _new_conversation(conversation_id)

        return conversation_id

    def get(self, conversation_id: str) -> Optional[dict]:
        """Devolve uma cópia da conversa inteira (ou None)."""
        with self._lock:
            convo = self._data.get(conversation_id)
            return copy.deepcopy(convo) if convo else None

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return
            convo["messages"].append({
                "role": role,
                "content": content,
                "at": _now(),
            })

    def set_current_document(self, conversation_id: str, document: dict) -> None:
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None:
                return
            convo["current_document"] = copy.deepcopy(document)

    def get_current_document(self, conversation_id: str) -> Optional[dict]:
        """Devolve uma cópia do documento ativo (ou None)."""
        with self._lock:
            convo = self._data.get(conversation_id)
            if convo is None or convo.get("current_document") is None:
                return None
            return copy.deepcopy(convo["current_document"])

    def has_active_tr(self, conversation_id: str) -> bool:
        """True se a conversa já tem um TR gerado e pronto para edição."""
        doc = self.get_current_document(conversation_id)
        return bool(doc and doc.get("type") == "tr")


# Instância única usada pela aplicação (singleton de módulo).
# Para migrar para banco, troque por outra implementação com os mesmos métodos.
STORE = InMemoryConversationStore()
