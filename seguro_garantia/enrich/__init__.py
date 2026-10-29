"""Etapas de enriquecimento de dados das empresas vencedoras."""

from .cnpj import EnriquecendorCNPJ
from .web import EnriquecendorWeb

__all__ = ["EnriquecendorCNPJ", "EnriquecendorWeb"]
