"""Registro da última execução da prospecção.

Grava um JSON pequeno em ``DIRETORIO_SAIDA/ultima_execucao.json`` para que a
interface e o CLI consigam mostrar quando a coleta rodou, com quais parâmetros,
quantos registros foram encontrados e quais falhas ocorreram.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config

NOME_ARQUIVO = "ultima_execucao.json"


def caminho_ultima_execucao(config: Config) -> Path:
    return Path(config.diretorio_saida) / NOME_ARQUIVO


def registrar_ultima_execucao(config: Config, dados: dict[str, Any]) -> Path:
    """Grava o registro de forma atômica (evita JSON pela metade)."""
    caminho = caminho_ultima_execucao(config)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "executado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        **dados,
    }
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporario, caminho)
    return caminho


def ler_ultima_execucao(config: Config) -> dict[str, Any] | None:
    """Lê o último registro, devolvendo None quando ainda não existe."""
    caminho = caminho_ultima_execucao(config)
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
