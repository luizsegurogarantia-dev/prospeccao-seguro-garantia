"""Testes de deduplicação e mescla de registros."""

from seguro_garantia.models import RegistroLicitacao
from seguro_garantia.pipeline import _deduplicar


def _registro(**kwargs) -> RegistroLicitacao:
    base = dict(
        fonte="PNCP",
        tipo_registro="Contrato Homologado",
        data_resultado="2026-10-28",
        orgao="Órgão Teste",
        objeto="Obra de drenagem",
        valor=100_000.0,
        numero_controle="11222333000181-1-000001/2026",
        cnpj_vencedor="11222333000181",
        nome_vencedor="",
    )
    base.update(kwargs)
    return RegistroLicitacao(**base)


def test_deduplica_mesmo_numero_de_controle_entre_fontes():
    primeiro = _registro(fonte="PNCP")
    segundo = _registro(fonte="Compras.gov.br", nome_vencedor="Empresa Teste Ltda")
    resultado = _deduplicar([primeiro, segundo])
    assert len(resultado) == 1
    assert resultado[0].nome_vencedor == "Empresa Teste Ltda"


def test_mescla_campos_complementares():
    primeiro = _registro(link="", processo="", valor=0.0)
    segundo = _registro(
        fonte="Compras.gov.br",
        link="https://exemplo/contrato",
        processo="PR 123/2026",
        valor=250_000.0,
        data_assinatura="2026-10-20",
    )
    resultado = _deduplicar([primeiro, segundo])
    assert len(resultado) == 1
    registro = resultado[0]
    assert registro.link == "https://exemplo/contrato"
    assert registro.processo == "PR 123/2026"
    assert registro.valor == 250_000.0
    assert registro.data_assinatura == "2026-10-20"


def test_nao_deduplica_registros_diferentes():
    a = _registro(numero_controle="controle-a")
    b = _registro(numero_controle="controle-b", cnpj_vencedor="04252011000110")
    assert len(_deduplicar([a, b])) == 2


def test_chave_dedup_ignora_caixa_acentos_e_pontuacao():
    a = _registro(numero_controle="ABC-123/2026")
    b = _registro(numero_controle="abc 123 2026")
    assert a.chave_dedup() == b.chave_dedup()


def test_chave_dedup_usa_documento_quando_sem_controle():
    a = _registro(
        numero_controle="",
        numero_documento="CT 001/2026",
        processo="PR 99/2026",
    )
    b = _registro(
        numero_controle="",
        numero_documento="ct-001-2026",
        processo="pr 99-2026",
        fonte="Compras.gov.br",
    )
    assert a.chave_dedup() == b.chave_dedup()
