"""Armazenamento local e geracao de chaves."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.integrations.storage.base import ObjectNotFound, StorageError, build_storage_key
from app.integrations.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


# --- Geracao de chave ------------------------------------------------------


def test_chave_e_derivada_de_ids_nao_do_nome() -> None:
    doc, ver = uuid.uuid4(), uuid.uuid4()

    chave = build_storage_key(document_id=doc, version_id=ver, filename="manual.pdf")

    assert chave == f"documents/{doc}/{ver}.pdf"


@pytest.mark.parametrize(
    "nome_malicioso",
    [
        "../../../etc/passwd",
        "..\\..\\windows\\system32\\config",
        "/etc/shadow",
        "arquivo.pdf/../../fora.txt",
        "....//....//escape.pdf",
    ],
)
def test_nome_malicioso_nao_escapa_do_prefixo(nome_malicioso: str) -> None:
    """Path traversal e eliminado por construcao: so a extensao vem do nome enviado."""
    doc, ver = uuid.uuid4(), uuid.uuid4()

    chave = build_storage_key(document_id=doc, version_id=ver, filename=nome_malicioso)

    assert chave.startswith(f"documents/{doc}/{ver}")
    assert ".." not in chave
    assert chave.count("/") == 2


@pytest.mark.parametrize(
    "nome",
    ["sem_extensao", "arquivo.", "arquivo.extensao-muito-longa", "arquivo.p df"],
)
def test_extensao_suspeita_e_descartada(nome: str) -> None:
    doc, ver = uuid.uuid4(), uuid.uuid4()

    chave = build_storage_key(document_id=doc, version_id=ver, filename=nome)

    assert chave == f"documents/{doc}/{ver}"


def test_extensao_e_normalizada_para_minuscula() -> None:
    doc, ver = uuid.uuid4(), uuid.uuid4()

    chave = build_storage_key(document_id=doc, version_id=ver, filename="MANUAL.PDF")

    assert chave.endswith(".pdf")


# --- LocalStorage ----------------------------------------------------------


async def test_grava_e_le(storage: LocalStorage) -> None:
    await storage.put("documents/a/b.pdf", b"conteudo", content_type="application/pdf")

    assert await storage.get("documents/a/b.pdf") == b"conteudo"
    assert await storage.exists("documents/a/b.pdf")


async def test_ler_objeto_inexistente_levanta_not_found(storage: LocalStorage) -> None:
    """Distinto de erro de storage: o chamador precisa diferenciar "sumiu" de "falhou"."""
    with pytest.raises(ObjectNotFound):
        await storage.get("documents/nao/existe.pdf")


async def test_exists_e_falso_para_inexistente(storage: LocalStorage) -> None:
    assert not await storage.exists("documents/nao/existe.pdf")


async def test_delete_e_idempotente(storage: LocalStorage) -> None:
    """Apagar duas vezes acontece em retry e limpeza de orfao; nao pode ser erro."""
    await storage.put("documents/a/b.pdf", b"x", content_type="application/pdf")

    await storage.delete("documents/a/b.pdf")
    await storage.delete("documents/a/b.pdf")

    assert not await storage.exists("documents/a/b.pdf")


async def test_sobrescrita_substitui_por_completo(storage: LocalStorage) -> None:
    await storage.put("k", b"conteudo original longo", content_type="text/plain")
    await storage.put("k", b"curto", content_type="text/plain")

    assert await storage.get("k") == b"curto"


async def test_nao_deixa_arquivo_temporario(storage: LocalStorage, tmp_path: Path) -> None:
    """A escrita usa temporario + rename para nunca expor objeto truncado."""
    await storage.put("documents/a/b.pdf", b"conteudo", content_type="application/pdf")

    assert list((tmp_path / "storage").rglob("*.tmp")) == []


async def test_chave_fora_da_raiz_e_recusada(storage: LocalStorage) -> None:
    """Defesa em profundidade: a chave ja e gerada pelo servidor, mas um bug futuro
    que a derive de entrada do usuario nao pode virar escrita fora do storage."""
    with pytest.raises(StorageError):
        await storage.put("../fora.txt", b"x", content_type="text/plain")


async def test_subdiretorios_sao_criados(storage: LocalStorage) -> None:
    await storage.put("a/b/c/d/e.pdf", b"x", content_type="application/pdf")

    assert await storage.exists("a/b/c/d/e.pdf")
