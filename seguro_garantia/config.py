"""Carregamento e normalização dos parâmetros da aplicação.

Os parâmetros vêm, nesta ordem de precedência:
1. argumentos de linha de comando (CLI) ou campos da interface (Streamlit);
2. variáveis de ambiente / arquivo `.env`;
3. valores padrão definidos abaixo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


# Palavras-chave padrão: exigência de garantia contratual / aditivos de prorrogação.
# Inclui os dispositivos legais (Lei 14.133/2021) citados em editais/contratos.
PALAVRAS_CHAVE_GARANTIA_PADRAO = [
    "seguro garantia",
    "fiança bancária",
    "garantia contratual",
    "caução",
    "cláusula de garantia",
    "retomada",
    "step-in",
    "aditivo de prorrogação",
    "termo aditivo",
    "art. 96",
    "art. 98",
    "art. 102",
]

# Modalidades de contratação do PNCP usadas na busca de editais.
MODALIDADES_PADRAO = [4, 5, 6, 7, 8, 9]

# Ramos que costumam exigir garantia de execução (obras, engenharia, construção,
# limpeza, conservação, manutenção predial, segurança etc.). O filtro compara
# estas palavras com o objeto do contrato/edital. Comparação sem acento e
# sem diferenciar maiúsculas/minúsculas.
PALAVRAS_CHAVE_RAMO_PADRAO = [
    "obra",
    "obras",
    "engenharia",
    "construcao",
    "construção",
    "edificacao",
    "edificação",
    "reforma",
    "pavimentacao",
    "pavimentação",
    "pavimentar",
    "recapeamento",
    "asfaltamento",
    "saneamento",
    "infraestrutura",
    "terraplenagem",
    "drenagem",
    "urbanizacao",
    "urbanização",
    "restauracao",
    "restauração",
    "demolicao",
    "demolição",
    "alvenaria",
    "pintura",
    "instalacoes",
    "instalações",
    "fundacoes",
    "fundações",
    "limpeza",
    "conservacao",
    "conservação",
    "manutencao",
    "manutenção",
    "servicos prediais",
    "serviços prediais",
    "vigilancia",
    "vigilância",
    "seguranca patrimonial",
    "segurança patrimonial",
    "gerenciamento de obras",
    "fiscalizacao de obras",
    "projetos de engenharia",
    "eletrica",
    "elétrica",
    "hidraulica",
    "hidráulica",
    "climatizacao",
    "climatização",
    "sinalizacao",
    "sinalização",
    "iluminacao publica",
    "iluminação pública",
    "esgotamento",
    "tubulacao",
    "tubulação",
]

# Prefixos de CNAE (divisão) típicos desses ramos — usados no filtro opcional por
# atividade da empresa, aplicado após o enriquecimento de CNPJ.
CNAE_ALVO_PADRAO = [
    "41",  # construção de edifícios
    "42",  # obras de infraestrutura
    "43",  # serviços especializados para construção
    "33",  # manutenção e reparação de máquinas e equipamentos
    "38",  # coleta, tratamento e disposição de resíduos
    "39",  # descontaminação e outros serviços de gestão de resíduos
    "71",  # serviços de arquitetura e engenharia
    "80",  # atividades de vigilância, segurança e investigação
    "81",  # serviços para edifícios e atividades paisagísticas (limpeza)
]


def _bool(valor: str | bool | None, padrao: bool = False) -> bool:
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in {"1", "true", "sim", "yes", "on", "verdadeiro"}


def _lista_palavras(valor: str | Iterable[str] | None) -> list[str]:
    if valor is None:
        return list(PALAVRAS_CHAVE_GARANTIA_PADRAO)
    if not isinstance(valor, str):
        return [str(v).strip().lower() for v in valor if str(v).strip()]
    itens = [p.strip().lower() for p in valor.replace("\n", "|").split("|")]
    return [p for p in itens if p]


def _lista_ufs(valor: str | Iterable[str] | None) -> list[str]:
    if valor is None:
        return []
    if not isinstance(valor, str):
        return [str(v).strip().upper() for v in valor if str(v).strip()]
    return [u.strip().upper() for u in valor.replace(";", ",").split(",") if u.strip()]


def _lista_int(valor: str | Iterable[int] | None, padrao: list[int]) -> list[int]:
    if valor is None or valor == "":
        return list(padrao)
    if not isinstance(valor, str):
        return [int(v) for v in valor]
    return [int(v.strip()) for v in valor.replace(";", ",").split(",") if v.strip()]


def _lista_str(valor: str | Iterable[str] | None, padrao: list[str]) -> list[str]:
    """Lista de textos separados por vírgula, ponto-e-vírgula, barra ou quebra."""
    if valor is None or valor == "":
        return list(padrao)
    if not isinstance(valor, str):
        return [str(v).strip() for v in valor if str(v).strip()]
    separado = valor.replace("\n", ",").replace(";", ",").replace("|", ",")
    return [p.strip() for p in separado.split(",") if p.strip()]


def _data(valor: str | None) -> date:
    if not valor:
        return date.today()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(valor.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"DATA_REFERENCIA inválida: {valor!r}. Use DD/MM/AAAA.")


@dataclass
class Config:
    """Todos os parâmetros de execução da aplicação."""

    # Janela de busca (N dias corridos, incluindo a data de referência)
    dias_retroativos: int = 30
    data_referencia: date = field(default_factory=date.today)
    data_inicial: date = field(init=False)
    data_final: date = field(init=False)

    # Filtro de garantia
    palavras_chave_garantia: list[str] = field(
        default_factory=lambda: list(PALAVRAS_CHAVE_GARANTIA_PADRAO)
    )
    filtro_garantia_estrito: bool = False

    # Filtro por ramo de atividade (obras, engenharia, limpeza, etc.)
    filtrar_por_ramo: bool = True
    ramos_palavras_chave: list[str] = field(
        default_factory=lambda: list(PALAVRAS_CHAVE_RAMO_PADRAO)
    )
    filtrar_por_cnae: bool = False
    cnae_alvo: list[str] = field(default_factory=lambda: list(CNAE_ALVO_PADRAO))

    # Valores
    valor_minimo: float = 0.0
    percentual_garantia: float = 0.05

    # Escopo geográfico e modalidades
    ufs: list[str] = field(default_factory=list)
    modalidades: list[int] = field(default_factory=lambda: list(MODALIDADES_PADRAO))
    buscar_editais: bool = True
    incluir_editais_sem_vencedor: bool = False

    # Links de documentos (edital, ata, resultado, contrato) no PNCP.
    coletar_links_documentos: bool = True
    links_max_registros: int = 50

    # Fontes complementares
    usar_compras_gov: bool = False
    compras_gov_orgaos: list[str] = field(default_factory=list)
    # Portais de bancos públicos / economia mista (estrutura — ver sources/bancos.py)
    usar_licitacoes_e: bool = False   # Banco do Brasil
    usar_caixa: bool = False          # Caixa Econômica Federal
    usar_bndes: bool = False
    usar_petronect: bool = False      # Petrobras
    # Portais estaduais / municipais (estrutura — ver sources/estaduais.py)
    usar_enegocios_sp: bool = False   # e-Negócios Imprensa Oficial SP (implementado)
    enegocios_max_cnpjs: int = 50
    enegocios_detalhes: bool = False
    enegocios_cnpjs: list[str] = field(default_factory=list)
    usar_bec_sp: bool = False
    usar_compras_rs: bool = False
    usar_compras_publicas: bool = False
    usar_bll_compras: bool = False

    # PDF / garantia no texto
    ler_anexos_pdf: bool = False
    ler_pdf_max_registros: int = 30
    exigir_garantia_no_texto: bool = False

    # Enriquecimento
    enriquecer_cnpj: bool = True
    usar_receitaws: bool = False
    enriquecer_web: bool = True
    web_max_empresas: int = 0  # 0 = sem limite
    pausa_web: float = 5.0
    pausa_cnpj: float = 0.5  # pausa entre consultas de CNPJ (APIs aguentam menor)
    max_workers: int = 6  # paralelismo (threads) no enriquecimento

    # Sanções públicas (CEIS/CNEP) — exige chave gratuita do Portal da Transparência
    enriquecer_sancoes: bool = True
    transparencia_api_key: str = ""
    pausa_sancoes: float = 0.3

    # Desempenho / resiliência
    pausa_entre_requisicoes: float = 3.0
    max_paginas: int = 200
    tamanho_pagina: int = 50
    timeout: int = 30
    max_tentativas: int = 3

    # Saída
    diretorio_saida: Path = field(default_factory=lambda: Path("./saida"))
    nome_arquivo: str = "prospeccao_seguro_garantia"
    gerar_csv: bool = True
    incluir_aba_parametros: bool = True
    registrar_ultima_execucao: bool = True

    # Diretórios de cache
    diretorio_cache_cnpj: Path = field(default_factory=lambda: Path("./.cache_cnpj"))
    diretorio_cache_web: Path = field(default_factory=lambda: Path("./.cache_web"))
    diretorio_cache_sancoes: Path = field(
        default_factory=lambda: Path("./.cache_sancoes")
    )

    # Execução
    verboso: bool = False
    limite: int | None = None  # teto de registros finais (útil p/ testes)

    def __post_init__(self) -> None:
        from datetime import timedelta

        if self.dias_retroativos < 0:
            self.dias_retroativos = 0
        self.data_final = self.data_referencia
        # A janela é inclusiva nas duas pontas: 30 dias = hoje + 29 anteriores.
        if self.dias_retroativos <= 1:
            self.data_inicial = self.data_referencia
        else:
            self.data_inicial = self.data_referencia - timedelta(
                days=self.dias_retroativos - 1
            )
        # Recalcula data_final caso data_referencia tenha sido passada sem __post_init__
        if self.data_final < self.data_inicial:
            self.data_final = self.data_inicial
        self.diretorio_saida = Path(self.diretorio_saida).expanduser()
        self.diretorio_cache_cnpj = Path(self.diretorio_cache_cnpj).expanduser()
        self.diretorio_cache_web = Path(self.diretorio_cache_web).expanduser()
        self.diretorio_cache_sancoes = Path(self.diretorio_cache_sancoes).expanduser()
        # Exigir garantia no texto implica ler os anexos (senão não há texto).
        if self.exigir_garantia_no_texto:
            self.ler_anexos_pdf = True
        if self.max_workers < 1:
            self.max_workers = 1
        if self.links_max_registros < 0:
            self.links_max_registros = 0

    # ---------------------------------------------------------------- helpers
    def datas_pncp(self) -> tuple[str, str]:
        """Retorna (dataInicial, dataFinal) no formato AAAAMMDD esperado pelo PNCP."""
        return self.data_inicial.strftime("%Y%m%d"), self.data_final.strftime("%Y%m%d")

    def dentro_da_janela(self, valor: object) -> bool | None:
        """Diz se uma data está na janela inclusiva (None = não interpretada)."""
        from .validacao import dentro_janela

        return dentro_janela(valor, self.data_inicial, self.data_final)

    def resumo(self) -> dict[str, object]:
        """Dicionário com os parâmetros para a aba `Parametros` / logs."""
        return {
            "Janela (dias)": self.dias_retroativos,
            "Data inicial": self.data_inicial.strftime("%d/%m/%Y"),
            "Data final": self.data_referencia.strftime("%d/%m/%Y"),
            "Valor mínimo (R$)": self.valor_minimo,
            "Percentual garantia": self.percentual_garantia,
            "UFs": ", ".join(self.ufs) if self.ufs else "Brasil inteiro",
            "Modalidades (editais)": ", ".join(map(str, self.modalidades)),
            "Buscar editais": self.buscar_editais,
            "Incluir editais sem vencedor": self.incluir_editais_sem_vencedor,
            "Coletar links de documentos": self.coletar_links_documentos,
            "Máx. registros com links": self.links_max_registros,
            "Registrar última execução": self.registrar_ultima_execucao,
            "Compras.gov.br": self.usar_compras_gov,
            "Licitações-E (BB)": self.usar_licitacoes_e,
            "CAIXA": self.usar_caixa,
            "BNDES": self.usar_bndes,
            "Petronect": self.usar_petronect,
            "e-Negócios SP": self.usar_enegocios_sp,
            "BEC/SP": self.usar_bec_sp,
            "ComprasRS": self.usar_compras_rs,
            "Compras Públicas": self.usar_compras_publicas,
            "BLL Compras": self.usar_bll_compras,
            "Ler PDF dos anexos": self.ler_anexos_pdf,
            "Exigir garantia no texto": self.exigir_garantia_no_texto,
            "Filtro de garantia estrito": self.filtro_garantia_estrito,
            "Filtrar por ramo": self.filtrar_por_ramo,
            "Ramos (palavras)": "; ".join(self.ramos_palavras_chave),
            "Filtrar por CNAE": self.filtrar_por_cnae,
            "CNAE alvo": ", ".join(self.cnae_alvo),
            "Enriquecer CNPJ": self.enriquecer_cnpj,
            "ReceitaWS (fallback)": self.usar_receitaws,
            "Enriquecer web": self.enriquecer_web,
            "Web (máx. empresas)": self.web_max_empresas or "sem limite",
            "Consultar sanções (CEIS/CNEP)": (
                "sim" if (self.enriquecer_sancoes and self.transparencia_api_key) else "não"
            ),
            "Paralelismo (threads)": self.max_workers,
            "Palavras-chave garantia": "; ".join(self.palavras_chave_garantia),
        }


def carregar_config(
    env_file: str | os.PathLike | None = None,
    **overrides: object,
) -> Config:
    """Monta a `Config` a partir do `.env` e de overrides (CLI/Streamlit)."""
    load_dotenv(dotenv_path=env_file, override=False)

    env = os.environ
    config = Config(
        dias_retroativos=int(env.get("DIAS_RETROATIVOS", 30) or 30),
        data_referencia=_data(env.get("DATA_REFERENCIA")),
        palavras_chave_garantia=_lista_palavras(env.get("PALAVRAS_CHAVE_GARANTIA")),
        filtro_garantia_estrito=_bool(env.get("FILTRO_GARANTIA_ESTRITO"), False),
        filtrar_por_ramo=_bool(env.get("FILTRAR_POR_RAMO"), True),
        ramos_palavras_chave=_lista_str(
            env.get("RAMOS_PALAVRAS_CHAVE"), PALAVRAS_CHAVE_RAMO_PADRAO
        ),
        filtrar_por_cnae=_bool(env.get("FILTRAR_POR_CNAE"), False),
        cnae_alvo=_lista_str(env.get("CNAE_ALVO"), CNAE_ALVO_PADRAO),
        valor_minimo=float(env.get("VALOR_MINIMO", 0) or 0),
        percentual_garantia=float(env.get("PERCENTUAL_GARANTIA", 0.05) or 0.05),
        ufs=_lista_ufs(env.get("UFS")),
        modalidades=_lista_int(env.get("MODALIDADES"), MODALIDADES_PADRAO),
        buscar_editais=_bool(env.get("BUSCAR_EDITAIS"), True),
        incluir_editais_sem_vencedor=_bool(env.get("INCLUIR_EDITAIS_SEM_VENCEDOR"), False),
        coletar_links_documentos=_bool(env.get("COLETAR_LINKS_DOCUMENTOS"), True),
        links_max_registros=int(env.get("LINKS_MAX_REGISTROS", 50) or 50),
        usar_compras_gov=_bool(env.get("USAR_COMPRAS_GOV"), False),
        compras_gov_orgaos=[
            c.strip() for c in (env.get("COMPRAS_GOV_ORGAOS", "") or "").split(",") if c.strip()
        ],
        usar_licitacoes_e=_bool(env.get("USAR_LICITACOES_E"), False),
        usar_caixa=_bool(env.get("USAR_CAIXA"), False),
        usar_bndes=_bool(env.get("USAR_BNDES"), False),
        usar_petronect=_bool(env.get("USAR_PETRONECT"), False),
        usar_enegocios_sp=_bool(env.get("USAR_ENEGOCIOS_SP"), False),
        enegocios_max_cnpjs=int(env.get("ENEGOCIOS_MAX_CNPJS", 50) or 50),
        enegocios_detalhes=_bool(env.get("ENEGOCIOS_DETALHES"), False),
        enegocios_cnpjs=_lista_str(env.get("ENEGOCIOS_CNPJS"), []),
        usar_bec_sp=_bool(env.get("USAR_BEC_SP"), False),
        usar_compras_rs=_bool(env.get("USAR_COMPRAS_RS"), False),
        usar_compras_publicas=_bool(env.get("USAR_COMPRAS_PUBLICAS"), False),
        usar_bll_compras=_bool(env.get("USAR_BLL_COMPRAS"), False),
        ler_anexos_pdf=_bool(env.get("LER_ANEXOS_PDF"), False),
        ler_pdf_max_registros=int(env.get("LER_PDF_MAX_REGISTROS", 30) or 30),
        exigir_garantia_no_texto=_bool(env.get("EXIGIR_GARANTIA_NO_TEXTO"), False),
        enriquecer_cnpj=_bool(env.get("ENRIQUECER_CNPJ"), True),
        usar_receitaws=_bool(env.get("USAR_RECEITAWS"), False),
        enriquecer_web=_bool(env.get("ENRIQUECER_WEB"), True),
        web_max_empresas=int(env.get("WEB_MAX_EMPRESAS", 0) or 0),
        pausa_web=float(env.get("PAUSA_WEB", 5) or 5),
        pausa_cnpj=float(env.get("PAUSA_CNPJ", 0.5) or 0),
        max_workers=int(env.get("MAX_WORKERS", 6) or 6),
        enriquecer_sancoes=_bool(env.get("ENRIQUECER_SANCOES"), True),
        transparencia_api_key=(env.get("TRANSPARENCIA_API_KEY", "") or "").strip(),
        pausa_sancoes=float(env.get("PAUSA_SANCOES", 0.3) or 0.3),
        pausa_entre_requisicoes=float(env.get("PAUSA_ENTRE_REQUISICOES", 3) or 3),
        max_paginas=int(env.get("MAX_PAGINAS", 200) or 200),
        tamanho_pagina=int(env.get("TAMANHO_PAGINA", 50) or 50),
        timeout=int(env.get("TIMEOUT", 30) or 30),
        max_tentativas=int(env.get("MAX_TENTATIVAS", 3) or 3),
        diretorio_saida=Path(env.get("DIRETORIO_SAIDA", "./saida") or "./saida"),
        nome_arquivo=env.get("NOME_ARQUIVO", "prospeccao_seguro_garantia")
        or "prospeccao_seguro_garantia",
        gerar_csv=_bool(env.get("GERAR_CSV"), True),
        incluir_aba_parametros=_bool(env.get("INCLUIR_ABA_PARAMETROS"), True),
        registrar_ultima_execucao=_bool(env.get("REGISTRAR_ULTIMA_EXECUCAO"), True),
    )

    overrides = {k: v for k, v in overrides.items() if v is not None}
    if overrides:
        # Aplicação manual (em vez de dataclasses.replace) para funcionar igual
        # em todas as versões do Python, inclusive a 3.14 do Streamlit Cloud.
        validos = {f.name for f in fields(Config) if f.init}
        invalidos = sorted(set(overrides) - validos)
        if invalidos:
            raise TypeError(
                "Parâmetro(s) inválido(s) para Config: " + ", ".join(invalidos)
            )
        for chave, valor in overrides.items():
            setattr(config, chave, valor)
        # Reaplica a janela, pois data de referência/dias podem ter mudado.
        config.__post_init__()

    config.diretorio_saida.mkdir(parents=True, exist_ok=True)
    return config
