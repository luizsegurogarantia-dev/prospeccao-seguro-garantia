"""Fonte oficial: Portal Nacional de Contratações Públicas (PNCP).

Endpoints públicos (sem token):
- ``/api/consulta/v1/contratos``            -> contratos publicados na janela
- ``/api/consulta/v1/contratacoes/publicacao`` -> editais publicados na janela
- ``/api/pncp/v1/orgaos/{orgao}/contratos/{ano}/{seq}/arquivos`` -> documentos
- ``/api/pncp/v1/orgaos/{orgao}/contratos/{ano}/{seq}/termos``   -> aditivos

O PNCP alimenta União, estados e municípios, então já cobre a esmagadora
maioria dos casos de grande vulto com uma única integração.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import RegistroLicitacao
from ..filters import registro_do_ramo
from .base import FonteBase

BASE_CONSULTA = "https://pncp.gov.br/api/consulta/v1"
BASE_API = "https://pncp.gov.br/api/pncp/v1"
BASE_APP = "https://pncp.gov.br/app"


class FontePNCP(FonteBase):
    nome = "PNCP"

    # ------------------------------------------------------------------ coleta
    def coletar(self) -> list[RegistroLicitacao]:
        registros: list[RegistroLicitacao] = []
        registros.extend(self._coletar_contratos())
        if self.config.buscar_editais and self.config.incluir_editais_sem_vencedor:
            registros.extend(self._coletar_editais())
        return registros

    # --------------------------------------------------------------- contratos
    def _coletar_contratos(self) -> list[RegistroLicitacao]:
        data_ini, data_fim = self.config.datas_pncp()
        self._avisar(f"Contratos PNCP: consultando {data_ini} a {data_fim}...")
        registros: list[RegistroLicitacao] = []

        for pagina in range(1, self.config.max_paginas + 1):
            payload = self._paginar(
                f"{BASE_CONSULTA}/contratos",
                {"dataInicial": data_ini, "dataFinal": data_fim},
                pagina,
            )
            if payload is None:
                break
            itens = payload.get("data") or []
            if not itens:
                break
            for item in itens:
                registro = self._normalizar_contrato(item)
                if registro and self._passa_filtros(registro):
                    registros.append(registro)
            total_paginas = payload.get("totalPaginas") or 0
            self._avisar(
                f"Contratos PNCP: página {pagina}"
                + (f"/{total_paginas}" if total_paginas else "")
                + f" — {len(registros)} registros na janela"
            )
            if self._ultima_pagina(payload, pagina):
                break

        self._log(f"contratos coletados: {len(registros)}")
        return registros

    def _normalizar_contrato(self, item: dict[str, Any]) -> RegistroLicitacao | None:
        orgao = item.get("orgaoEntidade") or {}
        unidade = item.get("unidadeOrgao") or {}
        tipo_contrato = (item.get("tipoContrato") or {}).get("nome", "") or ""
        retificacoes = item.get("numeroRetificacao") or 0

        tipo_registro = "Contrato Homologado"
        if retificacoes > 0 or any(
            termo in tipo_contrato.lower()
            for termo in ("aditivo", "prorrogação", "prorrogacao", "retifica")
        ):
            tipo_registro = "Termo Aditado"

        orgao_cnpj = orgao.get("cnpj", "")
        ano = item.get("anoContrato")
        seq = item.get("sequencialContrato")
        link = (
            f"{BASE_APP}/contratos/{orgao_cnpj}/{ano}/{seq}"
            if orgao_cnpj and ano and seq
            else ""
        )
        controle_compra = item.get("numeroControlePncpCompra", "") or ""
        link_edital = _link_edital_por_controle(controle_compra)

        return RegistroLicitacao(
            fonte=self.nome,
            tipo_registro=tipo_registro,
            data_evento=item.get("dataPublicacaoPncp") or item.get("dataAssinatura") or "",
            data_resultado=item.get("dataPublicacaoPncp") or item.get("dataAssinatura") or "",
            data_assinatura=item.get("dataAssinatura") or "",
            vigencia_inicio=item.get("dataVigenciaInicio")
            or item.get("dataVigenciaInicial")
            or "",
            vigencia_fim=item.get("dataVigenciaFim")
            or item.get("dataVigenciaFinal")
            or "",
            uf=unidade.get("ufSigla", "") or "",
            cidade=unidade.get("municipioNome", "") or "",
            orgao=orgao.get("razaoSocial", "") or item.get("nomeRazaoSocialFornecedor", ""),
            objeto=item.get("objetoContrato", "") or "",
            valor=float(item.get("valorGlobal") or item.get("valorInicial") or 0),
            link=link,
            link_edital=link_edital,
            link_resultado=link,
            link_contrato=link,
            cnpj_vencedor=_somente_digitos(item.get("niFornecedor", "")),
            nome_vencedor=item.get("nomeRazaoSocialFornecedor", "") or "",
            modalidade=tipo_contrato,
            numero_controle=item.get("numeroControlePNCP", "") or "",
            numero_documento=str(item.get("numeroContratoEmpenho", "") or ""),
            processo=item.get("processo", "") or "",
            orgao_cnpj=orgao_cnpj,
            ano_compra=ano,
            sequencial_compra=seq,
            numero_retificacao=retificacoes,
            link_origem=item.get("linkSistemaOrigem") or "",
            metadados={
                "processo": item.get("processo", ""),
                "numero_controle_compra": controle_compra,
                "data_atualizacao": item.get("dataAtualizacao", ""),
            },
        )

    # ----------------------------------------------------------------- editais
    def _coletar_editais(self) -> list[RegistroLicitacao]:
        data_ini, data_fim = self.config.datas_pncp()
        registros: list[RegistroLicitacao] = []
        for modalidade in self.config.modalidades:
            self._avisar(f"Editais PNCP: modalidade {modalidade} ({data_ini} a {data_fim})...")
            for pagina in range(1, self.config.max_paginas + 1):
                payload = self._paginar(
                    f"{BASE_CONSULTA}/contratacoes/publicacao",
                    {
                        "dataInicial": data_ini,
                        "dataFinal": data_fim,
                        "codigoModalidadeContratacao": modalidade,
                    },
                    pagina,
                )
                if payload is None:
                    break
                itens = payload.get("data") or []
                if not itens:
                    break
                for item in itens:
                    registro = self._normalizar_edital(item)
                    if registro and self._passa_filtros(registro):
                        registros.append(registro)
                total_paginas = payload.get("totalPaginas") or 0
                self._avisar(
                    f"Editais PNCP (modalidade {modalidade}): página {pagina}"
                    + (f"/{total_paginas}" if total_paginas else "")
                    + f" — {len(registros)} registros na janela"
                )
                if self._ultima_pagina(payload, pagina):
                    break
        self._log(f"editais coletados: {len(registros)}")
        return registros

    def _normalizar_edital(self, item: dict[str, Any]) -> RegistroLicitacao | None:
        orgao = item.get("orgaoEntidade") or {}
        unidade = item.get("unidadeOrgao") or {}
        orgao_cnpj = orgao.get("cnpj", "")
        ano = item.get("anoCompra")
        seq = item.get("sequencialCompra")
        link = (
            f"{BASE_APP}/editais/{orgao_cnpj}/{ano}/{seq}"
            if orgao_cnpj and ano and seq
            else ""
        )
        valor = item.get("valorTotalHomologado") or item.get("valorTotalEstimado") or 0
        return RegistroLicitacao(
            fonte=self.nome,
            tipo_registro="Licitação Nova",
            data_evento=item.get("dataPublicacaoPncp") or item.get("dataInclusao") or "",
            data_resultado=item.get("dataPublicacaoPncp") or item.get("dataInclusao") or "",
            uf=unidade.get("ufSigla", "") or "",
            cidade=unidade.get("municipioNome", "") or "",
            orgao=orgao.get("razaoSocial", "") or "",
            objeto=item.get("objetoCompra", "") or "",
            valor=float(valor or 0),
            link=link,
            link_edital=link,
            link_resultado=link,
            cnpj_vencedor="",
            nome_vencedor="",
            modalidade=item.get("modalidadeNome", "") or "",
            numero_controle=item.get("numeroControlePNCP", "") or "",
            numero_documento=item.get("numeroCompra", "") or "",
            processo=item.get("processo", "") or "",
            orgao_cnpj=orgao_cnpj,
            ano_compra=ano,
            sequencial_compra=seq,
            link_origem=item.get("linkSistemaOrigem") or "",
            metadados={
                "processo": item.get("processo", ""),
                "data_encerramento": item.get("dataEncerramentoProposta", ""),
            },
        )

    # ---------------------------------------------------------------- anexos
    def obter_documentos(self, registro: RegistroLicitacao) -> list[dict[str, str]]:
        """Documentos (edital, contrato, minuta) de um registro do PNCP."""
        if not registro.orgao_cnpj or not registro.ano_compra or not registro.sequencial_compra:
            return []
        if registro.tipo_registro in ("Contrato Homologado", "Termo Aditado") or registro.cnpj_vencedor:
            recurso = "contratos"
        else:
            recurso = "compras"
        url = (
            f"{BASE_API}/orgaos/{registro.orgao_cnpj}/{recurso}/"
            f"{registro.ano_compra}/{registro.sequencial_compra}/arquivos"
        )
        dados = self.http.get(url) or []
        if not isinstance(dados, list):
            return []
        documentos = []
        for doc in dados:
            documentos.append(
                {
                    "titulo": doc.get("titulo", ""),
                    "tipo": doc.get("tipoDocumentoNome", ""),
                    "url": doc.get("url") or doc.get("uri") or "",
                }
            )
        return documentos

    def obter_termos_aditivos(self, registro: RegistroLicitacao) -> list[dict[str, Any]]:
        """Termos aditivos de um contrato (prorrogação, valor, escopo)."""
        if not registro.orgao_cnpj or not registro.ano_compra or not registro.sequencial_compra:
            return []
        url = (
            f"{BASE_API}/orgaos/{registro.orgao_cnpj}/contratos/"
            f"{registro.ano_compra}/{registro.sequencial_compra}/termos"
        )
        dados = self.http.get(url) or []
        return dados if isinstance(dados, list) else []

    # ------------------------------------------------------------------ apoio
    def _paginar(self, url: str, params: dict[str, Any], pagina: int) -> dict[str, Any] | None:
        params = {**params, "pagina": pagina, "tamanhoPagina": self.config.tamanho_pagina}
        if self.config.verboso:
            self._log(f"GET {url} página {pagina}")
        payload = self.http.get(url, params=params)
        if pagina > 1:
            self.http.dormir(self.config.pausa_entre_requisicoes)
        if not isinstance(payload, dict) or not payload.get("data"):
            if isinstance(payload, dict) and payload.get("status") == 400:
                self._log(f"parâmetro inválido: {payload.get('message')}")
            return None
        return payload

    @staticmethod
    def _ultima_pagina(payload: dict[str, Any], pagina: int) -> bool:
        total_paginas = payload.get("totalPaginas") or 0
        if total_paginas and pagina >= total_paginas:
            return True
        itens = payload.get("data") or []
        tamanho = payload.get("tamanhoPagina") or len(itens)
        return len(itens) < tamanho

    def _passa_filtros(self, registro: RegistroLicitacao) -> bool:
        if registro.valor and registro.valor < self.config.valor_minimo:
            return False
        if self.config.ufs and registro.uf and registro.uf.upper() not in self.config.ufs:
            return False
        if self.config.filtrar_por_ramo and self.config.ramos_palavras_chave:
            if not registro_do_ramo(registro, self.config.ramos_palavras_chave):
                return False
        return True


def _somente_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _link_edital_por_controle(controle: str) -> str:
    """Converte o número de controle da compra em link do edital no PNCP.

    Formato usual: ``12345678000199-1-000001/2025``.
    """
    achado = re.match(r"^(\d{14})-\d+-(\d+)/(\d{4})$", (controle or "").strip())
    if not achado:
        return ""
    cnpj, sequencial, ano = achado.groups()
    return f"{BASE_APP}/editais/{cnpj}/{ano}/{int(sequencial)}"
