"""Fontes de dados de licitações e contratos públicos.

Além das fontes, expõe `montar_fontes(config, http, progresso)`, que monta a
lista de fontes ativas segundo os flags da `Config`. Fontes ainda não
implementadas são incluídas apenas como aviso (stubs) quando habilitadas.
"""

from __future__ import annotations

from ..config import Config
from ..http_client import ClienteHTTP
from .base import FonteBase
from .bancos import FonteBNDES, FonteCaixa, FonteLicitacoesE, FontePetronect
from .compras_gov import FonteComprasGov
from .estaduais import (
    FonteBLLCompras,
    FonteBecSP,
    FonteComprasPublicas,
    FonteComprasRS,
    FonteENegociosSP,
)
from .pncp import FontePNCP

__all__ = [
    "FonteBase",
    "FontePNCP",
    "FonteComprasGov",
    "FonteENegociosSP",
    "FonteLicitacoesE",
    "FonteCaixa",
    "FonteBNDES",
    "FontePetronect",
    "FonteBecSP",
    "FonteComprasRS",
    "FonteComprasPublicas",
    "FonteBLLCompras",
    "montar_fontes",
]


def montar_fontes(config: Config, http: ClienteHTTP, progresso=None) -> list[FonteBase]:
    """Fontes base (independentes), na ordem de execução."""
    fontes: list[FonteBase] = [FontePNCP(http, config, progresso=progresso)]

    if config.usar_compras_gov:
        fontes.append(FonteComprasGov(http, config, progresso=progresso))

    if config.usar_licitacoes_e:
        fontes.append(FonteLicitacoesE(http, config, progresso=progresso))
    if config.usar_caixa:
        fontes.append(FonteCaixa(http, config, progresso=progresso))
    if config.usar_bndes:
        fontes.append(FonteBNDES(http, config, progresso=progresso))
    if config.usar_petronect:
        fontes.append(FontePetronect(http, config, progresso=progresso))

    if config.usar_bec_sp:
        fontes.append(FonteBecSP(http, config, progresso=progresso))
    if config.usar_compras_rs:
        fontes.append(FonteComprasRS(http, config, progresso=progresso))
    if config.usar_compras_publicas:
        fontes.append(FonteComprasPublicas(http, config, progresso=progresso))
    if config.usar_bll_compras:
        fontes.append(FonteBLLCompras(http, config, progresso=progresso))

    return fontes
