"""Interface Streamlit da aplicação de prospecção B2B - Seguro Garantia.

Executar com:
    streamlit run app.py
"""

from __future__ import annotations

import io
import os
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from seguro_garantia.config import carregar_config
from seguro_garantia.pipeline import executar

# Torna as variáveis do .env visíveis já na sidebar (chave de sanções, etc.).
load_dotenv(override=False)

st.set_page_config(page_title="Prospecção Seguro Garantia", page_icon="🛡️", layout="wide")


def _sidebar() -> dict:
    st.sidebar.header("Parâmetros de execução")

    dias = st.sidebar.number_input(
        "Janela de busca (dias atrás)",
        0,
        365,
        30,
        help=(
            "0 = somente hoje. 1 = hoje e ontem. N = de hoje até N dias atrás "
            "(a janela inclui as duas pontas)."
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
    buscar_editais = st.sidebar.checkbox("Buscar editais abertos", value=True)
    incluir_editais_sem_vencedor = st.sidebar.checkbox(
        "Incluir editais sem vencedor (ainda sem CNPJ)",
        value=True,
        help="Editais homologados ainda sem vencedor entram só com órgão e objeto.",
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

    st.sidebar.subheader("Filtro de garantia")
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


def main() -> None:
    _exigir_senha()
    st.title("🛡️ Prospecção B2B — Seguro Garantia")
    st.caption(
        "Consolida licitações/contratos do PNCP, filtra cláusulas de garantia e enriquece "
        "os contatos das empresas vencedoras em um único arquivo Excel/CSV."
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

    metricas = st.columns(4)
    df = resultado.dataframe
    metricas[0].metric("Linhas", len(df))
    metricas[1].metric("Valor total (R$)", f"{df['Valor_Contrato'].sum():,.0f}".replace(",", "."))
    metricas[2].metric("Garantia estimada (R$)", f"{df['Valor_Garantia_Estimado'].sum():,.0f}".replace(",", "."))
    metricas[3].metric("Empresas", df["CNPJ_Vencedor"].replace("", None).nunique())

    st.subheader("Prévia")
    st.dataframe(df.head(200), use_container_width=True, height=420)

    st.subheader("Download")
    colunas = st.columns(2)
    xlsx_path = resultado.arquivos.get("xlsx")
    if xlsx_path and Path(xlsx_path).exists():
        colunas[0].download_button(
            "⬇️ Baixar Excel",
            data=Path(xlsx_path).read_bytes(),
            file_name=Path(xlsx_path).name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    csv_path = resultado.arquivos.get("csv")
    if csv_path and Path(csv_path).exists():
        colunas[1].download_button(
            "⬇️ Baixar CSV",
            data=Path(csv_path).read_bytes(),
            file_name=Path(csv_path).name,
            mime="text/csv",
            use_container_width=True,
        )

    st.caption(f"Arquivos salvos em: {config.diretorio_saida}")


if __name__ == "__main__":
    main()
