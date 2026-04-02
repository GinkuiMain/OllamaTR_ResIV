"""
auth/auth.py
Lógica central de autenticação: hash, verificação de senha, JWT e dependência
de rota para proteger endpoints futuros.

Fluxo de login:
  1. Cliente POST /auth/login com { email, password }
  2. Busca o usuário no PostgreSQL pelo email
  3. Verifica a senha com bcrypt
  4. Mapeia tipoUsuarioId → role ("user" | "admin")
  5. Gera um JWT assinado com HS256
  6. Retorna { access_token, token_type, role, user_id, user_name }

Protegendo um endpoint (uso futuro):
  from auth.auth import require_auth, require_admin

  @app.get("/rota-protegida")
  def rota(current_user = Depends(require_auth)):
      ...

  @app.post("/admin/algo")
  def admin_rota(current_user = Depends(require_admin)):
      ...
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt

from .database import get_connection
from .schemas import TokenData

load_dotenv()

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("JWT_SECRET", "troque-este-segredo-em-producao")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", 480))  # 8 horas

# Mapeamento tipoUsuarioId → role string
# Conforme Inserts.sql: 1 = Usuario Tecnico, 2 = Administrador, 3 = Juridico
_ROLE_MAP = {
    1: "user",
    2: "admin",
    3: "user",   # Jurídico recebe "user" por enquanto; expanda quando necessário
}

bearer_scheme = HTTPBearer()


# ---------------------------------------------------------------------------
# Utilitários de senha
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(user_id: int, role: str) -> str:
    """Gera um JWT com user_id e role no payload."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenData:
    """
    Decodifica e valida o JWT.
    Lança HTTPException 401 se inválido ou expirado.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        role = payload.get("role")
        if not user_id or not role:
            raise ValueError("Payload incompleto")
        return TokenData(user_id=user_id, role=role)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Busca de usuário no banco
# ---------------------------------------------------------------------------
def get_user_by_email(email: str) -> dict | None:
    """
    Retorna o registro do usuário (com tipoUsuarioId) ou None se não existir.
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.userId, u.userName, u.hashPass, u.email, u.tipoUsuarioId
                FROM usuario u
                WHERE u.email = %s
                LIMIT 1
                """,
                (email,),
            )
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro ao consultar o banco de dados: {e}",
        )


# ---------------------------------------------------------------------------
# Dependências FastAPI
# ---------------------------------------------------------------------------
def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenData:
    """
    Dependência que valida o Bearer token.
    Use em qualquer endpoint que exija login.
    """
    return decode_token(credentials.credentials)


def require_admin(token_data: TokenData = Depends(require_auth)) -> TokenData:
    """
    Dependência que exige role == 'admin'.
    Lança 403 se o usuário for apenas 'user'.
    """
    if token_data.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores.",
        )
    return token_data


# ---------------------------------------------------------------------------
# Lógica de login (chamada pelo endpoint)
# ---------------------------------------------------------------------------
def login(email: str, password: str) -> dict:
    """
    Autentica o usuário e retorna o payload do token.
    Lança HTTPException 401 se as credenciais forem inválidas.
    """
    user = get_user_by_email(email)

    if not user or not verify_password(password, user["hashpass"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = _ROLE_MAP.get(user["tipousuarioid"], "user")
    token = create_access_token(user_id=user["userid"], role=role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": role,
        "user_id": user["userid"],
        "user_name": user["username"],
    }
