"""Orquestração completa: coleta -> filtro -> enriquecimento -> exportação."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import Config
from .enrich.cnpj import EnriquecendorCNPJ
from .enrich.email import email_valido
from .enrich.sancoes import ConsultorSancoes
from .enrich.web import EnriquecendorWeb
from .execucao import registrar_ultima_execucao
from .exporter import exportar, montar_dataframe
from .filters import (
    calcular_valor_garantia,
    cnae_do_ramo,
    extrair_clausula_garantia,
    normalizar,
    registro_tem_garantia,
)
from .http_client import ClienteHTTP
from .models import DadosCNPJ, RegistroLicitacao, telefone_eh_celular
from .oportunidade import (
    calcular_score_confianca,
    classificar_garantia,
    extrair_prazo_execucao,
    formatar_vigencia,
    pendencias,
    prazo_por_vigencia,
    prioridade_comercial,
    resumo_links,
    setor_atividade,
)
from .pdf_text import ler_pdf
from .sources import FonteBase, FonteENegociosSP, FontePNCP, montar_fontes
from .validacao import formatar_cnpj, formatar_data, parse_data, validar_cnpj

log = logging.getLogger("seguro_garantia.pipeline")

Progresso = Callable[[str, int, int], None]


@dataclass
class ResultadoExecucao:
    dataframe: pd.DataFrame
    arquivos: dict[str, Path]
    total_bruto: int
    total_final: int
    duracao_segundos: float
    erros: list[str] = field(default_factory=list)
    ultima_execucao: dict[str, Any] | None = None


def executar(config: Config, progresso: Progresso | None = None) -> ResultadoExecucao:
    inicio = datetime.now()
    _configurar_log(config)
    erros: list[str] = []

    def avisar(mensagem: str, atual: int = 0, total: int = 0) -> None:
        log.info(mensagem)
        if progresso:
            progresso(mensagem, atual, total)

    try:
        return _executar(config, avisar, erros, inicio)
    except Exception as exc:  # registra a falha antes de propagar
        erros.append(str(exc))
        _gravar_ultima_execucao(
            config=config,
            status="falha",
            erros=erros,
            inicio=inicio,
            total_bruto=0,
            total_final=0,
            duracao=(datetime.now() - inicio).total_seconds(),
            arquivos={},
            fontes=[],
            df=None,
        )
        raise


def _executar(
    config: Config,
    avisar: Callable[..., None],
    erros: list[str],
    inicio: datetime,
) -> ResultadoExecucao:
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
        fontes_usadas: list[str] = []
        for fonte in fontes:
            fontes_usadas.append(fonte.nome)
            try:
                registros.extend(fonte.coletar())
            except Exception as exc:  # uma fonte com erro não derruba o todo
                mensagem = f"Falha na fonte {fonte.nome}: {exc}"
                erros.append(mensagem)
                avisar(mensagem)

        # 1b) Fontes complementares que dependem dos CNPJs já coletados -------
        if config.usar_enegocios_sp:
            fontes_usadas.append("e-Negócios SP")
            cnpjs_conhecidos = [
                r.cnpj_vencedor for r in registros if r.cnpj_vencedor
            ]
            if cnpjs_conhecidos or config.enegocios_cnpjs:
                fonte_eneg = FonteENegociosSP(http, config, progresso=avisar)
                try:
                    registros.extend(fonte_eneg.coletar(cnpjs_conhecidos))
                except Exception as exc:
                    mensagem = f"Falha na fonte {fonte_eneg.nome}: {exc}"
                    erros.append(mensagem)
                    avisar(mensagem)

        total_bruto = len(registros)
        registros = _deduplicar(registros)
        avisar(f"{total_bruto} registros brutos | {len(registros)} após deduplicação")

        # 1c) Trava da janela: nada fora dos N dias corridos configurados -----
        antes_janela = len(registros)
        registros = [r for r in registros if _na_janela(r, config)]
        if len(registros) != antes_janela:
            avisar(
                f"Janela de {config.dias_retroativos} dias "
                f"({config.data_inicial:%d/%m/%Y} a {config.data_final:%d/%m/%Y}): "
                f"{antes_janela} -> {len(registros)} registros"
            )

        # 1d) Links diretos de edital/ata/resultado/contrato -------------------
        if config.coletar_links_documentos:
            _enriquecer_links_documentos(registros, fonte_pncp, http, config, avisar)

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

        # 3b) Sanções públicas (CEIS/CNEP) ----------------------------------
        if config.enriquecer_sancoes and config.transparencia_api_key and cnpjs:
            alvos_sancao = list(dict.fromkeys(cnpjs))
            avisar(f"Consultando sanções públicas de {len(alvos_sancao)} empresas...")
            sancoes = _consultar_sancoes_paralelo(http, config, alvos_sancao, avisar)
            for cnpj, (lista, verificado) in sancoes.items():
                dados = dados_cnpj.get(cnpj)
                if dados is None:
                    dados = DadosCNPJ(cnpj=cnpj)
                    dados_cnpj[cnpj] = dados
                dados.sancoes = lista
                dados.sancoes_verificado = verificado

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

        status = "parcial" if erros else "sucesso"
        ultima = _gravar_ultima_execucao(
            config=config,
            status=status,
            erros=erros,
            inicio=inicio,
            total_bruto=total_bruto,
            total_final=len(linhas),
            duracao=duracao,
            arquivos=arquivos,
            fontes=fontes_usadas,
            df=df,
        )

        return ResultadoExecucao(
            dataframe=df,
            arquivos=arquivos,
            total_bruto=total_bruto,
            total_final=len(linhas),
            duracao_segundos=duracao,
            erros=erros,
            ultima_execucao=ultima,
        )


# --------------------------------------------------------------- internals
def _na_janela(registro: RegistroLicitacao, config: Config) -> bool:
    """Mantém registros sem data (sinalizados) e descarta os fora da janela."""
    for valor in (registro.data_resultado, registro.data_evento):
        resultado = config.dentro_da_janela(valor)
        if resultado is not None:
            return resultado
    return True


def _gravar_ultima_execucao(
    *,
    config: Config,
    status: str,
    erros: list[str],
    inicio: datetime,
    total_bruto: int,
    total_final: int,
    duracao: float,
    arquivos: dict[str, Path],
    fontes: list[str],
    df: pd.DataFrame | None,
) -> dict[str, Any] | None:
    if not config.registrar_ultima_execucao:
        return None
    dados: dict[str, Any] = {
        "status": status,
        "inicio": inicio.isoformat(timespec="seconds"),
        "janela": {
            "dias": config.dias_retroativos,
            "data_inicial": config.data_inicial.strftime("%d/%m/%Y"),
            "data_final": config.data_final.strftime("%d/%m/%Y"),
        },
        "totais": {
            "registros_brutos": total_bruto,
            "linhas_exportadas": total_final,
        },
        "duracao_segundos": round(duracao, 1),
        "fontes": fontes,
        "erros": erros,
        "arquivos": {formato: str(caminho) for formato, caminho in arquivos.items()},
        "parametros": config.resumo(),
    }
    if df is not None and not df.empty:
        dados["resumo_oportunidades"] = {
            "garantia_confirmada": int(
                (df.get("Garantia_Status", pd.Series(dtype=str)) == "Confirmada").sum()
            ),
            "garantia_provavel": int(
                (df.get("Garantia_Status", pd.Series(dtype=str)) == "Provável").sum()
            ),
            "prioridade_alta": int(
                (df.get("Prioridade_Comercial", pd.Series(dtype=str)) == "Alta").sum()
            ),
        }
    try:
        registrar_ultima_execucao(config, dados)
    except Exception as exc:  # registro não pode derrubar a exportação
        log.warning("não foi possível registrar a última execução: %s", exc)
    return dados


def _enriquecer_links_documentos(
    registros: list[RegistroLicitacao],
    fonte_pncp: FontePNCP,
    http: ClienteHTTP,
    config: Config,
    avisar: Callable[..., None],
) -> None:
    """Busca a lista de documentos do PNCP e separa edital/ata/resultado/contrato."""
    alvos = [r for r in registros if r.fonte == fonte_pncp.nome and r.cnpj_vencedor]
    if not alvos:
        return
    limite = config.links_max_registros
    if limite and limite > 0:
        alvos = sorted(alvos, key=lambda r: r.valor or 0.0, reverse=True)[:limite]
    total = len(alvos)
    if not total:
        return
    avisar(f"Buscando links de documentos de {total} registros no PNCP...")
    for i, registro in enumerate(alvos, start=1):
        try:
            documentos = fonte_pncp.obter_documentos(registro)
        except Exception as exc:  # documento é complementar; não interrompe
            log.debug("falha ao obter documentos de %s: %s", registro.numero_controle, exc)
            documentos = []
        for doc in documentos:
            url = doc.get("url", "")
            if not url:
                continue
            tipo = _tipo_documento(doc.get("titulo", ""), doc.get("tipo", ""))
            if tipo == "edital" and not registro.link_edital:
                registro.link_edital = url
            elif tipo == "ata" and not registro.link_ata:
                registro.link_ata = url
            elif tipo == "resultado" and not registro.link_resultado:
                registro.link_resultado = url
            elif tipo == "contrato" and not registro.link_contrato:
                registro.link_contrato = url
        avisar(f"Links PNCP {i}/{total}", i, total)
        http.dormir(config.pausa_entre_requisicoes)


def _tipo_documento(titulo: str, tipo: str) -> str:
    base = normalizar(f"{titulo} {tipo}")
    if "ata" in base:
        return "ata"
    if any(t in base for t in ("resultado", "homolog", "adjudic", "julgamento")):
        return "resultado"
    if any(t in base for t in ("edital", "minuta", "termo de referencia", "projeto basico")):
        return "edital"
    if any(t in base for t in ("contrato", "termo aditivo", "aditivo")):
        return "contrato"
    return "outro"


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


def _consultar_sancoes_paralelo(
    http: ClienteHTTP,
    config: Config,
    cnpjs: list[str],
    avisar: Callable[..., None],
) -> dict[str, tuple[list[str], bool]]:
    """Consulta CEIS/CNEP para vários CNPJs, em threads (I/O bound)."""
    consultor = ConsultorSancoes(http, config)
    resultado: dict[str, tuple[list[str], bool]] = {}
    total = len(cnpjs)
    if not total:
        return resultado

    if config.max_workers and config.max_workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
            futuros = {pool.submit(consultor.consultar, c): c for c in cnpjs}
            for i, futuro in enumerate(as_completed(futuros), start=1):
                cnpj = futuros[futuro]
                try:
                    resultado[cnpj] = futuro.result()
                except Exception as exc:
                    log.debug("falha ao consultar sanções de %s: %s", cnpj, exc)
                    resultado[cnpj] = ([], False)
                avisar(f"Sanções {i}/{total}: {cnpj}", i, total)
        return resultado

    for i, cnpj in enumerate(cnpjs, start=1):
        avisar(f"Sanções {i}/{total}: {cnpj}", i, total)
        try:
            resultado[cnpj] = consultor.consultar(cnpj)
        except Exception as exc:
            log.debug("falha ao consultar sanções de %s: %s", cnpj, exc)
            resultado[cnpj] = ([], False)
    return resultado


def _deduplicar(registros: list[RegistroLicitacao]) -> list[RegistroLicitacao]:
    """Remove duplicidades e complementa o registro remanescente."""
    por_chave: dict[str, RegistroLicitacao] = {}
    for registro in registros:
        chave = registro.chave_dedup()
        existente = por_chave.get(chave)
        if existente is None:
            por_chave[chave] = registro
        else:
            existente.mesclar(registro)
    return list(por_chave.values())


def _enriquecer_com_pdf(
    registros: list[RegistroLicitacao],
    fonte_pncp: FontePNCP,
    http: ClienteHTTP,
    config: Config,
    avisar: Callable[..., None],
) -> None:
    limite = min(len(registros), config.ler_pdf_max_registros)
    avisar(
        f"Lendo PDFs dos {limite} contratos de maior valor "
        "para extrair a cláusula de garantia..."
    )
    # Prioriza os maiores valores: é onde a garantia (e a comissão) importa mais.
    ordenados = sorted(registros, key=lambda r: r.valor or 0.0, reverse=True)[:limite]
    for i, registro in enumerate(ordenados, start=1):
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


LIMITE_EMAILS_TOTAL = 10
LIMITE_EMAILS_PRINCIPAIS = 3


def contatos_empresa(dados: DadosCNPJ, contato: Any | None) -> dict[str, Any]:
    """Reúne telefone, celular/WhatsApp, site e e-mails válidos de uma empresa.

    Usado tanto na montagem do arquivo quanto na atualização de cards já
    existentes. E-mails inválidos (placeholder/domínio morto) são descartados.
    Os três primeiros vão em `emails`; o restante (até 10) em `outros_emails`,
    para não perder contatos alternativos do mesmo domínio.
    """
    celular = ""
    if contato is not None:
        celular = getattr(contato, "celular_whatsapp", "") or ""
    if not celular and dados.telefone_2 and telefone_eh_celular(dados.telefone_2):
        celular = dados.telefone_2

    # O telefone da Receita é institucional; se o único número for o celular,
    # ele já aparece na coluna de WhatsApp e não se repete aqui.
    telefone_receita = dados.telefone_1 or ""
    if not telefone_receita and dados.telefone_2 and not celular:
        telefone_receita = dados.telefone_2

    candidatos: list[str] = []
    if dados.email:
        candidatos.append(dados.email)
    if contato is not None:
        candidatos.extend(getattr(contato, "emails", []) or [])

    emails: list[str] = []
    for email in candidatos:
        email = (email or "").strip().lower()
        if not email or email in emails:
            continue
        if not email_valido(email):
            log.info("e-mail descartado (inválido): %s", email)
            continue
        emails.append(email)
        if len(emails) >= LIMITE_EMAILS_TOTAL:
            break

    site = ""
    if contato is not None:
        site = getattr(contato, "site", "") or ""
    site = site or dados.site

    return {
        "telefone": telefone_receita,
        "celular": celular,
        "emails": emails[:LIMITE_EMAILS_PRINCIPAIS],
        "outros_emails": emails[LIMITE_EMAILS_PRINCIPAIS:],
        "site": site,
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
    outros_emails = contatos["outros_emails"]

    # Cláusula de garantia: só faz sentido dizer "não identificado" quando
    # houve texto para ler. Sem leitura, a coluna fica vazia (não é falha).
    texto_lido = bool((registro.texto_extra or "").strip())
    qualificacao = classificar_garantia(
        registro, texto_lido, config.palavras_chave_garantia
    )
    status_garantia = qualificacao["status"]
    clausula = {
        chave.replace("clausula_", ""): valor
        for chave, valor in qualificacao.items()
        if chave.startswith("clausula_")
    }

    def _do_edital(campo: str) -> str:
        if not texto_lido:
            return ""
        return clausula.get(campo) or "Não identificado"

    setor = setor_atividade(dados, registro.objeto)
    score = calcular_score_confianca(
        registro, dados, contatos, status_garantia, setor
    )
    prioridade = prioridade_comercial(
        registro,
        status_garantia,
        score,
        valor_garantia,
        dados.sancoes if dados.sancoes_verificado else None,
    )
    pendencias_texto = pendencias(registro, dados, contatos, status_garantia)
    cnpj_valido = validar_cnpj(registro.cnpj_vencedor)
    link_contrato = registro.link_contrato or registro.link
    link_principal = registro.link_edital or link_contrato or registro.link_origem
    prazo_execucao = (
        registro.prazo_execucao
        or extrair_prazo_execucao(registro.texto_extra)
        or prazo_por_vigencia(registro.vigencia_inicio, registro.vigencia_fim)
    )
    vigencia = formatar_vigencia(registro.vigencia_inicio, registro.vigencia_fim)
    data_resultado = formatar_data(registro.data_resultado or registro.data_evento)

    return {
        "Fonte_Origem": registro.fonte,
        "Tipo_Registro": registro.tipo_registro,
        "Data_Publicacao_Homologacao": data_resultado,
        "Data_Resultado": data_resultado,
        "Estado_UF": registro.uf or dados.uf or "",
        "Cidade_Orgao": registro.cidade or "",
        "Orgao_Licitante": registro.orgao,
        "Objeto_Contratado": registro.objeto,
        "Valor_Contrato": registro.valor or 0.0,
        "Valor_Garantia_Estimado": valor_garantia,
        "Link_Edital_Contrato": link_principal,
        "CNPJ_Vencedor": formatar_cnpj(registro.cnpj_vencedor),
        "CNPJ_Valido": (
            "Sim" if cnpj_valido else ("Não" if registro.cnpj_vencedor else "Não informado")
        ),
        "Razao_Social_Vencedora": nome_empresa or "Não localizado",
        "Socios_Administradores": dados.socios_str if registro.cnpj_vencedor else "Não localizado",
        "Telefone_Receita": telefone_receita or "Não localizado",
        "Celular_WhatsApp_Encontrado": celular or "Não localizado",
        "Email_Contato": "; ".join(emails) if emails else "Não localizado",
        "Cidade_Empresa": _endereco_empresa(dados) or "Não localizado",
        "Setor_Atividade": setor,
        # --- Dossiê cadastral ---
        "Perfil_Empresa": dados.perfil_str,
        "Porte_Empresa": dados.porte or "Não localizado",
        "Capital_Social": dados.capital_social or None,
        "Data_Abertura": dados.data_abertura or "Não localizado",
        "Idade_Empresa": dados.idade_anos if dados.idade_anos is not None else "",
        "Natureza_Juridica": dados.natureza_juridica or "Não localizado",
        "Simples_Nacional": dados.simples or "Não localizado",
        "CNAE_Principal": dados.cnae_principal or "Não localizado",
        "Sancoes": dados.sancoes_str,
        # --- Processo, prazos e vigência ---
        "Numero_Processo": registro.processo or "",
        "Numero_Edital_Contrato": registro.numero_documento or "",
        "Data_Assinatura_Contrato": formatar_data(registro.data_assinatura),
        "Prazo_Execucao": prazo_execucao or "",
        "Vigencia_Contratual": vigencia or "",
        # --- Cláusula de garantia do edital ---
        "Garantia_Status": status_garantia,
        "Garantia_Justificativa": qualificacao["justificativa"],
        "Garantia_Evidencias": qualificacao["evidencias"],
        "Garantia_Percentual_Edital": _do_edital("percentual"),
        "Prazo_Apresentacao_Garantia": _do_edital("prazo"),
        "Modalidade_Garantia_Aceita": _do_edital("modalidade"),
        "Vigencia_Garantia": _do_edital("vigencia"),
        # --- Links e rastreabilidade ---
        "Link_Edital": registro.link_edital or "",
        "Link_Resultado": registro.link_resultado or "",
        "Link_Contrato": link_contrato or "",
        "Link_Ata": registro.link_ata or "",
        "Fonte_Dados": resumo_links(registro),
        # --- Qualificação comercial ---
        "Score_Confianca": score,
        "Prioridade_Comercial": prioridade,
        "Pendencias": pendencias_texto,
        # --- Contatos complementares ---
        "Site_Empresa": contatos["site"] or "Não localizado",
        "Outros_Emails": "; ".join(outros_emails),
    }


def _endereco_empresa(dados: DadosCNPJ) -> str:
    cidade_uf = "/".join(p for p in [dados.cidade, dados.uf] if p)
    if dados.endereco and cidade_uf:
        return f"{dados.endereco} - {cidade_uf}"
    return dados.endereco or cidade_uf


def _formatar_cnpj(cnpj: str) -> str:
    return formatar_cnpj(cnpj)


def _formatar_data(valor: str) -> str:
    return formatar_data(valor)


def _configurar_log(config: Config) -> None:
    nivel = logging.INFO if config.verboso else logging.WARNING
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
