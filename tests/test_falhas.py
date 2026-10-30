"""Testes de resiliência: retries, rate-limit e falha de fonte."""

from datetime import date

import pytest

from seguro_garantia import pipeline
from seguro_garantia.config import Config
from seguro_garantia.http_client import ClienteHTTP


class RespostaFalsa:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._payload


def test_http_retenta_5xx_e_devolve_none(monkeypatch):
    cliente = ClienteHTTP(max_tentativas=2)
    chamadas = []

    def get_falso(*args, **kwargs):
        chamadas.append(1)
        return RespostaFalsa(503)

    cliente.session.get = get_falso
    monkeypatch.setattr("seguro_garantia.http_client.time.sleep", lambda _: None)

    assert cliente.get("https://exemplo.test/api") is None
    assert len(chamadas) == 2


def test_http_respeita_429_e_tenta_de_novo(monkeypatch):
    cliente = ClienteHTTP(max_tentativas=2)
    respostas = [
        RespostaFalsa(429, headers={"Retry-After": "1"}),
        RespostaFalsa(200, payload={"ok": True}),
    ]

    def get_falso(*args, **kwargs):
        return respostas.pop(0)

    cliente.session.get = get_falso
    monkeypatch.setattr("seguro_garantia.http_client.time.sleep", lambda _: None)

    assert cliente.get("https://exemplo.test/api") == {"ok": True}


class HTTPFalso:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def dormir(self, _segundos):
        return None

    def get(self, *args, **kwargs):
        return None

    def post(self, *args, **kwargs):
        return None

    def close(self):
        return None


class FonteComFalha:
    nome = "Fonte com falha"

    def coletar(self):
        raise RuntimeError("indisponível")


class PNCPFalso:
    nome = "PNCP"

    def __init__(self, *args, **kwargs):
        pass

    def obter_documentos(self, registro):
        return []


def test_falha_de_fonte_nao_derruba_pipeline_e_registra_execucao(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(pipeline, "ClienteHTTP", lambda **kwargs: HTTPFalso())
    monkeypatch.setattr(pipeline, "FontePNCP", PNCPFalso)
    monkeypatch.setattr(
        pipeline, "montar_fontes", lambda config, http, progresso=None: [FonteComFalha()]
    )
    monkeypatch.setattr(pipeline, "exportar", lambda df, config: {})

    config = Config(
        dias_retroativos=30,
        data_referencia=date(2026, 10, 29),
        diretorio_saida=tmp_path,
        enriquecer_cnpj=False,
        enriquecer_web=False,
        coletar_links_documentos=False,
        gerar_csv=False,
        incluir_aba_parametros=False,
        registrar_ultima_execucao=True,
    )

    resultado = pipeline.executar(config)

    assert resultado.total_bruto == 0
    assert len(resultado.erros) == 1
    assert "Fonte com falha" in resultado.erros[0]
    assert resultado.ultima_execucao["status"] == "parcial"
    assert (tmp_path / "ultima_execucao.json").exists()


@pytest.mark.parametrize(
    ("titulo", "tipo", "esperado"),
    [
        ("Edital de concorrência", "Edital", "edital"),
        ("Ata de julgamento", "Ata", "ata"),
        ("Resultado da homologação", "Outro", "resultado"),
        ("Contrato assinado", "Contrato", "contrato"),
        ("Termo aditivo", "Contrato", "contrato"),
        ("Documento qualquer", "Outro", "outro"),
    ],
)
def test_classifica_tipo_de_documento(titulo, tipo, esperado):
    assert pipeline._tipo_documento(titulo, tipo) == esperado
