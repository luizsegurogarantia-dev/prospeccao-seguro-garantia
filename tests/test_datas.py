"""Testes da janela de datas e dos utilitários de validação."""

from datetime import date

import pytest

from seguro_garantia.config import Config
from seguro_garantia.validacao import (
    dentro_janela,
    formatar_cnpj,
    formatar_data,
    parse_data,
    validar_cnpj,
)


def test_janela_de_30_dias_inclui_hoje_e_nao_ultrapassa():
    config = Config(dias_retroativos=30, data_referencia=date(2026, 10, 29))
    assert config.data_inicial == date(2026, 9, 30)
    assert config.data_final == date(2026, 10, 29)
    # 30 dias corridos: de 30/09 a 29/10, inclusive.
    assert (config.data_final - config.data_inicial).days + 1 == 30

    assert config.dentro_da_janela("2026-09-30") is True
    assert config.dentro_da_janela("2026-09-29") is False
    assert config.dentro_da_janela("2026-10-29") is True
    assert config.dentro_da_janela("2026-10-30") is False
    assert config.dentro_da_janela("") is None


def test_janela_de_um_dia_e_zero_ficam_em_hoje():
    for dias in (0, 1):
        config = Config(dias_retroativos=dias, data_referencia=date(2026, 10, 29))
        assert config.data_inicial == date(2026, 10, 29)
        assert config.data_final == date(2026, 10, 29)


def test_datas_em_formatos_diferentes():
    assert parse_data("2026-10-29") == date(2026, 10, 29)
    assert parse_data("2026-10-29T12:30:00") == date(2026, 10, 29)
    assert parse_data("29/10/2026") == date(2026, 10, 29)
    assert parse_data("29-10-2026") == date(2026, 10, 29)
    assert parse_data("") is None
    assert parse_data("data inválida") is None
    assert formatar_data("2026-10-29") == "29/10/2026"
    assert formatar_data("29/10/2026") == "29/10/2026"


def test_dentro_janela_com_limites_inclusivos():
    assert dentro_janela("30/09/2026", date(2026, 9, 30), date(2026, 10, 29)) is True
    assert dentro_janela("29/10/2026", date(2026, 9, 30), date(2026, 10, 29)) is True
    assert dentro_janela("29/09/2026", date(2026, 9, 30), date(2026, 10, 29)) is False


@pytest.mark.parametrize(
    "cnpj",
    ["11222333000181", "11.222.333/0001-81", "04252011000110", "04.252.011/0001-10"],
)
def test_cnpj_valido(cnpj):
    assert validar_cnpj(cnpj) is True


@pytest.mark.parametrize(
    "cnpj",
    ["", "123", "11111111111111", "11222333000182", "00.000.000/0000-00"],
)
def test_cnpj_invalido(cnpj):
    assert validar_cnpj(cnpj) is False


def test_formatar_cnpj():
    assert formatar_cnpj("11222333000181") == "11.222.333/0001-81"
    assert formatar_cnpj("123") == "123"
