"""Testes de extração de dados e qualificação da garantia."""

from seguro_garantia.filters import (
    calcular_valor_garantia,
    extrair_clausula_garantia,
    extrair_percentual_garantia,
)
from seguro_garantia.config import Config
from seguro_garantia.models import DadosCNPJ, RegistroLicitacao
from seguro_garantia.sources.pncp import FontePNCP
from seguro_garantia.oportunidade import (
    STATUS_CONFIRMADA,
    STATUS_NAO_ENCONTRADA,
    STATUS_NAO_VERIFICADA,
    STATUS_PROVAVEL,
    classificar_garantia,
    extrair_prazo_execucao,
    formatar_vigencia,
    prazo_por_vigencia,
    prioridade_comercial,
    setor_atividade,
    trecho_evidencia,
)

TEXTO_GARANTIA = (
    "CLÁUSULA DÉCIMA - DA GARANTIA DE EXECUÇÃO. O contratado deverá apresentar "
    "garantia de execução no percentual de 10% (dez por cento) do valor do contrato, "
    "em até 10 (dez) dias úteis após a assinatura, admitida a modalidade seguro-garantia, "
    "com vigência de 12 meses."
)


def _registro(**kwargs) -> RegistroLicitacao:
    base = dict(
        fonte="PNCP",
        tipo_registro="Contrato Homologado",
        data_resultado="2026-10-28",
        orgao="Prefeitura Teste",
        objeto="Obra de pavimentação asfáltica",
        valor=1_000_000.0,
        cnpj_vencedor="11222333000181",
        nome_vencedor="Empresa Teste Ltda",
    )
    base.update(kwargs)
    return RegistroLicitacao(**base)


def test_extrai_percentual_e_clausula():
    assert extrair_percentual_garantia(TEXTO_GARANTIA) == 0.10
    clausula = extrair_clausula_garantia(TEXTO_GARANTIA)
    assert clausula["percentual"] == "10%"
    assert clausula["prazo"] == "10 dias"
    assert "Seguro garantia" in clausula["modalidade"]
    assert clausula["vigencia"] == "12 meses"


def test_calcula_valor_garantia_usa_percentual_do_texto():
    assert calcular_valor_garantia(1_000_000, 0.05, TEXTO_GARANTIA) == 100_000.0
    assert calcular_valor_garantia(1_000_000, 0.05, "") == 50_000.0


def test_classificacao_sem_texto_e_nao_verificada():
    resultado = classificar_garantia(_registro(), texto_lido=False, palavras_chave=["garantia"])
    assert resultado["status"] == STATUS_NAO_VERIFICADA
    assert resultado["evidencias"] == ""


def test_classificacao_texto_sem_mencao_e_nao_encontrada():
    registro = _registro(texto_extra="O objeto é a execução de obra, sem outras cláusulas.")
    resultado = classificar_garantia(registro, texto_lido=True, palavras_chave=["garantia"])
    assert resultado["status"] == STATUS_NAO_ENCONTRADA


def test_classificacao_mencao_generica_e_provavel():
    registro = _registro(texto_extra="Haverá garantia, conforme o instrumento convocatório.")
    resultado = classificar_garantia(registro, texto_lido=True, palavras_chave=["garantia"])
    assert resultado["status"] == STATUS_PROVAVEL
    assert resultado["evidencias"]


def test_classificacao_clausula_completa_e_confirmada():
    registro = _registro(texto_extra=TEXTO_GARANTIA)
    resultado = classificar_garantia(registro, texto_lido=True, palavras_chave=["garantia"])
    assert resultado["status"] == STATUS_CONFIRMADA
    assert resultado["clausula_percentual"] == "10%"
    assert "seguro-garantia" in resultado["evidencias"].lower()


def test_objeto_com_garantia_sem_leitura_e_provavel():
    registro = _registro(objeto="Serviço com exigência de garantia contratual")
    resultado = classificar_garantia(registro, texto_lido=False, palavras_chave=["garantia"])
    assert resultado["status"] == STATUS_PROVAVEL


def test_trecho_evidencia_limita_e_nao_quebra():
    evidencia = trecho_evidencia(TEXTO_GARANTIA, limite=500)
    assert "garantia" in evidencia.lower()
    assert len(evidencia) <= 500


def test_extrai_prazo_de_execucao_e_vigencia():
    texto = "O prazo de execução será de 180 dias, contados da ordem de serviço."
    assert extrair_prazo_execucao(texto) == "180 dias"
    assert extrair_prazo_execucao("Vigência de 12 meses.") == "12 meses"
    assert extrair_prazo_execucao("Sem prazo declarado.") == ""


def test_formatar_vigencia():
    assert formatar_vigencia("2026-01-01", "2026-12-31").startswith(
        "01/01/2026 a 31/12/2026"
    )
    assert "(364 dias)" in formatar_vigencia("2026-01-01", "2026-12-31")
    assert formatar_vigencia("2026-01-01", "") == "Início em 01/01/2026"


def test_prazo_por_vigencia_e_rotulado_como_estimativa():
    assert prazo_por_vigencia("2026-10-27", "2026-11-11") == "15 dias (vigência)"
    assert prazo_por_vigencia("2026-10-27", "") == ""
    assert prazo_por_vigencia("2026-10-27", "2026-10-27") == ""


def test_setor_prioriza_cnae_e_depois_objeto():
    assert setor_atividade(DadosCNPJ(cnpj="1", cnae_principal="4120-4/00")) == (
        "Construção e engenharia"
    )
    assert setor_atividade(None, "Serviço de limpeza e conservação") == (
        "Serviços prediais e limpeza"
    )
    assert setor_atividade(None, "Objeto indefinido") == "Outros"


def test_prioridade_comercial():
    registro = _registro(valor=2_000_000)
    assert (
        prioridade_comercial(registro, STATUS_CONFIRMADA, 80, 200_000) == "Alta"
    )
    assert (
        prioridade_comercial(registro, STATUS_NAO_VERIFICADA, 20, 0) == "Baixa"
    )
    assert (
        prioridade_comercial(registro, STATUS_CONFIRMADA, 90, 200_000, ["CEIS"]) == "Baixa"
    )


def test_normaliza_contrato_pncp_com_vigencia_e_links():
    fonte = FontePNCP(http=object(), config=Config())
    registro = fonte._normalizar_contrato(
        {
            "numeroControlePncpCompra": "12075748000132-1-000131/2024",
            "orgaoEntidade": {"cnpj": "82577636000165", "razaoSocial": "MUNICÍPIO"},
            "anoContrato": 2026,
            "sequencialContrato": 509,
            "dataAtualizacao": "2026-10-28T00:00:25",
            "nomeRazaoSocialFornecedor": "FENIX INFORMÁTICA E TELEFONIA LTDA",
            "niFornecedor": "05047599000132",
            "tipoContrato": {"nome": "Outros"},
            "numeroContratoEmpenho": "AF354570",
            "objetoContrato": "EQUIPAMENTOS DE INFORMÁTICA",
            "valorInicial": 500.0,
            "valorGlobal": 500.0,
            "dataAssinatura": "2026-10-23",
            "dataVigenciaInicio": "2026-10-23",
            "dataVigenciaFim": "2026-11-26",
            "numeroControlePNCP": "82577636000165-2-000509/2026",
            "dataPublicacaoPncp": "2026-10-28T00:00:25",
            "unidadeOrgao": {"ufSigla": "SC", "municipioNome": "Tijucas"},
            "processo": "000083/2024",
        }
    )
    assert registro is not None
    assert registro.data_resultado == "2026-10-28T00:00:25"
    assert registro.vigencia_inicio == "2026-10-23"
    assert registro.vigencia_fim == "2026-11-26"
    assert registro.cnpj_vencedor == "05047599000132"
    assert registro.link_edital == "https://pncp.gov.br/app/editais/12075748000132/2024/131"
    assert registro.link_contrato == "https://pncp.gov.br/app/contratos/82577636000165/2026/509"
