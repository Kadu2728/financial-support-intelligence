from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.users.models import Role

# Politica de senha. 12 caracteres em vez dos 8 habituais: para senha gerada por humano,
# comprimento protege mais que exigencia de simbolos, que na pratica produz
# "Senha@123" — curta, previsivel e formalmente valida.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str = Field(min_length=2, max_length=255)
    role: Role = Role.ANALYST

    @field_validator("password")
    @classmethod
    def _reject_obvious_passwords(cls, value: str) -> str:
        if value.lower() in _SENHAS_PROIBIDAS:
            raise ValueError("Senha muito comum. Escolha outra.")
        return value

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()


# Lista curta e proposital: bloqueia o que passaria pelo comprimento minimo mas cairia
# no primeiro dicionario. Uma verificacao real (k-anonymity contra base de vazamentos)
# fica registrada como melhoria, nao como requisito da fase.
_SENHAS_PROIBIDAS = frozenset(
    {
        "senha123456",
        "123456789012",
        "password1234",
        "qwertyuiop12",
        "financialsupport",
    }
)
