"""Validacao de arquivos.

Conteudo enviado por usuario e a superficie de ataque mais direta do sistema. Cada
teste aqui corresponde a uma forma de enganar a validacao.
"""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest

from app.modules.documents.validation import (
    MAX_FILE_SIZE_BYTES,
    DocumentFormat,
    EmptyFileError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    detect_format,
    read_and_validate,
)

PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


def docx(*, valido: bool = True) -> bytes:
    """DOCX minimo. `valido=False` produz um ZIP sem o conteudo caracteristico."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        if valido:
            arquivo.writestr("word/document.xml", "<w:document/>")
            arquivo.writestr("[Content_Types].xml", "<Types/>")
        else:
            arquivo.writestr("xl/workbook.xml", "<workbook/>")  # e um .xlsx
    return buffer.getvalue()


# --- Deteccao de formato ---------------------------------------------------


def test_pdf_e_reconhecido() -> None:
    assert detect_format(PDF, filename="manual.pdf") is DocumentFormat.PDF


def test_docx_e_reconhecido() -> None:
    assert detect_format(docx(), filename="procedimento.docx") is DocumentFormat.DOCX


def test_xlsx_disfarcado_de_docx_e_recusado() -> None:
    """Todo Office moderno e ZIP. Sem olhar dentro, um .xlsx passaria por .docx e o
    extrator da Fase 5 falharia com um erro sem relacao aparente com o upload."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_format(docx(valido=False), filename="planilha.docx")


def test_zip_comum_e_recusado() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("qualquer.txt", "conteudo")

    with pytest.raises(UnsupportedFileTypeError):
        detect_format(buffer.getvalue(), filename="arquivo.docx")


def test_markdown_vem_da_extensao() -> None:
    conteudo = b"# Manual\n\nProcedimento de atualizacao."
    assert detect_format(conteudo, filename="manual.md") is DocumentFormat.MARKDOWN
    assert detect_format(conteudo, filename="manual.txt") is DocumentFormat.TEXT


def test_texto_com_acentuacao_e_aceito() -> None:
    conteudo = "Atualização cadastral: verificação de documentação.".encode()
    assert detect_format(conteudo, filename="nota.txt") is DocumentFormat.TEXT


@pytest.mark.parametrize(
    ("descricao", "conteudo"),
    [
        ("executavel windows", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64),
        ("elf linux", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64),
        ("png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64),
        ("gzip", b"\x1f\x8b\x08\x00" + bytes(range(32))),
    ],
)
def test_binarios_sao_recusados_mesmo_com_extensao_de_texto(
    descricao: str, conteudo: bytes
) -> None:
    """A extensao e escolhida por quem envia e nao diz nada sobre o conteudo."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_format(conteudo, filename="inofensivo.txt")


def test_pdf_falsificado_pela_extensao_e_recusado() -> None:
    """Renomear um executavel para .pdf e a tentativa mais obvia."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_format(b"MZ\x90\x00" + b"\x00" * 128, filename="manual.pdf")


def test_texto_com_byte_nulo_e_recusado() -> None:
    """Nenhum texto real contem byte nulo; todo binario contem varios."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_format(b"texto normal\x00seguido de binario", filename="nota.txt")


def test_utf16_e_recusado() -> None:
    """UTF-16 e legivel para humanos mas nao decodifica em UTF-8, e o pipeline de
    extracao assume UTF-8 em todo o caminho."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_format("procedimento".encode("utf-16"), filename="nota.txt")


# --- Leitura e limites -----------------------------------------------------


def test_checksum_confere_com_o_conteudo() -> None:
    resultado = read_and_validate(BytesIO(PDF), filename="manual.pdf")

    assert resultado.checksum_sha256 == hashlib.sha256(PDF).hexdigest()
    assert resultado.size_bytes == len(PDF)
    assert resultado.content == PDF


def test_mime_vem_do_formato_detectado_nao_do_cliente() -> None:
    resultado = read_and_validate(BytesIO(PDF), filename="manual.pdf")

    assert resultado.mime_type == "application/pdf"


def test_arquivo_vazio_e_recusado() -> None:
    with pytest.raises(EmptyFileError):
        read_and_validate(BytesIO(b""), filename="vazio.pdf")


def test_arquivo_acima_do_limite_e_recusado() -> None:
    grande = b"%PDF-1.7\n" + b"a" * (MAX_FILE_SIZE_BYTES + 1)

    with pytest.raises(FileTooLargeError):
        read_and_validate(BytesIO(grande), filename="grande.pdf")


def test_limite_interrompe_a_leitura_em_vez_de_carregar_tudo() -> None:
    """Verificar o tamanho depois de ler significa ja ter carregado o arquivo — que e
    exatamente o que o limite existe para impedir."""
    lidos = 0

    class StreamContado(BytesIO):
        def read(self, tamanho: int = -1, /) -> bytes:
            nonlocal lidos
            pedaco = super().read(tamanho)
            lidos += len(pedaco)
            return pedaco

    enorme = StreamContado(b"%PDF-1.7\n" + b"a" * (MAX_FILE_SIZE_BYTES * 3))

    with pytest.raises(FileTooLargeError):
        read_and_validate(enorme, filename="enorme.pdf")

    # Para em pouco mais que o limite — nao nos 75 MB do arquivo inteiro.
    assert lidos < MAX_FILE_SIZE_BYTES + (128 * 1024)


def test_arquivo_no_limite_exato_e_aceito() -> None:
    cabecalho = b"%PDF-1.7\n"
    exato = cabecalho + b"a" * (MAX_FILE_SIZE_BYTES - len(cabecalho))

    resultado = read_and_validate(BytesIO(exato), filename="limite.pdf")

    assert resultado.size_bytes == MAX_FILE_SIZE_BYTES
