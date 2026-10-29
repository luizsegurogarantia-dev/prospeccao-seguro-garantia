"""Orquestração completa: coleta -> filtro -> enriquecimento -> exportação."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import Config
from .enrich.cnpj import EnriquecendorCNPJ
from .enrich.email import email_valido
from .enrich.web import EnriquecendorWeb
from .exporter import exportar, montar_dataframe
from .filters import calcular_valor_garantia, cnae_do_ramo, registro_tem_garantia
from .http_client import ClienteHTTP
from .models import DadosCNPJ, RegistroLicitacao, telefone_eh_celular
from .pdf_text import ler_pdf
from .sources import FonteBase, FonteENegociosSP, FontePNCP, montar_fontes

log = logging.getLogger("seguro_garantia.pipeline")

Progresso = Callable[[str, int, int], None]


@dataclass
class ResultadoExecucao:
    dataframe: pd.DataFrame
    arquivos: dict[str, Path]
    total_bruto: int
    total_final: int
    duracao_segundos: float


def executar(config: Config, progresso: Progresso | None = None) -> ResultadoExecucao:
    inicio = datetime.now()
    _configurar_log(config)

    def avisar(mensagem: str, atual: int = 0, total: int = 0) -> None:
        log.info(mensagem)
        if progresso:
            progresso(mensagem, atual, total)

    with ClienteHTTP(
        timeout=config.timeout,
        max_tentativas=config.max_tentativas,
        pausa_base=config.pausa_entre_requisicoes,
        verboso=config.verboso,
        aviso=avisar,
    ) as http:
        # 1) Coleta ---------------------------------------------------------
        avisar("Coletando dados das fontes públicas...")
        fonte_pncp = FontePNCP(http, config, progresso=avisar)
        fontes: list[FonteBase] = montar_fontes(config, http, progresso=avisar)

        registros: list[RegistroLicitacao] = []
        for fonte in fontes:
            try:
                registros.extend(fonte.coletar())
            except Exception as exc:  # uma fonte com erro não derruba o todo
                avisar(f"Falha na fonte {fonte.nome}: {exc}")

        # 1b) Fontes complementares que dependem dos CNPJs já coletados -------
        if config.usar_enegocios_sp:
            cnpjs_conhecidos = [
                r.cnpj_vencedor for r in registros if r.cnpj_vencedor
            ]
            if cnpjs_conhecidos or config.enegocios_cnpjs:
                fonte_eneg = FonteENegociosSP(http, config, progresso=avisar)
                try:
                    registros.extend(fonte_eneg.coletar(cnpjs_conhecidos))
                except Exception as exc:
                    avisar(f"Falha na fonte {fonte_eneg.nome}: {exc}")

        total_bruto = len(registros)
        registros = _deduplicar(registros)
        avisar(f"{total_bruto} registros brutos | {len(registros)} após deduplicação")

        # 2) Texto do edital (PDF) e filtro de garantia ---------------------
        if config.ler_anexos_pdf:
            _enriquecer_com_pdf(registros, fonte_pncp, http, config, avisar)

        if config.filtro_garantia_estrito or config.exigir_garantia_no_texto:
            antes = len(registros)
            registros = [
                r for r in registros
                if registro_tem_garantia(r, config.palavras_chave_garantia)
            ]
            avisar(
                f"Filtro de garantia (exigência no texto): "
                f"{antes} -> {len(registros)} registros"
            )

        if config.limite:
            registros = registros[: config.limite]

        # 3) Enriquecimento -------------------------------------------------
        cnpjs = [r.cnpj_vencedor for r in registros if r.cnpj_vencedor]
        dados_cnpj: dict[str, DadosCNPJ] = {}
        contatos_web: dict[str, Any] = {}

        if config.enriquecer_cnpj and cnpjs:
            avisar(f"Enriquecendo {len(set(cnpjs))} CNPJs (Receita Federal/BrasilAPI)...")
            enriq_cnpj = EnriquecendorCNPJ(http, config)
            dados_cnpj = enriq_cnpj.enriquecer_lote(
                cnpjs, progresso=avisar, max_workers=config.max_workers
            )

        if config.filtrar_por_cnae and dados_cnpj:
            antes = len(registros)
            registros = [
                r
                for r in registros
                if cnae_do_ramo(
                    (
                        dados_cnpj.get(r.cnpj_vencedor)
                        or DadosCNPJ(cnpj=r.cnpj_vencedor)
                    ).cnae_principal,
                    config.cnae_alvo,
                )
            ]
            avisar(f"Filtro por CNAE (ramo da empresa): {antes} -> {len(registros)} registros")

        if config.enriquecer_web and dados_cnpj:
            cnpjs_web = [r.cnpj_vencedor for r in registros if r.cnpj_vencedor]
            alvos = [
                (cnpj, dados_cnpj[cnpj])
                for cnpj in dict.fromkeys(cnpjs_web)
                if cnpj in dados_cnpj
            ]
            if config.web_max_empresas and config.web_max_empresas > 0:
                alvos = alvos[: config.web_max_empresas]
            avisar(f"Enriquecendo contatos na web ({len(alvos)} empresas)...")
            contatos_web = _enriquecer_web_paralelo(
                http, config, alvos, avisar
            )

        # 4) Montagem e exportação -----------------------------------------
        linhas = [
            _montar_linha(registro, dados_cnpj, contatos_web, config)
            for registro in registros
        ]
        df = montar_dataframe(linhas)
        arquivos = exportar(df, config)
        duracao = (datetime.now() - inicio).total_seconds()
        avisar(f"Concluído em {duracao:.0f}s. {len(linhas)} linhas exportadas.")

        return ResultadoExecucao(
            dataframe=df,
            arquivos=arquivos,
            total_bruto=total_bruto,
            total_final=len(linhas),
            duracao_segundos=duracao,
        )


# --------------------------------------------------------------- internals
def _enriquecer_web_paralelo(
    http: ClienteHTTP,
    config: Config,
    alvos: list[tuple[str, DadosCNPJ]],
    avisar: Callable[..., None],
) -> dict[str, Any]:
    """Enriquece contatos na web usando threads (I/O bound)."""
    enriq_web = EnriquecendorWeb(http, config)
    contatos: dict[str, Any] = {}
    if not alvos:
        return contatos

    total = len(alvos)
    if config.max_workers and config.max_workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
            futuros = {
                pool.submit(
                    enriq_web.enriquecer, cnpj, dados.razao_social, dados.nome_fantasia
                ): cnpj
                for cnpj, dados in alvos
            }
            for i, futuro in enumerate(as_completed(futuros), start=1):
                cnpj = futuros[futuro]
                try:
                    contatos[cnpj] = futuro.result()
                except Exception as exc:
                    log.debug("falha no enriquecimento web de %s: %s", cnpj, exc)
                avisar(f"Web {i}/{total}: {cnpj}", i, total)
        return contatos

    for i, (cnpj, dados) in enumerate(alvos, start=1):
        avisar(f"Web {i}/{total}: {dados.razao_social or cnpj}", i, total)
        try:
            contatos[cnpj] = enriq_web.enriquecer(
                cnpj, dados.razao_social, dados.nome_fantasia
            )
        except Exception as exc:
            log.debug("falha no enriquecimento web de %s: %s", cnpj, exc)
    return contatos


def _deduplicar(registros: list[RegistroLicitacao]) -> list[RegistroLicitacao]:
    vistos: set[str] = set()
    unicos = []
    for registro in registros:
        chave = registro.chave_dedup()
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(registro)
    return unicos


def _enriquecer_com_pdf(
    registros: list[RegistroLicitacao],
    fonte_pncp: FontePNCP,
    http: ClienteHTTP,
    config: Config,
    avisar: Callable[..., None],
) -> None:
    limite = min(len(registros), config.ler_pdf_max_registros)
    avisar(f"Lendo PDFs de {limite} registros para buscar cláusula de garantia...")
    for i, registro in enumerate(registros[:limite], start=1):
        documentos = fonte_pncp.obter_documentos(registro)
        for doc in documentos:
            url = doc.get("url", "")
            if not url.lower().endswith(".pdf"):
                continue
            texto = ler_pdf(url, http)
            if texto:
                registro.texto_extra = f"{registro.texto_extra}\n{texto}"
                if registro_tem_garantia(registro, config.palavras_chave_garantia):
                    break
        avisar(f"PDF {i}/{limite}", i, limite)


def contatos_empresa(dados: DadosCNPJ, contato: Any | None) -> dict[str, Any]:
    """Reúne telefone, celular/WhatsApp e e-mails válidos de uma empresa.

    Usado tanto na montagem do arquivo quanto na atualização de cards já
    existentes. E-mails inválidos (placeholder/domínio morto) são descartados.
    """
    telefone_receita = dados.telefone_1 or dados.telefone_2 or ""
    celular = ""
    if contato is not None:
        celular = getattr(contato, "celular_whatsapp", "") or ""
    if not celular and dados.telefone_2 and telefone_eh_celular(dados.telefone_2):
        celular = dados.telefone_2

    candidatos: list[str] = []
    if dados.email:
        candidatos.append(dados.email)
    if contato is not None:
        candidatos.extend(getattr(contato, "emails", [])[:5])

    emails: list[str] = []
    for email in candidatos:
        email = (email or "").strip().lower()
        if not email or email in emails:
            continue
        if not email_valido(email):
            log.info("e-mail descartado (inválido): %s", email)
            continue
        emails.append(email)
        if len(emails) >= 3:
            break

    return {
        "telefone": telefone_receita,
        "celular": celular,
        "emails": emails,
    }


def _montar_linha(
    registro: RegistroLicitacao,
    dados_cnpj: dict[str, DadosCNPJ],
    contatos_web: dict[str, Any],
    config: Config,
) -> dict[str, Any]:
    dados = dados_cnpj.get(registro.cnpj_vencedor, DadosCNPJ(cnpj=registro.cnpj_vencedor))
    contato = contatos_web.get(registro.cnpj_vencedor)

    valor_garantia = calcular_valor_garantia(
        registro.valor, config.percentual_garantia, registro.texto_extra
    )

    nome_empresa = dados.razao_social or registro.nome_vencedor or ""
    if dados.nome_fantasia and dados.nome_fantasia.upper() not in nome_empresa.upper():
        nome_empresa = f"{nome_empresa} ({dados.nome_fantasia})" if nome_empresa else dados.nome_fantasia

    contatos = contatos_empresa(dados, contato)
    telefone_receita = contatos["telefone"]
    celular = contatos["celular"]
    emails = contatos["emails"]

    return {
        "Fonte_Origem": registro.fonte,
        "Tipo_Registro": registro.tipo_registro,
        "Data_Publicacao_Homologacao": _formatar_data(registro.data_evento),
        "Estado_UF": registro.uf or dados.uf or "",
        "Cidade_Orgao": registro.cidade or "",
        "Orgao_Licitante": registro.orgao,
        "Objeto_Contratado": registro.objeto,
        "Valor_Contrato": registro.valor or 0.0,
        "Valor_Garantia_Estimado": valor_garantia,
        "Link_Edital_Contrato": registro.link or registro.link_origem or "",
        "CNPJ_Vencedor": _formatar_cnpj(registro.cnpj_vencedor),
        "Razao_Social_Vencedora": nome_empresa or "Não localizado",
        "Socios_Administradores": dados.socios_str if registro.cnpj_vencedor else "Não localizado",
        "Telefone_Receita": telefone_receita or "Não localizado",
        "Celular_WhatsApp_Encontrado": celular or "Não localizado",
        "Email_Contato": "; ".join(emails) if emails else "Não localizado",
        "Cidade_Empresa": _endereco_empresa(dados) or "Não localizado",
    }


def _endereco_empresa(dados: DadosCNPJ) -> str:
    cidade_uf = "/".join(p for p in [dados.cidade, dados.uf] if p)
    if dados.endereco and cidade_uf:
        return f"{dados.endereco} - {cidade_uf}"
    return dados.endereco or cidade_uf


def _formatar_cnpj(cnpj: str) -> str:
    digitos = "".join(c for c in str(cnpj or "") if c.isdigit())
    if len(digitos) != 14:
        return cnpj or ""
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def _formatar_data(valor: str) -> str:
    if not valor:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor[:19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return valor


def _configurar_log(config: Config) -> None:
    nivel = logging.INFO if config.verboso else logging.WARNING
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
