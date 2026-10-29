"""Portais de bancos públicos e sociedades de economia mista.

Todas as fontes abaixo são **apenas estruturadas** (stubs): cada portal exige
engenharia de site específica (autenticação, JavaScript, catálogos distintos).
Elas expõem `disponivel = False` e registram um aviso claro quando habilitadas,
para não confundir "sem resultados" com "fonte não implementada".
"""

from __future__ import annotations

from ..models import RegistroLicitacao
from .base import FonteBase


class _FontePendente(FonteBase):
    disponivel = False
    instrucao = ""

    def coletar(self) -> list[RegistroLicitacao]:
        self._avisar(
            f"{self.nome}: fonte habilitada, mas ainda não implementada. "
            f"{self.instrucao}".strip()
        )
        return []


class FonteLicitacoesE(_FontePendente):
    """Banco do Brasil — Licitações-E."""

    nome = "Licitações-E (BB)"
    instrucao = "Requer engenharia de site específica (Licitações-E / BB)."


class FonteCaixa(_FontePendente):
    """Caixa Econômica Federal — Portal de Licitações."""

    nome = "CAIXA"
    instrucao = "Requer engenharia de site específica (Portal de Licitações CAIXA)."


class FonteBNDES(_FontePendente):
    """BNDES — licitações e contratações."""

    nome = "BNDES"
    instrucao = "Requer engenharia de site específica (BNDES)."


class FontePetronect(_FontePendente):
    """Petrobras — Petronect."""

    nome = "Petronect"
    instrucao = "Requer engenharia de site específica (Petronect / Petrobras)."
