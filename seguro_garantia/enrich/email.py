"""Validação de e-mail: sintaxe + existência de servidor de e-mail no domínio.

Sem dependências obrigatórias:
1. Valida a sintaxe do endereço.
2. Rejeita domínios "placeholder" (exemplo, empresa, dominio...).
3. Consulta o registro MX do domínio (via `dig` do sistema ou dnspython); na
   ausência de MX, aceita se houver registro A (RFC permite entrega direta).

Importante: isso garante que o *domínio* recebe e-mail. Não é possível, sem
enviar mensagem, confirmar que a *caixa* específica existe — então um e-mail
como `contato@empresa.com.br` pode passar aqui e ainda voltar por não existir.

Os resultados são cacheados por domínio (uma consulta por domínio, no máximo).
Em caso de impossibilidade de consulta (sem rede/ferramenta), o e-mail é
considerado válido (fail-open) para não descartar dados por engano.
"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache

RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9\-]+)+)$")

# Domínios que nunca são de uma empresa real (placeholders/erro comum).
DOMINIOS_PLACEHOLDER = {
    "example.com", "example.com.br", "example.org", "exemplo.com",
    "exemplo.com.br", "empresa.com", "empresa.com.br", "empresas.com.br",
    "suaempresa.com", "suaempresa.com.br", "suaempresa.com",
    "dominio.com", "dominio.com.br", "seudominio.com", "seudominio.com.br",
    "domain.com", "domain.com.br", "meudominio.com", "meusite.com",
    "site.com", "site.com.br", "seusite.com", "seuemail.com", "seuemail.com.br",
    "email.com", "email.com.br", "mail.com", "test.com", "test.com.br",
    "teste.com", "teste.com.br", "abc.com", "abc.com.br", "localhost",
    "hotmail.com.br", "smtp.com", "noreply.com", "naoresponda.com",
}

_circuit_offline = False


def _dig(dominio: str, tipo: str) -> list[str] | None:
    """Retorna os registros DNS do tipo pedido, ou None se não foi possível."""
    try:
        proc = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=1", tipo, dominio],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [linha.strip() for linha in proc.stdout.splitlines() if linha.strip()]


def _mx_dnspython(dominio: str) -> bool | None:
    try:
        import dns.resolver  # type: ignore
    except ImportError:
        return None
    try:
        respostas = dns.resolver.resolve(dominio, "MX", lifetime=5)
        return len(list(respostas)) > 0
    except Exception:
        return None


@lru_cache(maxsize=4096)
def dominio_aceita_email(dominio: str) -> bool:
    global _circuit_offline
    dominio = dominio.lower().strip(".")
    if _circuit_offline:
        return True

    mx = _dig(dominio, "MX")
    if mx is None:
        via_py = _mx_dnspython(dominio)
        if via_py is None:
            _circuit_offline = True
            return True
        return via_py
    if mx:
        return True

    # Sem MX: alguns domínios aceitam e-mail no host principal (registro A).
    a = _dig(dominio, "A")
    if a is None:
        return True
    return bool(a)


def validar_email(email: str) -> tuple[bool, str]:
    """Retorna (valido, motivo). Motivo é 'ok' quando válido."""
    limpo = (email or "").strip().lower()
    if not limpo:
        return False, "vazio"
    casamento = RE_EMAIL.match(limpo)
    if not casamento:
        return False, "sintaxe inválida"
    dominio = casamento.group(1)
    if dominio in DOMINIOS_PLACEHOLDER:
        return False, "domínio placeholder"
    if not dominio_aceita_email(dominio):
        return False, "domínio sem servidor de e-mail"
    return True, "ok"


def email_valido(email: str) -> bool:
    return validar_email(email)[0]
