"""Filtro de cláusula de garantia e cálculo do valor de garantia exigida.

A Lei 14.133/2021 (arts. 96 a 102) prevê garantia de execução contratual. Na
prática, todo contrato de obra/serviço de grande vulto exige garantia — por isso
o filtro por palavra-chave é opcional (`FILTRO_GARANTIA_ESTRITO`), servindo para
priorizar registros cujo texto cita explicitamente garantia/caução/aditivo.
"""

from __future__ import annotations

import re
import unicodedata

from .models import RegistroLicitacao

RE_PERCENTUAL = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
RE_VALOR_GARANTIA = re.compile(
    r"garantia[^.]{0,120}?r\$\s*([\d.,]+)", re.IGNORECASE
)
# "prazo de 10 (dez) dias", "em até 5 dias úteis", "no prazo de 30 dias"
RE_PRAZO_DIAS = re.compile(
    r"(?:prazo|ate|até|dentro de)\D{0,25}?(\d{1,3})\s*(?:\([^)]*\)\s*)?dias",
    re.IGNORECASE,
)
# "vigência de 12 meses", "vigência mínima de 3 anos"
RE_VIGENCIA = re.compile(
    r"vig[eê]ncia[^.]{0,40}?(\d{1,3})\s*(dias|meses|anos)", re.IGNORECASE
)
MODALIDADES = (
    ("seguro-garantia", "Seguro garantia"),
    ("seguro garantia", "Seguro garantia"),
    ("fianca bancaria", "Fiança bancária"),
    ("fiança bancária", "Fiança bancária"),
    ("caucao em dinheiro", "Caução em dinheiro"),
    ("caucao", "Caução"),
    ("título de capitalização", "Título de capitalização"),
)


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparação robusta de palavras-chave."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def encontrar_palavras(texto: str, palavras: list[str]) -> list[str]:
    base = normalizar(texto)
    if not base:
        return []
    return [p for p in palavras if normalizar(p) in base]


def registro_tem_garantia(registro: RegistroLicitacao, palavras: list[str]) -> bool:
    texto = " ".join([registro.objeto or "", registro.texto_extra or ""])
    return bool(encontrar_palavras(texto, palavras))


def registro_do_ramo(registro: RegistroLicitacao, palavras: list[str]) -> bool:
    """Diz se o objeto do contrato/edital é de um ramo alvo.

    Considera o objeto e, quando houver, o texto extraído do edital. Comparação
    sem acento e sem diferenciar maiúsculas/minúsculas (ver `normalizar`).
    """
    if not palavras:
        return True
    texto = " ".join([registro.objeto or "", registro.texto_extra or ""])
    return bool(encontrar_palavras(texto, palavras))


def cnae_do_ramo(cnae: str, prefixos: list[str]) -> bool:
    """Diz se um CNAE (ex.: '4120-4/00 - Construção de edifícios') bate com os
    prefixos-alvo (ex.: '41', '42', '43')."""
    if not prefixos:
        return True
    digitos = "".join(c for c in (cnae or "") if c.isdigit())[:4]
    if len(digitos) < 2:
        return False
    return any(digitos.startswith(p) for p in prefixos)


def calcular_valor_garantia(
    valor: float,
    percentual: float,
    texto_edital: str = "",
) -> float:
    """Estima a garantia exigida.

    Se o texto do edital informar um percentual de garantia, ele prevalece;
    caso contrário usa-se o `percentual` padrão (ex.: 5%).
    """
    if valor <= 0:
        return 0.0
    percentual_efetivo = percentual
    extraido = extrair_percentual_garantia(texto_edital)
    if extraido is not None:
        percentual_efetivo = extraido
    return round(valor * percentual_efetivo, 2)


def extrair_percentual_garantia(texto: str) -> float | None:
    """Procura um percentual de garantia no texto do edital, se disponível."""
    if not texto:
        return None
    base = normalizar(texto)
    trechos = []
    for gatilho in ("garantia", "caução", "caucao"):
        idx = base.find(gatilho)
        if idx >= 0:
            trechos.append(base[idx : idx + 200])
    for trecho in trechos:
        match = RE_PERCENTUAL.search(trecho)
        if match:
            valor = float(match.group(1).replace(",", "."))
            if 0 < valor <= 30:  # limite legal: garantia de até 30% do valor
                return valor / 100.0
    return None


def valor_garantia_em_texto(texto: str) -> float | None:
    """Procura um valor em R$ citado junto da palavra garantia."""
    if not texto:
        return None
    match = RE_VALOR_GARANTIA.search(texto)
    if not match:
        return None
    bruto = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(bruto)
    except ValueError:
        return None


def extrair_clausula_garantia(texto: str) -> dict[str, str]:
    """Extrai os termos da cláusula de garantia para a planilha.

    Devolve um dicionário com `percentual`, `prazo`, `modalidade` e `vigencia`
    já formatados para leitura humana. Campos não encontrados vêm vazios.
    """
    vazio = {"percentual": "", "prazo": "", "modalidade": "", "vigencia": ""}
    if not texto:
        return vazio

    base = normalizar(texto)
    janelas: list[str] = []
    inicio = 0
    for _ in range(4):
        idx = base.find("garantia", inicio)
        if idx < 0:
            break
        janelas.append(base[max(0, idx - 120) : idx + 700])
        inicio = idx + 1
    if not janelas:
        return vazio

    percentual = ""
    prazo = ""
    vigencia = ""
    modalidades: list[str] = []

    for janela in janelas:
        if not percentual:
            for achado in RE_PERCENTUAL.finditer(janela):
                valor = float(achado.group(1).replace(",", "."))
                if 0 < valor <= 30:
                    percentual = f"{valor:g}%"
                    break
        if not prazo:
            achado = RE_PRAZO_DIAS.search(janela)
            if achado:
                prazo = f"{int(achado.group(1))} dias"
        if not vigencia:
            achado = RE_VIGENCIA.search(janela)
            if achado:
                vigencia = f"{int(achado.group(1))} {achado.group(2).lower()}"
        for termo, rotulo in MODALIDADES:
            if rotulo not in modalidades and normalizar(termo) in janela:
                modalidades.append(rotulo)

    return {
        "percentual": percentual,
        "prazo": prazo,
        "modalidade": " / ".join(modalidades[:3]),
        "vigencia": vigencia,
    }
