"""
auth/schemas.py
Modelos Pydantic usados nos endpoints de autenticação.
"""

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str           # "user" | "admin"
    user_id: int
    user_name: str


class TokenData(BaseModel):
    """Payload decodificado do JWT (usado internamente)."""
    user_id: int
    role: str
