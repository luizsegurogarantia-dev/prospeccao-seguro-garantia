"""Enriquecimento cadastral a partir do CNPJ.

Fontes públicas gratuitas, consultadas nesta ordem:
1. BrasilAPI   -> https://brasilapi.com.br/api/cnpj/v1/{cnpj}
2. cnpj.ws     -> https://publica.cnpj.ws/cnpj/{cnpj}
3. ReceitaWS   -> https://receitaws.com.br/v1/cnpj/{cnpj} (fallback opcional)

Extrai razão social, situação cadastral, CNAE, endereço, telefone(s), e-mail
institucional e o QSA (sócios/administradores) para abordagem comercial.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from ..config import Config
from ..http_client import ClienteHTTP
from ..models import DadosCNPJ

log = logging.getLogger("seguro_garantia.cnpj")

Progresso = Callable[[str, int, int], None]

# Ordem de prioridade para escolher os decisores dentro do QSA.
PRIORIDADE_QUALIFICACAO = (
    "presidente",
    "diretor",
    "administrador",
    "sócio-administrador",
    "socio-administrador",
    "sócio",
    "socio",
    "titular",
    "gerente",
    "procurador",
)


class EnriquecendorCNPJ:
    def __init__(self, http: ClienteHTTP, config: Config) -> None:
        self.http = http
        self.config = config
        self.diretorio_cache: Path = config.diretorio_cache_cnpj
        self.diretorio_cache.mkdir(parents=True, exist_ok=True)
        self.consultas_rede = 0

    # ------------------------------------------------------------------ API
    def enriquecer(self, cnpj: str) -> DadosCNPJ:
        cnpj = _limpar_cnpj(cnpj)
        if len(cnpj) != 14:
            return DadosCNPJ(cnpj=cnpj, situacao="CNPJ inválido")

        cache = self._ler_cache(cnpj)
        if cache is not None:
            return cache

        dados = (
            self._consultar_brasilapi(cnpj)
            or self._consultar_cnpjws(cnpj)
            or (self._consultar_receitaws(cnpj) if self.config.usar_receitaws else None)
        )
        if dados is None:
            # Não grava no cache: pode ser indisponibilidade temporária da API.
            return DadosCNPJ(cnpj=cnpj, situacao="Não localizado")

        self._gravar_cache(cnpj, dados)
        return dados

    def enriquecer_lote(
        self,
        cnpjs: list[str],
        progresso: Progresso | None = None,
        max_workers: int = 1,
    ) -> dict[str, DadosCNPJ]:
        resultado: dict[str, DadosCNPJ] = {}
        unicos = sorted({_limpar_cnpj(c) for c in cnpjs if c})
        total = len(unicos)

        if max_workers and max_workers > 1 and total > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futuros = {pool.submit(self.enriquecer, c): c for c in unicos}
                for i, futuro in enumerate(as_completed(futuros), start=1):
                    cnpj = futuros[futuro]
                    try:
                        dados = futuro.result()
                    except Exception as exc:  # nunca derruba o lote
                        log.debug("falha ao enriquecer %s: %s", cnpj, exc)
                        dados = DadosCNPJ(cnpj=cnpj, situacao="Erro na consulta")
                    resultado.setdefault(cnpj, dados)
                    self._reportar(progresso, i, total, dados, cnpj)
            return resultado

        for i, cnpj in enumerate(unicos, start=1):
            dados = self.enriquecer(cnpj)
            resultado[cnpj] = dados
            self._reportar(progresso, i, total, dados, cnpj)
            self.http.dormir(self.config.pausa_cnpj)
        return resultado

    def _reportar(
        self,
        progresso: Progresso | None,
        i: int,
        total: int,
        dados: DadosCNPJ,
        cnpj: str,
    ) -> None:
        etiqueta = dados.razao_social or dados.situacao or cnpj
        mensagem = f"Enriquecendo CNPJ {i}/{total}: {etiqueta}"
        if progresso:
            progresso(mensagem, i, total)
        elif self.config.verboso:
            log.info(mensagem)

    def _consultar_brasilapi(self, cnpj: str) -> DadosCNPJ | None:
        self.consultas_rede += 1
        payload = self.http.get(
            f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
            permitir_404=True,
        )
        if not isinstance(payload, dict):
            return None
        return self._normalizar_brasilapi(payload)

    def _consultar_cnpjws(self, cnpj: str) -> DadosCNPJ | None:
        self.consultas_rede += 1
        payload = self.http.get(f"https://publica.cnpj.ws/cnpj/{cnpj}")
        if not isinstance(payload, dict) or "estabelecimento" not in payload:
            return None
        return self._normalizar_cnpjws(payload)

    def _consultar_receitaws(self, cnpj: str) -> DadosCNPJ | None:
        self.consultas_rede += 1
        payload = self.http.get(f"https://receitaws.com.br/v1/cnpj/{cnpj}")
        if not isinstance(payload, dict) or payload.get("status") == "ERROR":
            return None
        return self._normalizar_receitaws(payload)

    # ------------------------------------------------------- normalização
    @staticmethod
    def _normalizar_brasilapi(d: dict) -> DadosCNPJ:
        return DadosCNPJ(
            cnpj=d.get("cnpj", ""),
            razao_social=d.get("razao_social", "") or "",
            nome_fantasia=d.get("nome_fantasia", "") or "",
            situacao=d.get("descricao_situacao_cadastral", "") or "",
            cnae_principal=_formatar_cnae(d.get("cnae_fiscal"), d.get("cnae_fiscal_descricao")),
            endereco=_montar_endereco(d),
            cidade=d.get("municipio", "") or "",
            uf=d.get("uf", "") or "",
            telefone_1=_telefone(d.get("ddd_telefone_1")),
            telefone_2=_telefone(d.get("ddd_telefone_2")),
            email=(d.get("email") or "").lower(),
            socios=_extrair_socios(d.get("qsa") or []),
            fonte="BrasilAPI",
        )

    @staticmethod
    def _normalizar_receitaws(d: dict) -> DadosCNPJ:
        atividades = d.get("atividade_principal") or [{}]
        return DadosCNPJ(
            cnpj=_limpar_cnpj(d.get("cnpj", "")),
            razao_social=d.get("nome", "") or "",
            nome_fantasia=d.get("fantasia", "") or "",
            situacao=d.get("situacao", "") or "",
            cnae_principal=_formatar_cnae(
                atividades[0].get("code"), atividades[0].get("text")
            ),
            endereco=_montar_endereco(
                {
                    "descricao_tipo_de_logradouro": "",
                    "logradouro": d.get("logradouro", ""),
                    "numero": d.get("numero", ""),
                    "complemento": d.get("complemento", ""),
                    "bairro": d.get("bairro", ""),
                    "cep": _limpar_cep(d.get("cep", "")),
                }
            ),
            cidade=d.get("municipio", "") or "",
            uf=d.get("uf", "") or "",
            telefone_1=_telefone(d.get("telefone", "")),
            telefone_2="",
            email=(d.get("email") or "").lower(),
            socios=_extrair_socios(d.get("qsa") or []),
            fonte="ReceitaWS",
        )

    @staticmethod
    def _normalizar_cnpjws(d: dict) -> DadosCNPJ:
        est = d.get("estabelecimento") or {}
        atividade = est.get("atividade_principal") or {}
        cnae = atividade.get("subclasse")
        descricao = atividade.get("descricao")
        tel1 = _telefone(
            f"{est.get('ddd1') or ''}{est.get('telefone1') or ''}".strip()
        )
        tel2 = _telefone(
            f"{est.get('ddd2') or ''}{est.get('telefone2') or ''}".strip()
        )
        endereco = _montar_endereco(
            {
                "descricao_tipo_de_logradouro": est.get("tipo_logradouro", ""),
                "logradouro": est.get("logradouro", ""),
                "numero": est.get("numero", ""),
                "complemento": est.get("complemento", ""),
                "bairro": est.get("bairro", ""),
                "cep": est.get("cep", ""),
            }
        )
        return DadosCNPJ(
            cnpj=_limpar_cnpj(est.get("cnpj", "")),
            razao_social=d.get("razao_social", "") or "",
            nome_fantasia=(est.get("nome_fantasia") or "").strip(),
            situacao=est.get("situacao_cadastral", "") or "",
            cnae_principal=_formatar_cnae(cnae, descricao),
            endereco=endereco,
            cidade=(est.get("cidade") or {}).get("nome", "") or "",
            uf=(est.get("estado") or {}).get("sigla", "") or "",
            telefone_1=tel1,
            telefone_2=tel2,
            email=(est.get("email") or "").lower(),
            socios=_extrair_socios(d.get("socios") or []),
            fonte="cnpj.ws",
        )

    # ------------------------------------------------------------- cache
    def _caminho_cache(self, cnpj: str) -> Path:
        return self.diretorio_cache / f"{cnpj}.json"

    def _ler_cache(self, cnpj: str) -> DadosCNPJ | None:
        caminho = self._caminho_cache(cnpj)
        if not caminho.exists():
            return None
        try:
            d = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(d, dict) or "razao_social" not in d:
            return None
        return DadosCNPJ(
            cnpj=d.get("cnpj", cnpj),
            razao_social=d.get("razao_social", ""),
            nome_fantasia=d.get("nome_fantasia", ""),
            situacao=d.get("situacao", ""),
            cnae_principal=d.get("cnae_principal", ""),
            endereco=d.get("endereco", ""),
            cidade=d.get("cidade", ""),
            uf=d.get("uf", ""),
            telefone_1=d.get("telefone_1", ""),
            telefone_2=d.get("telefone_2", ""),
            email=d.get("email", ""),
            socios=list(d.get("socios") or []),
            site=d.get("site", ""),
            fonte=d.get("fonte", "cache"),
        )

    def _gravar_cache(self, cnpj: str, dados: DadosCNPJ) -> None:
        try:
            self._caminho_cache(cnpj).write_text(
                json.dumps(dados.__dict__, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass


# ------------------------------------------------------------- utilitários
def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", str(cnpj or ""))


def _limpar_cep(cep: str) -> str:
    return re.sub(r"\D", "", str(cep or ""))


def _telefone(valor: str | None) -> str:
    return re.sub(r"[^\d+ ]", "", str(valor or "")).strip()


def _formatar_cnae(codigo: object, descricao: object) -> str:
    if not codigo and not descricao:
        return ""
    return f"{codigo} - {descricao}" if descricao else str(codigo)


def _montar_endereco(d: dict) -> str:
    tipo = (d.get("descricao_tipo_de_logradouro") or "").strip()
    partes = [
        " ".join(p for p in [tipo, (d.get("logradouro") or "").strip()] if p),
        (d.get("numero") or "").strip(),
        (d.get("complemento") or "").strip(),
        (d.get("bairro") or "").strip(),
        (d.get("cep") or "").strip(),
    ]
    return ", ".join(p for p in partes if p)


def _extrair_socios(qsa: list[dict]) -> list[str]:
    """Ordena o QSA por poder de decisão e devolve nomes com a qualificação."""
    itens = []
    for socio in qsa:
        nome = (socio.get("nome_socio") or socio.get("nome") or "").strip()
        if not nome or nome.upper().startswith("***"):
            continue
        qualificacao = socio.get("qualificacao_socio") or socio.get("qual") or ""
        if isinstance(qualificacao, dict):  # formato do cnpj.ws
            qualificacao = qualificacao.get("descricao", "")
        qualificacao = str(qualificacao).strip()
        itens.append((_peso_qualificacao(qualificacao), nome, qualificacao))

    itens.sort(key=lambda x: x[0])
    nomes = []
    for _, nome, qualificacao in itens[:4]:
        nomes.append(f"{nome} ({qualificacao})" if qualificacao else nome)
    return nomes


def _peso_qualificacao(qualificacao: str) -> int:
    q = qualificacao.lower()
    for peso, termo in enumerate(PRIORIDADE_QUALIFICACAO):
        if termo in q:
            return peso
    return len(PRIORIDADE_QUALIFICACAO) + 1
