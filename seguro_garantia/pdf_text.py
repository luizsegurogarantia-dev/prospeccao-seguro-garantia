"""Extração opcional de texto de editais/contratos em PDF.

Usado apenas quando `LER_ANEXOS_PDF=true`, para procurar a cláusula de garantia
(arts. 96 a 102 da Lei 14.133/2021) dentro do documento. É uma etapa lenta:
cada PDF é baixado e lido, por isso aplica-se um teto de registros.
"""

from __future__ import annotations

import io
import logging

from .http_client import ClienteHTTP

log = logging.getLogger("seguro_garantia.pdf")

try:  # pypdf é opcional
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    _PYPDF_OK = True
except ImportError:  # pragma: no cover
    _PYPDF_OK = False


def ler_pdf(url: str, http: ClienteHTTP, max_caracteres: int = 400_000) -> str:
    """Baixa e extrai o texto de um PDF. Retorna "" em caso de falha."""
    if not _PYPDF_OK:
        log.warning("pypdf não instalado — leitura de PDF desabilitada")
        return ""
    if not url.lower().endswith(".pdf"):
        # Alguns arquivos vêm sem extensão; tenta mesmo assim.
        pass

    resp = http.session.get(url, timeout=http.timeout)
    if resp.status_code != 200 or "pdf" not in resp.headers.get("Content-Type", "").lower():
        return ""
    try:
        leitor = PdfReader(io.BytesIO(resp.content))
    except (PdfReadError, ValueError, OSError) as exc:
        log.debug("falha ao ler PDF %s: %s", url, exc)
        return ""

    partes = []
    for pagina in leitor.pages:
        try:
            partes.append(pagina.extract_text() or "")
        except Exception:  # pragma: no cover - tolerância a PDFs corrompidos
            continue
        if sum(len(p) for p in partes) > max_caracteres:
            break
    return "\n".join(partes)
