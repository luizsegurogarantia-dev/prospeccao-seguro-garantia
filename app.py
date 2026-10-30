"""Interface Streamlit da aplicação de prospecção B2B - Seguro Garantia.

Executar com:
    streamlit run app.py
"""

from __future__ import annotations

import io
import os
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from seguro_garantia.config import carregar_config
from seguro_garantia.execucao import ler_ultima_execucao
from seguro_garantia.pipeline import executar

# Torna as variáveis do .env visíveis já na sidebar (chave de sanções, etc.).
load_dotenv(override=False)

st.set_page_config(page_title="Prospecção Seguro Garantia", page_icon="🛡️", layout="wide")

COLUNAS_PAINEL = [
    "Data_Resultado",
    "Prioridade_Comercial",
    "Score_Confianca",
    "Garantia_Status",
    "Razao_Social_Vencedora",
    "CNPJ_Vencedor",
    "Orgao_Licitante",
    "Estado_UF",
    "Objeto_Contratado",
    "Valor_Contrato",
    "Valor_Garantia_Estimado",
    "Setor_Atividade",
    "Link_Edital",
    "Link_Contrato",
    "Telefone_Receita",
    "Email_Contato",
    "Pendencias",
]

ORDEM_PRIORIDADE = {"Alta": 3, "Média": 2, "Baixa": 1}


def _sidebar() -> dict:
    st.sidebar.header("Parâmetros de execução")

    dias = st.sidebar.number_input(
        "Janela de busca (dias corridos)",
        0,
        365,
        30,
        help=(
            "30 = hoje + os 29 dias anteriores (30 dias corridos, incluindo hoje). "
            "0 ou 1 = somente hoje."
        ),
    )
    valor_minimo = st.sidebar.number_input("Valor mínimo (R$)", 0.0, step=50_000.0, value=0.0)
    percentual = st.sidebar.slider(
        "Percentual estimado da garantia", 1, 30, 5, help="Usado quando o edital não informa."
    ) / 100.0

    st.sidebar.subheader("Desempenho (modo teste)")
    max_paginas = st.sidebar.number_input(
        "Máx. páginas por consulta",
        1,
        2000,
        200,
        help=(
            "Cada página traz até 50 registros e o PNCP limita a frequência de consultas "
            "(~3s por página). Reduza para testar rápido (ex.: 3 = ~15s)."
        ),
    )
    limite = st.sidebar.number_input(
        "Limite de registros (0 = sem limite)",
        0,
        100000,
        0,
        help="Corta após N registros, antes do enriquecimento. Use um valor baixo para testar.",
    )

    st.sidebar.subheader("Escopo")
    ufs = st.sidebar.text_input("UFs (vazio = Brasil)", placeholder="SP,RJ,MG")
    modalidades = st.sidebar.text_input("Modalidades de edital (PNCP)", value="4,5,6,7,8,9")
    buscar_editais = st.sidebar.checkbox(
        "Buscar editais abertos",
        value=True,
        help=(
            "Os editais do PNCP ainda não têm vencedor; eles só são coletados "
            "quando a opção abaixo estiver ligada."
        ),
    )
    incluir_editais_sem_vencedor = st.sidebar.checkbox(
        "Incluir editais sem vencedor (ainda sem CNPJ)",
        value=False,
        help=(
            "Editais sem vencedor não são oportunidades qualificadas; mantidos "
            "desligados por padrão. Ligue apenas se quiser mapear o mercado."
        ),
    )
    usar_compras_gov = st.sidebar.checkbox(
        "Incluir Compras.gov.br", value=False, help="Requer COMPRAS_GOV_ORGAOS no .env"
    )
    filtrar_por_ramo = st.sidebar.checkbox(
        "Filtrar por ramo (obras, engenharia, limpeza...)", value=True
    )
    filtrar_por_cnae = st.sidebar.checkbox(
        "Filtrar por CNAE da empresa (após CNPJ)", value=False
    )

    st.sidebar.subheader("Fontes complementares")
    usar_enegocios_sp = st.sidebar.checkbox(
        "e-Negócios SP (SP)", value=False, help="Busca por CNPJ do vencedor."
    )
    enegocios_cnpjs = st.sidebar.text_input(
        "CNPJs extras e-Negócios (opcional)", placeholder="00.000.000/0000-00, ..."
    )
    usar_licitacoes_e = st.sidebar.checkbox("Licitações-E (BB)", value=False)
    usar_caixa = st.sidebar.checkbox("CAIXA", value=False)
    usar_bndes = st.sidebar.checkbox("BNDES", value=False)
    usar_petronect = st.sidebar.checkbox("Petronect (Petrobras)", value=False)
    usar_bec_sp = st.sidebar.checkbox("BEC/SP", value=False)
    usar_compras_rs = st.sidebar.checkbox("ComprasRS", value=False)
    usar_compras_publicas = st.sidebar.checkbox("Compras Públicas", value=False)
    usar_bll_compras = st.sidebar.checkbox("BLL Compras", value=False)

    st.sidebar.subheader("Links e garantia")
    coletar_links = st.sidebar.checkbox(
        "Buscar links de edital/ata/resultado/contrato",
        value=True,
        help="Consulta os documentos do PNCP. Deixe desligado para acelerar.",
    )
    links_max = st.sidebar.number_input(
        "Máx. registros com busca de links",
        0,
        2000,
        50,
        disabled=not coletar_links,
        help="0 = sem limite. Prioriza os maiores valores.",
    )
    filtro_estrito = st.sidebar.checkbox(
        "Manter só registros com cláusula de garantia", value=False
    )
    exigir_garantia_no_texto = st.sidebar.checkbox(
        "Descartar registro sem garantia explícita no texto",
        value=False,
        help="Implica ler os anexos (PDF) do edital/contrato. Bem mais lento.",
    )
    ler_pdf = st.sidebar.checkbox("Ler PDF do edital (lento)", value=False)

    st.sidebar.subheader("Enriquecimento")
    enriquecer_cnpj = st.sidebar.checkbox("Enriquecer CNPJ (Receita/BrasilAPI)", value=True)
    usar_receitaws = st.sidebar.checkbox("Usar ReceitaWS como fallback", value=False)
    enriquecer_web = st.sidebar.checkbox(
        "Buscar contatos na web (e-mail/WhatsApp)", value=True
    )
    chave_transparencia = _chave_transparencia()
    enriquecer_sancoes = st.sidebar.checkbox(
        "Consultar sanções CEIS/CNEP",
        value=bool(chave_transparencia),
        disabled=not chave_transparencia,
        help=(
            "Exige TRANSPARENCIA_API_KEY (variável de ambiente ou Secrets). "
            "Cadastro gratuito: https://api.portaldatransparencia.gov.br"
        ),
    )
    sem_teto_web = st.sidebar.checkbox(
        "Sem teto de empresas (web)", value=True, disabled=not enriquecer_web
    )
    web_max = st.sidebar.number_input(
        "Teto de empresas (web)", 1, 5000, 50, disabled=(not enriquecer_web) or sem_teto_web
    )
    max_workers = st.sidebar.number_input(
        "Paralelismo (threads)", 1, 16, 6, help="Concorrência do enriquecimento."
    )

    st.sidebar.subheader("Saída")
    diretorio = st.sidebar.text_input("Diretório de saída", value="./saida")
    gerar_csv = st.sidebar.checkbox("Gerar também CSV", value=True)

    return dict(
        dias_retroativos=dias,
        valor_minimo=valor_minimo,
        percentual_garantia=percentual,
        max_paginas=int(max_paginas),
        limite=int(limite) or None,
        ufs=[u.strip().upper() for u in ufs.split(",") if u.strip()] or None,
        modalidades=[int(m.strip()) for m in modalidades.replace(";", ",").split(",") if m.strip()] or None,
        buscar_editais=buscar_editais,
        incluir_editais_sem_vencedor=incluir_editais_sem_vencedor,
        usar_compras_gov=usar_compras_gov,
        filtrar_por_ramo=filtrar_por_ramo,
        filtrar_por_cnae=filtrar_por_cnae,
        usar_enegocios_sp=usar_enegocios_sp,
        enegocios_cnpjs=[c.strip() for c in enegocios_cnpjs.split(",") if c.strip()],
        usar_licitacoes_e=usar_licitacoes_e,
        usar_caixa=usar_caixa,
        usar_bndes=usar_bndes,
        usar_petronect=usar_petronect,
        usar_bec_sp=usar_bec_sp,
        usar_compras_rs=usar_compras_rs,
        usar_compras_publicas=usar_compras_publicas,
        usar_bll_compras=usar_bll_compras,
        coletar_links_documentos=coletar_links,
        links_max_registros=int(links_max),
        filtro_garantia_estrito=filtro_estrito,
        exigir_garantia_no_texto=exigir_garantia_no_texto,
        ler_anexos_pdf=ler_pdf,
        enriquecer_cnpj=enriquecer_cnpj,
        usar_receitaws=usar_receitaws,
        enriquecer_web=enriquecer_web,
        enriquecer_sancoes=enriquecer_sancoes,
        transparencia_api_key=chave_transparencia or None,
        web_max_empresas=0 if sem_teto_web else int(web_max),
        max_workers=int(max_workers),
        diretorio_saida=Path(diretorio),
        gerar_csv=gerar_csv,
        verboso=False,
    )


def _segredo(nome: str) -> str:
    """Lê uma configuração sensível da variável de ambiente ou dos Secrets."""
    valor = os.environ.get(nome, "").strip()
    if valor:
        return valor
    try:
        return str(st.secrets.get(nome, "")).strip()
    except Exception:  # noqa: BLE001 - sem arquivo de secrets, segue sem valor
        return ""


def _chave_transparencia() -> str:
    return _segredo("TRANSPARENCIA_API_KEY")


def _senha_configurada() -> str:
    """Lê a senha de APP_SENHA (variável de ambiente) ou dos Secrets do Streamlit."""
    return _segredo("APP_SENHA")


def _exigir_senha() -> None:
    """Bloqueia o acesso quando APP_SENHA está definida (uso em link público).

    Sem a senha configurada, o app abre direto como sempre. Com ela, exige a
    senha uma vez por sessão do navegador.
    """
    senha = _senha_configurada()
    if not senha or st.session_state.get("autenticado"):
        return

    st.title("🛡️ Prospecção B2B — Seguro Garantia")
    st.caption("Acesso restrito. Informe a senha para continuar.")
    with st.form("login"):
        digitada = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", type="primary")
    if entrar:
        if digitada == senha:
            st.session_state["autenticado"] = True
            st.rerun()
        st.error("Senha incorreta.")
    st.stop()


def _multiselect(coluna: str, df: pd.DataFrame, rotulo: str, **kwargs) -> list[str]:
    opcoes = sorted(
        {str(v).strip() for v in df[coluna].dropna() if str(v).strip()}
    )
    return st.multiselect(rotulo, opcoes, **kwargs)


def _painel(df: pd.DataFrame) -> None:
    """Painel pesquisável, filtrável e ordenável das oportunidades."""
    st.subheader("Painel de oportunidades")
    if df.empty:
        st.info("Nenhum registro encontrado para os parâmetros atuais.")
        return

    trabalho = df.copy()
    trabalho["_data"] = pd.to_datetime(
        trabalho["Data_Resultado"], dayfirst=True, errors="coerce"
    )

    with st.expander("Filtros do painel", expanded=True):
        busca = st.text_input(
            "Busca livre",
            placeholder="Empresa, CNPJ, órgão, objeto, processo ou setor...",
        )
        colunas_busca = [
            "Razao_Social_Vencedora",
            "CNPJ_Vencedor",
            "Orgao_Licitante",
            "Objeto_Contratado",
            "Numero_Processo",
            "Numero_Edital_Contrato",
            "Setor_Atividade",
        ]
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            datas_validas = trabalho["_data"].dropna()
            if not datas_validas.empty:
                minimo = datas_validas.min().date()
                maximo = datas_validas.max().date()
                intervalo = st.date_input(
                    "Data do resultado",
                    value=(minimo, maximo),
                    min_value=minimo,
                    max_value=maximo,
                )
            else:
                intervalo = None
        with col2:
            status_garantia = _multiselect(
                "Garantia_Status", trabalho, "Exigência de garantia"
            )
        with col3:
            prioridades = _multiselect(
                "Prioridade_Comercial", trabalho, "Prioridade comercial"
            )
        with col4:
            setores = _multiselect("Setor_Atividade", trabalho, "Setor")

        col5, col6, col7, col8 = st.columns(4)
        with col5:
            ufs_sel = _multiselect("Estado_UF", trabalho, "UF")
        with col6:
            orgaos = _multiselect("Orgao_Licitante", trabalho, "Órgão")
        with col7:
            valor_min, valor_max = st.slider(
                "Faixa de valor do contrato (R$)",
                min_value=0.0,
                max_value=max(1.0, float(trabalho["Valor_Contrato"].max() or 0)),
                value=(0.0, max(1.0, float(trabalho["Valor_Contrato"].max() or 0))),
                step=10_000.0,
                format="R$ %.0f",
            )
        with col8:
            score_min = st.slider(
                "Score de confiança mínimo", 0, 100, 0, help="0 = todos."
            )

        ordenacao = st.selectbox(
            "Ordenar por",
            [
                "Data do resultado (mais recente)",
                "Maior valor de contrato",
                "Maior garantia estimada",
                "Maior score de confiança",
                "Prioridade comercial",
            ],
        )

    mascara = pd.Series(True, index=trabalho.index)
    if busca.strip():
        termo = busca.strip()
        encontrou = pd.Series(False, index=trabalho.index)
        for coluna in colunas_busca:
            encontrou |= (
                trabalho[coluna]
                .fillna("")
                .astype(str)
                .str.contains(termo, case=False, regex=False, na=False)
            )
        digitos = re.sub(r"\D", "", termo)
        if digitos:
            encontrou |= (
                trabalho["CNPJ_Vencedor"]
                .fillna("")
                .astype(str)
                .str.replace(r"\D", "", regex=True)
                .str.contains(digitos, na=False)
            )
        mascara &= encontrou

    if intervalo:
        if isinstance(intervalo, tuple):
            inicio = intervalo[0]
            fim = intervalo[1] if len(intervalo) > 1 else intervalo[0]
        else:
            inicio = fim = intervalo
        if inicio and fim:
            mascara &= trabalho["_data"].dt.date.between(inicio, fim)

    for coluna, selecao in (
        ("Garantia_Status", status_garantia),
        ("Prioridade_Comercial", prioridades),
        ("Setor_Atividade", setores),
        ("Estado_UF", ufs_sel),
        ("Orgao_Licitante", orgaos),
    ):
        if selecao:
            mascara &= trabalho[coluna].isin(selecao)

    mascara &= trabalho["Valor_Contrato"].fillna(0) >= valor_min
    mascara &= trabalho["Valor_Contrato"].fillna(0) <= valor_max
    mascara &= trabalho["Score_Confianca"].fillna(0) >= score_min

    filtrado = trabalho[mascara].copy()
    if ordenacao == "Maior valor de contrato":
        filtrado = filtrado.sort_values("Valor_Contrato", ascending=False)
    elif ordenacao == "Maior garantia estimada":
        filtrado = filtrado.sort_values("Valor_Garantia_Estimado", ascending=False)
    elif ordenacao == "Maior score de confiança":
        filtrado = filtrado.sort_values("Score_Confianca", ascending=False)
    elif ordenacao == "Prioridade comercial":
        filtrado["_prioridade_ord"] = (
            filtrado["Prioridade_Comercial"].map(ORDEM_PRIORIDADE).fillna(0)
        )
        filtrado = filtrado.sort_values(
            ["_prioridade_ord", "Score_Confianca"], ascending=[False, False]
        )
    else:
        filtrado = filtrado.sort_values("_data", ascending=False, na_position="last")

    metricas = st.columns(4)
    metricas[0].metric("Oportunidades no recorte", len(filtrado))
    metricas[1].metric(
        "Valor total (R$)",
        f"{filtrado['Valor_Contrato'].sum():,.0f}".replace(",", "."),
    )
    metricas[2].metric(
        "Garantia estimada (R$)",
        f"{filtrado['Valor_Garantia_Estimado'].sum():,.0f}".replace(",", "."),
    )
    metricas[3].metric(
        "Prioridade alta",
        int((filtrado["Prioridade_Comercial"] == "Alta").sum()),
    )

    visiveis = [c for c in COLUNAS_PAINEL if c in filtrado.columns]
    configuracao = {
        "Data_Resultado": st.column_config.TextColumn("Resultado"),
        "Prioridade_Comercial": st.column_config.TextColumn("Prioridade"),
        "Score_Confianca": st.column_config.ProgressColumn(
            "Confiança", min_value=0, max_value=100, format="%d"
        ),
        "Garantia_Status": st.column_config.TextColumn("Garantia"),
        "Valor_Contrato": st.column_config.NumberColumn(
            "Valor do contrato", format="R$ %.2f"
        ),
        "Valor_Garantia_Estimado": st.column_config.NumberColumn(
            "Garantia estimada", format="R$ %.2f"
        ),
        "Link_Edital": st.column_config.LinkColumn("Edital"),
        "Link_Contrato": st.column_config.LinkColumn("Contrato"),
        "Pendencias": st.column_config.TextColumn("Pendências", width="large"),
    }
    st.dataframe(
        filtrado[visiveis],
        use_container_width=True,
        height=560,
        column_config=configuracao,
        hide_index=True,
    )

    st.caption(
        "Confiança: qualidade dos dados (0–100). Prioridade: potencial comercial "
        "combinado com garantia, valor e sanções. Garantia: Confirmada, Provável, "
        "Não encontrada ou Não verificada (sem leitura do texto)."
    )

    recorte = filtrado.drop(columns=["_data", "_prioridade_ord"], errors="ignore")
    carimbo = datetime.now().strftime("%Y%m%d_%H%M")
    colunas_download = st.columns(2)
    colunas_download[0].download_button(
        "⬇️ Baixar recorte em CSV",
        data=recorte.to_csv(sep=";", index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"oportunidades_filtradas_{carimbo}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        recorte.to_excel(writer, sheet_name="Oportunidades", index=False)
    colunas_download[1].download_button(
        "⬇️ Baixar recorte em Excel",
        data=buffer.getvalue(),
        file_name=f"oportunidades_filtradas_{carimbo}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _mostrar_ultima_execucao(config, resultado) -> None:
    registro = resultado.ultima_execucao or ler_ultima_execucao(config)
    if not registro:
        return
    janela = registro.get("janela", {})
    totais = registro.get("totais", {})
    status = registro.get("status", "")
    st.caption(
        "Última execução: "
        f"{registro.get('executado_em', '—')} | status: {status} | "
        f"janela: {janela.get('data_inicial', '—')} a {janela.get('data_final', '—')} | "
        f"{totais.get('registros_brutos', 0)} brutos → "
        f"{totais.get('linhas_exportadas', 0)} linhas"
    )
    if registro.get("erros"):
        st.warning("Ocorreram falhas parciais: " + " | ".join(registro["erros"][:5]))


def main() -> None:
    _exigir_senha()
    st.title("🛡️ Prospecção B2B — Seguro Garantia")
    st.caption(
        "Monitora contratos e resultados publicados nos últimos 30 dias, qualifica a "
        "exigência de garantia e enriquece os contatos das empresas vencedoras."
    )

    overrides = _sidebar()
    iniciar = st.sidebar.button("▶ Gerar carteira", type="primary", use_container_width=True)

    if iniciar:
        config = carregar_config(**overrides)
        barra = st.progress(0.0, text="Iniciando...")
        status = st.empty()
        estado = {"passos": 0, "fracao": 0.0}
        inicio_ts = time.time()

        def progresso(mensagem: str, atual: int = 0, total: int = 0) -> None:
            if total:
                fracao = min(atual / total, 0.9)
            else:
                estado["passos"] += 1
                fracao = min(estado["passos"] * 0.05, 0.9)
            estado["fracao"] = max(estado["fracao"], fracao)
            decorrido = time.time() - inicio_ts
            barra.progress(estado["fracao"], text=mensagem)
            status.info(f"{mensagem}\n\n⏱️ {decorrido:.0f}s decorridos — o app continua trabalhando.")

        try:
            resultado = executar(config, progresso)
            barra.progress(1.0, text="Concluído")
            st.session_state["resultado"] = resultado
            st.session_state["config"] = config
        except Exception as exc:  # noqa: BLE001
            st.exception(exc)
            return

    resultado = st.session_state.get("resultado")
    if not resultado:
        st.info("Configure os parâmetros na barra lateral e clique em **Gerar carteira**.")
        return

    config = st.session_state["config"]
    st.success(
        f"{resultado.total_final} linhas exportadas de {resultado.total_bruto} registros "
        f"brutos em {resultado.duracao_segundos:.0f}s."
    )
    _mostrar_ultima_execucao(config, resultado)

    df = resultado.dataframe
    _painel(df)

    st.subheader("Arquivos completos")
    colunas = st.columns(2)
    xlsx_path = resultado.arquivos.get("xlsx")
    if xlsx_path and Path(xlsx_path).exists():
        colunas[0].download_button(
            "⬇️ Baixar Excel completo",
            data=Path(xlsx_path).read_bytes(),
            file_name=Path(xlsx_path).name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    csv_path = resultado.arquivos.get("csv")
    if csv_path and Path(csv_path).exists():
        colunas[1].download_button(
            "⬇️ Baixar CSV completo",
            data=Path(csv_path).read_bytes(),
            file_name=Path(csv_path).name,
            mime="text/csv",
            use_container_width=True,
        )

    st.caption(f"Arquivos salvos em: {config.diretorio_saida}")


if __name__ == "__main__":
    main()
