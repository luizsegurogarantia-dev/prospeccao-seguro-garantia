"""Modelos de dados normalizados usados por todas as fontes e pelo enriquecimento."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class RegistroLicitacao:
    """Registro normalizado de uma licitação/contrato, independente da fonte.

    Cada fonte (PNCP, Compras.gov.br, portais) converte seu formato bruto para
    esta estrutura, de forma que filtros, enriquecimento e exportação funcionem
    para qualquer origem.
    """

    fonte: str
    tipo_registro: str  # "Licitação Nova", "Contrato Homologado" ou "Termo Aditado"
    data_evento: str = ""  # data de publicação/homologação (ISO ou DD/MM/AAAA)
    uf: str = ""
    cidade: str = ""
    orgao: str = ""
    objeto: str = ""
    valor: float = 0.0
    link: str = ""
    cnpj_vencedor: str = ""
    nome_vencedor: str = ""
    # Campos auxiliares (não saem diretamente no arquivo final)
    modalidade: str = ""
    numero_controle: str = ""
    numero_documento: str = ""  # número do edital (numeroCompra) ou do contrato
    processo: str = ""  # processo administrativo (ex.: PR66/2026, 1752/2026)
    orgao_cnpj: str = ""
    ano_compra: int | None = None
    sequencial_compra: int | None = None
    numero_retificacao: int = 0
    texto_extra: str = ""  # texto do edital/contrato p/ busca de cláusula
    link_origem: str = ""
    metadados: dict[str, Any] = field(default_factory=dict)

    def chave_dedup(self) -> str:
        """Chave usada para eliminar duplicidades entre páginas/fontes."""
        if self.numero_controle:
            return f"{self.fonte}:{self.numero_controle}"
        return f"{self.fonte}:{self.cnpj_vencedor}:{self.objeto[:60]}:{self.valor}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DadosCNPJ:
    """Dossiê cadastral + contato de uma empresa, obtidos no enriquecimento."""

    cnpj: str
    razao_social: str = ""
    nome_fantasia: str = ""
    situacao: str = ""
    situacao_data: str = ""
    cnae_principal: str = ""
    cnaes_secundarios: list[str] = field(default_factory=list)
    natureza_juridica: str = ""
    porte: str = ""
    capital_social: float = 0.0
    data_abertura: str = ""
    idade_anos: int | None = None
    simples: str = ""
    mei: str = ""
    matriz_filial: str = ""
    endereco: str = ""
    cidade: str = ""
    uf: str = ""
    telefone_1: str = ""
    telefone_2: str = ""
    email: str = ""
    socios: list[str] = field(default_factory=list)
    site: str = ""
    fonte: str = ""
    # Sanções públicas (CEIS/CNEP). Verificado=True indica que a consulta rodou.
    sancoes: list[str] = field(default_factory=list)
    sancoes_verificado: bool = False

    @property
    def socios_str(self) -> str:
        return "; ".join(self.socios) if self.socios else "Não localizado"

    @property
    def sancoes_str(self) -> str:
        if not self.sancoes_verificado:
            return "Não verificado"
        if not self.sancoes:
            return "LIMPA"
        return "; ".join(self.sancoes)

    @property
    def perfil_str(self) -> str:
        """Resumo de uma linha para leitura rápida na planilha."""
        partes: list[str] = []
        if self.porte:
            partes.append(self.porte)
        if self.capital_social:
            partes.append(f"capital R$ {self.capital_social:,.0f}".replace(",", "."))
        if self.idade_anos is not None:
            partes.append(f"{self.idade_anos} ano(s) de atividade")
        if self.simples:
            partes.append(f"Simples: {self.simples}")
        if self.mei:
            partes.append(f"MEI: {self.mei}")
        return " | ".join(partes) if partes else "Não localizado"


@dataclass
class ContatoEnriquecido:
    """Contatos adicionais obtidos no enriquecimento web."""

    cnpj: str
    telefones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    site: str = ""
    whatsapp: str = ""

    @property
    def celular_whatsapp(self) -> str:
        if self.whatsapp:
            return self.whatsapp
        for tel in self.telefones:
            if telefone_eh_celular(tel):
                return tel
        return ""


def telefone_eh_celular(telefone: str) -> bool:
    """Heurística: celular brasileiro tem 11 dígitos e o 3º (após DDD) é 9."""
    digitos = "".join(c for c in telefone if c.isdigit())
    if len(digitos) == 11:
        return digitos[2] == "9"
    if len(digitos) == 13 and digitos.startswith("55"):  # com DDI
        return digitos[4] == "9"
    return False
