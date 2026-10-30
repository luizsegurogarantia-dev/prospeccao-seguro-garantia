"""Fonte complementar: API de Dados Abertos do Compras.gov.br (esfera federal).

A API (`https://dadosabertos.compras.gov.br/modulo-contratos/1_consultarContratos`)
exige `codigoOrgao`, então a varredura é feita órgão a órgão. Preencha
`COMPRAS_GOV_ORGAOS` no `.env` com os códigos desejados.

Observação de engenharia: o PNCP já agrega os contratos federais; esta fonte é
útil sobretudo como conferência/contingência. Por isso vem desligada por padrão.
"""

from __future__ import annotations

from typing import Any

from ..filters import registro_do_ramo
from ..models import RegistroLicitacao
from .base import FonteBase

BASE_COMPRAS_GOV = "https://dadosabertos.compras.gov.br"


class FonteComprasGov(FonteBase):
    nome = "Compras.gov.br"

    def coletar(self) -> list[RegistroLicitacao]:
        if not self.config.compras_gov_orgaos:
            self._log("nenhum órgão informado em COMPRAS_GOV_ORGAOS — fonte ignorada")
            return []

        data_ini, data_fim = self.config.datas_pncp()
        # A API espera datas no formato ISO (AAAA-MM-DD).
        ini = f"{data_ini[:4]}-{data_ini[4:6]}-{data_ini[6:]}"
        fim = f"{data_fim[:4]}-{data_fim[4:6]}-{data_fim[6:]}"

        registros: list[RegistroLicitacao] = []
        for orgao in self.config.compras_gov_orgaos:
            registros.extend(self._coletar_orgao(orgao, ini, fim))
        self._log(f"contratos coletados: {len(registros)}")
        return registros

    def _coletar_orgao(self, orgao: str, ini: str, fim: str) -> list[RegistroLicitacao]:
        registros: list[RegistroLicitacao] = []
        for pagina in range(1, self.config.max_paginas + 1):
            payload = self.http.get(
                f"{BASE_COMPRAS_GOV}/modulo-contratos/1_consultarContratos",
                params={
                    "pagina": pagina,
                    "tamanhoPagina": self.config.tamanho_pagina,
                    "codigoOrgao": orgao,
                    "dataVigenciaInicialMin": ini,
                    "dataVigenciaInicialMax": fim,
                },
            )
            if not isinstance(payload, dict):
                break
            itens = payload.get("resultado") or []
            if not itens:
                break
            for item in itens:
                registro = self._normalizar(item)
                if registro and self._passa_filtros(registro):
                    registros.append(registro)
            total_paginas = payload.get("totalPaginas") or 0
            if total_paginas and pagina >= total_paginas:
                break
            self.http.dormir(self.config.pausa_entre_requisicoes)
        return registros

    def _normalizar(self, item: dict[str, Any]) -> RegistroLicitacao | None:
        return RegistroLicitacao(
            fonte=self.nome,
            tipo_registro="Contrato Homologado",
            data_evento=item.get("dataHoraInclusao", "") or "",
            data_resultado=item.get("dataHoraInclusao", "")
            or item.get("dataPublicacaoPncp", "")
            or item.get("dataAssinatura", "")
            or "",
            data_assinatura=item.get("dataAssinatura", "") or "",
            vigencia_inicio=item.get("dataVigenciaInicial", "")
            or item.get("dataVigenciaInicio", "")
            or "",
            vigencia_fim=item.get("dataVigenciaFinal", "")
            or item.get("dataVigenciaFim", "")
            or "",
            uf="",
            cidade="",
            orgao=item.get("nomeOrgao", "") or item.get("nomeUnidadeGestora", ""),
            objeto=item.get("objeto", "") or "",
            valor=float(item.get("valorGlobal") or 0),
            link="",
            cnpj_vencedor="".join(c for c in str(item.get("niFornecedor", "")) if c.isdigit()),
            nome_vencedor=item.get("nomeRazaoSocialFornecedor", "") or "",
            modalidade=item.get("nomeModalidadeCompra", "") or "",
            numero_documento=str(item.get("numeroContrato", "") or ""),
            processo=item.get("processo", "") or "",
            numero_controle=item.get("numeroControlePncpContrato", "")
            or f"{self.nome}-{item.get('codigoOrgao')}-{item.get('numeroContrato')}",
            link_origem=item.get("numeroControlePncpCompra", "") or "",
            metadados={
                "processo": item.get("processo", ""),
                "codigo_orgao": item.get("codigoOrgao"),
                "numero_controle_compra": item.get("numeroControlePncpCompra", ""),
            },
        )

    def _passa_filtros(self, registro: RegistroLicitacao) -> bool:
        if registro.valor and registro.valor < self.config.valor_minimo:
            return False
        if self.config.filtrar_por_ramo and self.config.ramos_palavras_chave:
            if not registro_do_ramo(registro, self.config.ramos_palavras_chave):
                return False
        return True
