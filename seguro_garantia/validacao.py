"""Validação de CNPJ, datas e chaves de deduplicação.

Funções puras (sem rede) usadas pelo pipeline, pelos filtros, pela exportação
e pelos testes.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime


def somente_digitos(valor: object) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def validar_cnpj(cnpj: object) -> bool:
    """Valida os dígitos verificadores de um CNPJ (com ou sem formatação).

    Não consulta a Receita Federal: confirma apenas a consistência matemática.
    """
    digitos = somente_digitos(cnpj)
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False

    def _digito(base: str, pesos: list[int]) -> int:
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    if int(digitos[12]) != _digito(digitos[:12], pesos_1):
        return False
    return int(digitos[13]) == _digito(digitos[:13], pesos_2)


def formatar_cnpj(cnpj: object) -> str:
    """Devolve o CNPJ no formato 00.000.000/0000-00 quando possível."""
    digitos = somente_digitos(cnpj)
    if len(digitos) != 14:
        return str(cnpj or "")
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def parse_data(valor: object) -> date | None:
    """Converte datas ISO, DD/MM/AAAA ou datetime em ``date``.

    Devolve ``None`` quando o valor está vazio ou não é reconhecido.
    """
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor).strip()
    if not texto:
        return None

    # ISO: 2026-10-29, 2026-10-29T12:00:00, 2026-10-29 12:00:00
    if re.match(r"^\d{4}-\d{2}-\d{2}", texto):
        try:
            return date.fromisoformat(texto[:10])
        except ValueError:
            pass

    # Formatos brasileiros mais comuns.
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto[:10], fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def formatar_data(valor: object, vazio: str = "") -> str:
    """Formata a data como DD/MM/AAAA; mantém o texto original se não entender."""
    data = parse_data(valor)
    if data is None:
        return str(valor or vazio)
    return data.strftime("%d/%m/%Y")


def dentro_janela(
    valor: object,
    data_inicial: date,
    data_final: date,
) -> bool | None:
    """Diz se a data está na janela inclusiva.

    Retorna ``None`` quando a data não pode ser interpretada, para que o
    chamador decida entre sinalizar pendência ou descartar o registro.
    """
    data = parse_data(valor)
    if data is None:
        return None
    return data_inicial <= data <= data_final


def normalizar_chave(valor: object) -> str:
    """Normaliza texto para comparação (sem acento, pontuação ou caixa)."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", "-", texto.lower())
    return texto.strip("-")
