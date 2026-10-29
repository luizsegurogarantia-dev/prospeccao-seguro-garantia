"""Consulta de sanções públicas (CEIS e CNEP) pelo Portal da Transparência.

Serve para responder, antes de investir tempo numa proposta, se a empresa
vencedora está **impedida de contratar** ou **sancionada** — situação em que a
seguradora normalmente recusa a emissão da apólice.

A API é pública, mas exige uma chave gratuita (cadastro em
<https://api.portaldatransparencia.gov.br>). Sem `TRANSPARENCIA_API_KEY`
configurada, a consulta é ignorada e a planilha mostra "Não verificado".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import Config
from ..http_client import ClienteHTTP

log = logging.getLogger("seguro_garantia.sancoes")

URL_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"

# Rótulos amigáveis para as duas bases consultadas.
BASES = {
    "ceis": "CEIS (impedimento/suspensão)",
    "cnep": "CNEP (punição)",
}


class ConsultorSancoes:
    def __init__(self, http: ClienteHTTP, config: Config) -> None:
        self.http = http
        self.config = config
        self.chave = (config.transparencia_api_key or "").strip()
        self.diretorio_cache: Path = config.diretorio_cache_sancoes
        if self.ativa:
            self.diretorio_cache.mkdir(parents=True, exist_ok=True)

    @property
    def ativa(self) -> bool:
        return bool(self.chave) and self.config.enriquecer_sancoes

    def consultar(self, cnpj: str) -> tuple[list[str], bool]:
        """Devolve (lista de sanções, consulta_realizada)."""
        cnpj = "".join(c for c in str(cnpj or "") if c.isdigit())
        if not self.ativa or len(cnpj) != 14:
            return [], False

        cache = self._ler_cache(cnpj)
        if cache is not None:
            return cache

        sancoes: list[str] = []
        verificado = False
        for base in BASES:
            itens = self._buscar(base, cnpj)
            if itens is None:
                continue  # erro/limite: não marca como verificado
            verificado = True
            sancoes.extend(_formatar_itens(base, itens))
            self.http.dormir(self.config.pausa_sancoes)

        if verificado:
            self._gravar_cache(cnpj, sancoes)
        return sancoes, verificado

    # ------------------------------------------------------------------ HTTP
    def _buscar(self, base: str, cnpj: str) -> list[dict] | None:
        payload = self.http.get(
            f"{URL_BASE}/{base}",
            params={"codigoSancionado": cnpj, "pagina": 1},
            headers={"chave-api-dados": self.chave},
        )
        if payload is None:
            return None
        if isinstance(payload, dict):  # alguns retornos vêm embrulhados
            payload = payload.get("content") or payload.get("data") or []
        return payload if isinstance(payload, list) else []

    # ----------------------------------------------------------------- cache
    def _caminho_cache(self, cnpj: str) -> Path:
        return self.diretorio_cache / f"{cnpj}.json"

    def _ler_cache(self, cnpj: str) -> tuple[list[str], bool] | None:
        caminho = self._caminho_cache(cnpj)
        if not caminho.exists():
            return None
        try:
            d = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(d, dict):
            return None
        return list(d.get("sancoes") or []), True

    def _gravar_cache(self, cnpj: str, sancoes: list[str]) -> None:
        try:
            self._caminho_cache(cnpj).write_text(
                json.dumps({"sancoes": sancoes}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass


def _formatar_itens(base: str, itens: list[dict]) -> list[str]:
    formatados: list[str] = []
    for item in itens:
        tipo = item.get("tipoSancao") or {}
        if isinstance(tipo, dict):
            descricao = (
                tipo.get("descricaoResumida")
                or tipo.get("descricaoDetalhada")
                or tipo.get("descricao")
                or ""
            )
        else:
            descricao = str(tipo or "")
        inicio = _data(item.get("dataInicioSancao"))
        fim = _data(item.get("dataFimSancao"))
        orgao = item.get("orgaoSancionador") or {}
        nome_orgao = (
            orgao.get("sigla") or orgao.get("nome") if isinstance(orgao, dict) else ""
        )
        partes = [p for p in [descricao, _periodo(inicio, fim), nome_orgao] if p]
        rotulo = BASES.get(base, base.upper())
        formatados.append(f"{rotulo}: " + " — ".join(partes) if partes else rotulo)
    return formatados


def _data(valor: object) -> str:
    texto = str(valor or "").strip()[:10]
    if len(texto) == 10 and texto[4] == "-":  # AAAA-MM-DD -> DD/MM/AAAA
        return f"{texto[8:10]}/{texto[5:7]}/{texto[0:4]}"
    return texto


def _periodo(inicio: str, fim: str) -> str:
    if inicio and fim:
        return f"{inicio} a {fim}"
    if inicio:
        return f"desde {inicio}"
    return ""
