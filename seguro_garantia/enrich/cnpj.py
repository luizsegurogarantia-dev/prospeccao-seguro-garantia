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
from dataclasses import asdict, fields
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from ..config import Config
from ..http_client import ClienteHTTP
from ..models import DadosCNPJ

log = logging.getLogger("seguro_garantia.cnpj")

Progresso = Callable[[str, int, int], None]

# Muda quando o conjunto de campos extraídos muda, para invalidar caches antigos.
VERSAO_CACHE_CNPJ = 2

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
            situacao=_formatar_situacao(d.get("descricao_situacao_cadastral")),
            situacao_data=_formatar_data(d.get("data_situacao_cadastral")),
            cnae_principal=_formatar_cnae(d.get("cnae_fiscal"), d.get("cnae_fiscal_descricao")),
            cnaes_secundarios=_extrair_cnaes_secundarios(d.get("cnaes_secundarios")),
            natureza_juridica=d.get("natureza_juridica", "") or "",
            porte=_formatar_porte(d.get("porte")),
            capital_social=_numero(d.get("capital_social")),
            data_abertura=_formatar_data(d.get("data_inicio_atividade")),
            idade_anos=_idade_anos(d.get("data_inicio_atividade")),
            simples=_sim_nao(d.get("opcao_pelo_simples")),
            mei=_sim_nao(d.get("opcao_pelo_mei")),
            matriz_filial=d.get("descricao_identificador_matriz_filial", "") or "",
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
            situacao=_formatar_situacao(d.get("situacao")),
            situacao_data=_formatar_data(d.get("data_situacao")),
            cnae_principal=_formatar_cnae(
                atividades[0].get("code"), atividades[0].get("text")
            ),
            cnaes_secundarios=_extrair_cnaes_secundarios(d.get("atividades_secundarias")),
            natureza_juridica=d.get("natureza_juridica", "") or "",
            porte=_formatar_porte(d.get("porte")),
            capital_social=_numero(d.get("capital_social")),
            data_abertura=_formatar_data(d.get("abertura")),
            idade_anos=_idade_anos(d.get("abertura")),
            simples=_sim_nao(d.get("simples")),
            mei=_sim_nao(d.get("mei")),
            matriz_filial=d.get("tipo", "") or "",
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
        natureza = d.get("natureza_juridica") or {}
        if isinstance(natureza, dict):
            natureza = natureza.get("descricao", "")
        simples = d.get("simples") or {}
        mei = d.get("mei") or {}
        return DadosCNPJ(
            cnpj=_limpar_cnpj(est.get("cnpj", "")),
            razao_social=d.get("razao_social", "") or "",
            nome_fantasia=(est.get("nome_fantasia") or "").strip(),
            situacao=_formatar_situacao(est.get("situacao_cadastral")),
            situacao_data=_formatar_data(est.get("data_situacao_cadastral")),
            cnae_principal=_formatar_cnae(cnae, descricao),
            cnaes_secundarios=_extrair_cnaes_secundarios(
                est.get("atividades_secundarias")
            ),
            natureza_juridica=str(natureza or ""),
            porte=_formatar_porte(d.get("porte")),
            capital_social=_numero(d.get("capital_social")),
            data_abertura=_formatar_data(est.get("data_inicio_atividade")),
            idade_anos=_idade_anos(est.get("data_inicio_atividade")),
            simples=_sim_nao(simples.get("data_opcao") if isinstance(simples, dict) else simples),
            mei=_sim_nao(mei.get("data_opcao") if isinstance(mei, dict) else mei),
            matriz_filial=est.get("tipo", "") or "",
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
        # Cache antigo (sem o dossiê completo) é descartado e consultado de novo.
        if d.get("_versao") != VERSAO_CACHE_CNPJ:
            return None
        validos = {f.name for f in fields(DadosCNPJ)}
        dados = {k: v for k, v in d.items() if k in validos}
        dados["cnpj"] = dados.get("cnpj") or cnpj
        try:
            return DadosCNPJ(**dados)
        except TypeError:
            return None

    def _gravar_cache(self, cnpj: str, dados: DadosCNPJ) -> None:
        payload = asdict(dados)
        payload["_versao"] = VERSAO_CACHE_CNPJ
        try:
            self._caminho_cache(cnpj).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
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


def _extrair_socios(qsa: list[dict], limite: int = 12) -> list[str]:
    """Ordena o QSA por poder de decisão e devolve nome, qualificação e entrada."""
    itens = []
    for socio in qsa:
        nome = (socio.get("nome_socio") or socio.get("nome") or "").strip()
        if not nome or nome.upper().startswith("***"):
            continue
        qualificacao = socio.get("qualificacao_socio") or socio.get("qual") or ""
        if isinstance(qualificacao, dict):  # formato do cnpj.ws
            qualificacao = qualificacao.get("descricao", "")
        qualificacao = str(qualificacao).strip()
        entrada = _formatar_data(
            socio.get("data_entrada_sociedade")
            or socio.get("data_entrada")
            or ""
        )
        itens.append((_peso_qualificacao(qualificacao), nome, qualificacao, entrada))

    itens.sort(key=lambda x: x[0])
    nomes = []
    for _, nome, qualificacao, entrada in itens[:limite]:
        detalhe = ", ".join(p for p in [qualificacao, f"desde {entrada}" if entrada else ""] if p)
        nomes.append(f"{nome} ({detalhe})" if detalhe else nome)
    return nomes


def _extrair_cnaes_secundarios(lista: object) -> list[str]:
    """Normaliza a lista de CNAEs secundários para 'codigo - descricao'."""
    if not isinstance(lista, list):
        return []
    itens: list[str] = []
    for item in lista[:8]:
        if not isinstance(item, dict):
            continue
        codigo = item.get("codigo") or item.get("code") or item.get("subclasse")
        descricao = item.get("descricao") or item.get("text")
        formatado = _formatar_cnae(codigo, descricao)
        if formatado and formatado not in itens:
            itens.append(formatado)
    return itens


def _numero(valor: object) -> float:
    """Converte '1.000,50', '1000.50' ou 1000 em float."""
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if "," in texto:  # formato brasileiro
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _sim_nao(valor: object) -> str:
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    texto = str(valor).strip().lower()
    if texto in {"true", "sim", "s", "1", "yes"}:
        return "Sim"
    if texto in {"false", "nao", "não", "n", "0", "no"}:
        return "Não"
    return "Sim"  # data de opção preenchida = optante


def _formatar_porte(valor: object) -> str:
    """Converte os rótulos em caixa alta das APIs para leitura humana."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    mapa = {
        "DEMAIS": "Demais",
        "MEI": "MEI",
        "MICRO EMPRESA": "Microempresa",
        "EMPRESA DE PEQUENO PORTE": "EPP",
    }
    return mapa.get(texto.upper(), texto.title())


def _formatar_situacao(valor: object) -> str:
    texto = str(valor or "").strip()
    return texto.capitalize() if texto else ""


def _formatar_data(valor: object) -> str:
    """Aceita ISO (2020-01-31) ou DD/MM/AAAA e devolve DD/MM/AAAA."""
    if not valor:
        return ""
    texto = str(valor).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return ""


def _idade_anos(valor: object) -> int | None:
    data = _formatar_data(valor)
    if not data:
        return None
    try:
        abertura = datetime.strptime(data, "%d/%m/%Y").date()
    except ValueError:
        return None
    hoje = date.today()
    return hoje.year - abertura.year - ((hoje.month, hoje.day) < (abertura.month, abertura.day))


def _peso_qualificacao(qualificacao: str) -> int:
    q = qualificacao.lower()
    for peso, termo in enumerate(PRIORIDADE_QUALIFICACAO):
        if termo in q:
            return peso
    return len(PRIORIDADE_QUALIFICACAO) + 1
