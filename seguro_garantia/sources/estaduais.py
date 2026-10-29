"""Portais estaduais / municipais estratégicos.

Fonte implementada:
- **e-Negócios SP** (Imprensa Oficial do Estado de SP) — busca por fornecedor
  (CNPJ ou razão social). A busca de licitações/contratos por área/órgão exige
  assinatura ("ticket") e não retorna resultados para usuário anônimo, por isso
  a integração usa o CNPJ do vencedor já coletado no PNCP como chave.

Fontes apenas estruturadas (stubs): BEC/SP, ComprasRS, Compras Públicas e
BLL Compras. Cada uma expõe `disponivel = False` e registra um aviso claro
quando habilitada, para não mascarar dados ausentes como "sem resultado".
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ..models import RegistroLicitacao
from .base import FonteBase


class FonteENegociosSP(FonteBase):
    """Licitações do Estado de SP via busca por fornecedor (CNPJ)."""

    nome = "e-Negócios SP"
    disponivel = True

    URL_BUSCA = "https://www.imprensaoficial.com.br/ENegocios/BuscaENegocios_14_1.aspx"
    URL_DETALHE = (
        "https://www.imprensaoficial.com.br/ENegocios/"
        "MostraDetalhesLicitacao_14_3.aspx?IdLicitacao={id_licitacao}"
    )
    PREFIXO = "ctl00$ctl00$ctl00$content$content$content$"

    # ------------------------------------------------------------------ coleta
    def coletar(self, cnpjs: list[str] | None = None) -> list[RegistroLicitacao]:
        alvos = self._alvos(cnpjs)
        if not alvos:
            self._avisar(
                "e-Negócios SP: nenhum CNPJ informado (use ENEGOCIOS_CNPJS ou colete "
                "contratos do PNCP primeiro)."
            )
            return []

        total = len(alvos)
        registros: list[RegistroLicitacao] = []
        for i, cnpj in enumerate(alvos, start=1):
            self._avisar(f"e-Negócios SP {i}/{total}: CNPJ {cnpj}", i, total)
            try:
                registros.extend(self._coletar_cnpj(cnpj))
            except Exception as exc:  # pragma: no cover - rede/HTML variável
                self._log(f"falha ao consultar {cnpj}: {exc}")
            self.http.dormir(self.config.pausa_entre_requisicoes)
        self._log(f"registros coletados: {len(registros)}")
        return registros

    def _alvos(self, cnpjs: list[str] | None) -> list[str]:
        base = cnpjs if cnpjs else self.config.enegocios_cnpjs
        digitos = [re.sub(r"\D", "", c or "") for c in (base or [])]
        unicos = list(dict.fromkeys(c for c in digitos if len(c) == 14))
        limite = self.config.enegocios_max_cnpjs
        if limite and limite > 0:
            unicos = unicos[:limite]
        return unicos

    def _coletar_cnpj(self, cnpj: str) -> list[RegistroLicitacao]:
        html = self.http.get(self.URL_BUSCA, as_json=False)
        if not html:
            return []
        campos = _campos_formulario(html)
        campos[self.PREFIXO + "txtFornecedorCPFCNPJ"] = cnpj
        campos[self.PREFIXO + "btnBuscarFornecedor"] = "Buscar"
        html_resultado = self.http.post(self.URL_BUSCA, data=campos, as_json=False)
        if not html_resultado:
            return []
        registros = _parse_resultados(html_resultado, cnpj, self.URL_DETALHE, self.nome)
        if self.config.enegocios_detalhes:
            for registro in registros:
                self._carregar_detalhes(registro)
        return registros

    def _carregar_detalhes(self, registro: RegistroLicitacao) -> None:
        url = registro.link
        if not url:
            return
        html = self.http.get(url, as_json=False)
        if not html:
            return
        texto = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
        registro.texto_extra = texto
        processo = re.search(r"Processo\s*:?\s*([A-Za-z0-9./\-]{3,})", texto)
        if processo:
            registro.processo = processo.group(1)
        local = re.search(
            r"Local de Execu[çc][ãa]o\s*:?\s*([^|]{3,80}?)(?:Modalidade|Publicado|Registro|$)",
            texto,
        )
        if local:
            registro.cidade = registro.cidade or local.group(1).strip()
        valor = re.search(r"Valor[^R]{0,20}R\$\s*([\d.]+,\d{2})", texto)
        if valor:
            registro.valor = _para_float(valor.group(1))
        self.http.dormir(self.config.pausa_entre_requisicoes)


# --------------------------------------------------------------- stubs
class _FontePendente(FonteBase):
    """Base para portais ainda não implementados (site-específicos)."""

    disponivel = False
    instrucao = ""

    def coletar(self) -> list[RegistroLicitacao]:
        self._avisar(
            f"{self.nome}: fonte habilitada, mas ainda não implementada. "
            f"{self.instrucao}".strip()
        )
        return []


class FonteBecSP(_FontePendente):
    nome = "BEC/SP"
    instrucao = "Requer engenharia de site específica (portal de compras do Estado de SP)."


class FonteComprasRS(_FontePendente):
    nome = "ComprasRS"
    instrucao = "Requer engenharia de site específica (Compras RS)."


class FonteComprasPublicas(_FontePendente):
    nome = "Compras Públicas"
    instrucao = "Requer engenharia de site específica (plataforma privada)."


class FonteBLLCompras(_FontePendente):
    nome = "BLL Compras"
    instrucao = "Requer engenharia de site específica (plataforma privada de prefeituras)."


# --------------------------------------------------------------- utilitários
def _campos_formulario(html: str) -> dict[str, str]:
    """Reconstrói os campos de um formulário ASP.NET WebForms (viewstate etc.)."""
    dados: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]+>", html):
        nome = re.search(r'name="([^"]+)"', tag)
        if not nome:
            continue
        tipo = re.search(r'type="([^"]+)"', tag)
        tipo_txt = (tipo.group(1).lower() if tipo else "text")
        if tipo_txt in ("submit", "button", "image"):
            continue
        if tipo_txt in ("checkbox", "radio"):
            if "checked" in tag:
                dados[nome.group(1)] = "on"
            continue
        valor = re.search(r'value="([^"]*)"', tag)
        dados[nome.group(1)] = valor.group(1) if valor else ""

    for nome, inner in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        selecionado = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', inner)
        opcoes = re.findall(r'<option[^>]*value="([^"]*)"', inner)
        dados[nome] = (
            selecionado.group(1)
            if selecionado
            else (opcoes[0] if opcoes else "")
        )
    return dados


def _parse_resultados(
    html: str, cnpj: str, url_detalhe: str, fonte: str
) -> list[RegistroLicitacao]:
    soup = BeautifulSoup(html, "lxml")
    tabela = None
    for t in soup.find_all("table"):
        if t.find("a", href=re.compile("MostraDetalhesLicitacao")):
            tabela = t
            break
    if tabela is None:
        return []

    registros: list[RegistroLicitacao] = []
    for linha in tabela.find_all("tr"):
        link = linha.find("a", href=re.compile("MostraDetalhesLicitacao"))
        if not link:
            continue
        celulas = [c.get_text(" ", strip=True) for c in linha.find_all(["td", "th"])]
        if len(celulas) < 6:
            continue
        id_match = re.search(r"IdLicitacao=(\d+)", link.get("href", ""))
        id_licitacao = id_match.group(1) if id_match else ""
        registros.append(
            RegistroLicitacao(
                fonte=fonte,
                tipo_registro="Licitação Nova",
                data_evento=celulas[4],
                uf="SP",
                cidade="",
                orgao=celulas[1],
                objeto=celulas[5],
                valor=0.0,
                link=url_detalhe.format(id_licitacao=id_licitacao) if id_licitacao else "",
                cnpj_vencedor=cnpj,
                nome_vencedor="",
                modalidade=celulas[2],
                numero_documento=celulas[3],
                numero_controle=f"e-negocios-{id_licitacao}",
                metadados={"id_licitacao": id_licitacao},
            )
        )
    return registros


def _para_float(valor: str) -> float:
    limpo = valor.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return 0.0
