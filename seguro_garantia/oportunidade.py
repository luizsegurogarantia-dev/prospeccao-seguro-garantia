"""Qualificação comercial das oportunidades de seguro-garantia.

Concentra regras puras (sem rede) para:
- classificar a exigência de garantia em Confirmada / Provável / Não encontrada /
  Não verificada, sempre com evidência e justificativa;
- estimar um score de confiança dos dados;
- definir prioridade comercial e listar pendências;
- extrair prazo de execução e formatar a vigência contratual.
"""

from __future__ import annotations

import re
from typing import Any

from .filters import (
    encontrar_palavras,
    extrair_clausula_garantia,
    normalizar,
)
from .models import DadosCNPJ, RegistroLicitacao
from .validacao import formatar_data, parse_data, validar_cnpj

STATUS_CONFIRMADA = "Confirmada"
STATUS_PROVAVEL = "Provável"
STATUS_NAO_ENCONTRADA = "Não encontrada"
STATUS_NAO_VERIFICADA = "Não verificada"

STATUS_VALIDOS = (
    STATUS_CONFIRMADA,
    STATUS_PROVAVEL,
    STATUS_NAO_ENCONTRADA,
    STATUS_NAO_VERIFICADA,
)

RE_TRECHO_GARANTIA = re.compile(
    r"(seguro[\s-]*garantia|garantia\s+contratual|garantia\s+de\s+execu[çc][ãa]o|"
    r"cau[çc][ãa]o|fian[çc]a\s+banc[áa]ria|garantia)",
    re.IGNORECASE,
)
RE_PRAZO_EXECUCAO = re.compile(
    r"(?:prazo\s+(?:de\s+)?execu[çc][ãa]o|prazo\s+contratual|prazo\s+de\s+vig[êe]ncia)"
    r"[^.]{0,90}?(\d{1,3})\s*(dias|meses|anos)",
    re.IGNORECASE,
)
RE_VIGENCIA_EXECUCAO = re.compile(
    r"vig[êe]ncia[^.]{0,60}?(\d{1,3})\s*(dias|meses|anos)",
    re.IGNORECASE,
)

SETORES_CNAE = (
    ("41", "Construção e engenharia"),
    ("42", "Construção e engenharia"),
    ("43", "Construção e engenharia"),
    ("71", "Engenharia e arquitetura"),
    ("33", "Indústria e manutenção"),
    ("38", "Resíduos e saneamento"),
    ("39", "Resíduos e saneamento"),
    ("80", "Segurança patrimonial"),
    ("81", "Serviços prediais e limpeza"),
    ("49", "Transporte e logística"),
    ("52", "Transporte e logística"),
    ("53", "Transporte e logística"),
    ("62", "Tecnologia da informação"),
    ("63", "Tecnologia da informação"),
    ("86", "Saúde"),
    ("87", "Saúde"),
    ("10", "Alimentos e suprimentos"),
    ("11", "Alimentos e suprimentos"),
    ("46", "Comércio e suprimentos"),
    ("47", "Comércio e suprimentos"),
    ("70", "Consultoria e serviços"),
    ("82", "Serviços administrativos"),
)

SETORES_OBJETO = (
    ("Construção e engenharia", ("obra", "engenharia", "constru", "reforma", "paviment", "saneamento", "drenagem", "edifica")),
    ("Serviços prediais e limpeza", ("limpeza", "conserva", "manuten", "servicos prediais", "jardinagem", "portaria")),
    ("Segurança patrimonial", ("vigilancia", "seguranca patrimonial", "porteiro", "monitoramento")),
    ("Tecnologia da informação", ("software", "sistema", "ti ", "informatica", "computador", "rede", "nuvem", "licenca")),
    ("Saúde", ("saude", "medicamento", "hospital", "clinica", "ambulancia", "equipamento medico")),
    ("Transporte e logística", ("transporte", "logistica", "frota", "veiculo", "combustivel", "frete")),
    ("Alimentos e suprimentos", ("alimento", "merenda", "refeicao", "genero", "material de limpeza")),
    ("Engenharia e arquitetura", ("projeto", "arquitetura", "fiscalizacao de obra", "gerenciamento de obra")),
    ("Consultoria e serviços", ("consultoria", "assessoria", "capacitacao", "treinamento", "auditoria")),
    ("Indústria e manutenção", ("manutencao industrial", "equipamento", "maquina", "peca", "usinagem")),
)


def trecho_evidencia(texto: str, limite: int = 900) -> str:
    """Recorta até três trechos ao redor de menções a garantia."""
    if not texto:
        return ""
    achados: list[str] = []
    for achado in RE_TRECHO_GARANTIA.finditer(texto):
        inicio = max(0, achado.start() - 90)
        fim = min(len(texto), achado.end() + 260)
        trecho = re.sub(r"\s+", " ", texto[inicio:fim]).strip()
        if trecho and trecho not in achados:
            achados.append(trecho)
        if len(achados) >= 3:
            break
    return " | ".join(achados)[:limite]


def classificar_garantia(
    registro: RegistroLicitacao,
    texto_lido: bool,
    palavras_chave: list[str],
) -> dict[str, str]:
    """Classifica a exigência de garantia **sem presumir** o que não foi lido.

    - ``Confirmada``: o texto analisado traz modalidade e percentual/valor ou
      menção expressa à garantia de execução;
    - ``Provável``: o texto cita garantia/caução, mas sem elementos suficientes;
    - ``Não encontrada``: o texto foi analisado e não menciona garantia;
    - ``Não verificada``: não houve leitura do edital/contrato.
    """
    texto = registro.texto_extra or ""
    clausula = extrair_clausula_garantia(texto) if texto_lido else {
        "percentual": "",
        "prazo": "",
        "modalidade": "",
        "vigencia": "",
    }
    evidencia = trecho_evidencia(texto) if texto_lido else ""
    base = normalizar(texto)

    if texto_lido:
        tem_modalidade = bool(clausula.get("modalidade"))
        tem_percentual = bool(clausula.get("percentual"))
        tem_execucao = any(
            termo in base
            for termo in (
                "garantia de execucao",
                "garantia contratual",
                "garantia para execucao",
                "garantir a execucao",
                "art. 96",
            )
        )
        if tem_modalidade and (tem_percentual or tem_execucao):
            status = STATUS_CONFIRMADA
            justificativa = "Texto analisado com modalidade de garantia identificada."
        elif encontrar_palavras(texto, palavras_chave):
            status = STATUS_PROVAVEL
            justificativa = (
                "Texto menciona garantia/caução, mas não confirma modalidade e "
                "percentual/valor; requer conferência manual."
            )
        else:
            status = STATUS_NAO_ENCONTRADA
            justificativa = "Texto analisado e nenhuma menção a garantia foi encontrada."
    else:
        status = STATUS_NAO_VERIFICADA
        justificativa = (
            "Texto do edital/contrato não analisado; ative a leitura de anexos "
            "ou confira o link para confirmar a exigência."
        )
        if encontrar_palavras(registro.objeto or "", palavras_chave):
            status = STATUS_PROVAVEL
            justificativa = (
                "O objeto menciona garantia, mas o edital/contrato não foi lido; "
                "confirme a exigência na fonte."
            )
            evidencia = trecho_evidencia(registro.objeto or "")

    return {
        "status": status,
        "evidencias": evidencia,
        "justificativa": justificativa,
        **{f"clausula_{k}": v for k, v in clausula.items()},
    }


def setor_atividade(dados: DadosCNPJ | None, objeto: str = "") -> str:
    """Setor aproximado, priorizando o CNAE e usando o objeto como reserva."""
    cnae = (dados.cnae_principal if dados else "") or ""
    digitos = "".join(c for c in cnae if c.isdigit())[:4]
    for prefixo, setor in SETORES_CNAE:
        if digitos.startswith(prefixo):
            return setor

    base = normalizar(objeto)
    for setor, termos in SETORES_OBJETO:
        if any(normalizar(termo) in base for termo in termos):
            return setor
    return "Outros"


def extrair_prazo_execucao(texto: str) -> str:
    """Extrai o prazo de execução contratual do texto, quando declarado."""
    if not texto:
        return ""
    achado = RE_PRAZO_EXECUCAO.search(texto) or RE_VIGENCIA_EXECUCAO.search(texto)
    if not achado:
        return ""
    return f"{int(achado.group(1))} {achado.group(2).lower()}"


def prazo_por_vigencia(inicio: str, fim: str) -> str:
    """Estimativa explícita do prazo quando só as datas de vigência existem.

    O rótulo ``(vigência)`` deixa claro que o número foi derivado do intervalo
    contratual e não de uma cláusula de prazo de execução.
    """
    data_inicio = parse_data(inicio)
    data_fim = parse_data(fim)
    if not data_inicio or not data_fim:
        return ""
    dias = (data_fim - data_inicio).days
    if dias <= 0:
        return ""
    return f"{dias} dias (vigência)"


def formatar_vigencia(inicio: str, fim: str) -> str:
    """Formata a vigência como 'DD/MM/AAAA a DD/MM/AAAA (N dias)'."""
    data_inicio = parse_data(inicio)
    data_fim = parse_data(fim)
    if data_inicio and data_fim:
        dias = (data_fim - data_inicio).days
        sufixo = f" ({dias} dias)" if dias > 0 else ""
        return f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}{sufixo}"
    if data_inicio:
        return f"Início em {data_inicio.strftime('%d/%m/%Y')}"
    if data_fim:
        return f"Fim em {data_fim.strftime('%d/%m/%Y')}"
    return ""


def calcular_score_confianca(
    registro: RegistroLicitacao,
    dados: DadosCNPJ | None,
    contatos: dict[str, Any] | None,
    status_garantia: str,
    setor: str = "",
) -> int:
    """Score de 0 a 100 para a qualidade dos dados da oportunidade."""
    pontos = 0
    cnpj = registro.cnpj_vencedor or (dados.cnpj if dados else "")
    if validar_cnpj(cnpj):
        pontos += 15
    if registro.nome_vencedor or (dados and dados.razao_social):
        pontos += 10
    if registro.valor and registro.valor > 0:
        pontos += 10
    if parse_data(registro.data_resultado or registro.data_evento):
        pontos += 10
    if registro.fonte in ("PNCP", "Compras.gov.br", "e-Negócios SP"):
        pontos += 10
    pontos += {
        STATUS_CONFIRMADA: 20,
        STATUS_PROVAVEL: 12,
        STATUS_NAO_ENCONTRADA: 8,
        STATUS_NAO_VERIFICADA: 0,
    }.get(status_garantia, 0)
    links = [
        registro.link_edital,
        registro.link_resultado,
        registro.link_contrato,
        registro.link_ata,
        registro.link,
        registro.link_origem,
    ]
    links_validos = len({l for l in links if l})
    if links_validos >= 2:
        pontos += 10
    elif links_validos == 1:
        pontos += 5
    if contatos and (
        contatos.get("telefone")
        or contatos.get("celular")
        or contatos.get("emails")
    ):
        pontos += 10
    if registro.processo or registro.numero_documento:
        pontos += 5
    if registro.vigencia_inicio or registro.vigencia_fim:
        pontos += 5
    if setor and setor != "Outros":
        pontos += 5
    if dados and dados.sancoes_verificado:
        pontos += 5
    return max(0, min(100, pontos))


def prioridade_comercial(
    registro: RegistroLicitacao,
    status_garantia: str,
    score: int,
    valor_garantia: float,
    sancoes: list[str] | None = None,
) -> str:
    """Classifica a prioridade em Alta, Média ou Baixa.

    A prioridade combina sinal de garantia, valor potencial, confiança dos
    dados e existência de sanção ativa (que rebaixa a oportunidade).
    """
    if not registro.cnpj_vencedor and not registro.nome_vencedor:
        return "Baixa"
    if sancoes:
        return "Baixa"
    valor = registro.valor or 0.0
    if status_garantia == STATUS_CONFIRMADA:
        if valor_garantia >= 50_000 or valor >= 1_000_000 or score >= 65:
            return "Alta"
        return "Média"
    if status_garantia == STATUS_PROVAVEL:
        if valor_garantia >= 100_000 or valor >= 2_000_000 or score >= 75:
            return "Alta"
        return "Média"
    if score >= 70 and valor >= 500_000:
        return "Média"
    return "Baixa"


def pendencias(
    registro: RegistroLicitacao,
    dados: DadosCNPJ | None,
    contatos: dict[str, Any] | None,
    status_garantia: str,
) -> str:
    """Lista curta de dados ausentes/inconsistências para conferência manual."""
    itens: list[str] = []
    cnpj = registro.cnpj_vencedor or ""
    if not cnpj:
        itens.append("CNPJ do vencedor ausente")
    elif not validar_cnpj(cnpj):
        itens.append("CNPJ inválido")
    if not parse_data(registro.data_resultado or registro.data_evento):
        itens.append("data do resultado ausente")
    if not registro.valor:
        itens.append("valor adjudicado ausente")
    if not (registro.link_edital or registro.link or registro.link_origem):
        itens.append("link do edital ausente")
    if not (registro.link_contrato or registro.link):
        itens.append("link do contrato ausente")
    if not (registro.processo or registro.numero_documento):
        itens.append("processo/edital não identificado")
    if not (
        contatos
        and (contatos.get("telefone") or contatos.get("celular") or contatos.get("emails"))
    ):
        itens.append("sem contato público localizado")
    if status_garantia == STATUS_NAO_VERIFICADA:
        itens.append("garantia não verificada no texto")
    elif status_garantia == STATUS_PROVAVEL:
        itens.append("garantia provável: confirmar no edital")
    if dados and not dados.sancoes_verificado:
        itens.append("sanções não verificadas")
    return "; ".join(itens)


def resumo_links(registro: RegistroLicitacao) -> str:
    """Monta a lista de fontes/links usados para comprovar os dados."""
    partes: list[str] = []
    rotulos = (
        ("Edital", registro.link_edital),
        ("Resultado", registro.link_resultado),
        ("Contrato", registro.link_contrato or registro.link),
        ("Ata", registro.link_ata),
        ("Sistema de origem", registro.link_origem),
    )
    for rotulo, url in rotulos:
        if url and url not in [p.split(": ", 1)[-1] for p in partes]:
            partes.append(f"{rotulo}: {url}")
    return " | ".join(partes)


def formatar_percentual(valor: str) -> str:
    """Normaliza texto de percentual para exibição."""
    return str(valor or "").strip()
