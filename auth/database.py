"""
auth/database.py
Conexão com o PostgreSQL via psycopg2.

Lê as credenciais de variáveis de ambiente (ou .env via python-dotenv).
Variáveis esperadas:
  DB_HOST     (default: localhost)
  DB_PORT     (default: 5432)
  DB_NAME     (default: fsph)
  DB_USER     (default: postgres)
  DB_PASSWORD (obrigatório)
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()  # carrega .env se existir


def get_connection():
    """Abre e retorna uma nova conexão com o PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "fsph"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,  # rows como dicts
    )
