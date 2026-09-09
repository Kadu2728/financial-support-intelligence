"""Ponto unico de importacao dos modelos.

O Alembic compara o schema do banco com `Base.metadata`, e uma tabela so entra no
metadata se a classe tiver sido importada. Sem este modulo, um modelo esquecido nao
gera erro: o autogenerate simplesmente nao o inclui, e a tabela some silenciosamente
da migration.

Importar aqui e resolver de uma vez: `alembic/env.py` importa apenas este arquivo.
"""

from app.db.base import Base
from app.modules.auth.models import RefreshToken
from app.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.modules.feedback.models import Feedback
from app.modules.ingestion.models import ProcessingJob
from app.modules.queries.models import Answer, Citation, Query
from app.modules.users.models import User

__all__ = [
    "Answer",
    "Base",
    "Citation",
    "Document",
    "DocumentChunk",
    "DocumentVersion",
    "Feedback",
    "ProcessingJob",
    "Query",
    "RefreshToken",
    "User",
]
