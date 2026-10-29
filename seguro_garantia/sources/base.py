"""Contrato comum a todas as fontes de licitações.

Para adicionar um portal novo (Licitações-E, TCE, portal estadual...), basta
implementar `coletar()` devolvendo uma lista de `RegistroLicitacao`. O restante
do pipeline (filtro de garantia, enriquecimento e exportação) já funciona.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..config import Config
from ..http_client import ClienteHTTP
from ..models import RegistroLicitacao

log = logging.getLogger("seguro_garantia.fonte")

Progresso = Callable[[str, int, int], None]


class FonteBase:
    nome = "base"

    def __init__(
        self,
        http: ClienteHTTP,
        config: Config,
        progresso: Progresso | None = None,
    ) -> None:
        self.http = http
        self.config = config
        self._progresso = progresso

    def coletar(self) -> list[RegistroLicitacao]:
        raise NotImplementedError

    def _log(self, msg: str) -> None:
        log.info("[%s] %s", self.nome, msg)

    def _avisar(self, msg: str, atual: int = 0, total: int = 0) -> None:
        """Reporta progresso para o log e para a interface (se houver)."""
        self._log(msg)
        if self._progresso:
            self._progresso(msg, atual, total)

