"""Interface de linha de comando (CLI) parametrizável.

Exemplos:
    python -m seguro_garantia --dias 30 --valor-minimo 1000000
    python -m seguro_garantia --ufs SP,RJ --web --limite 50
    python -m seguro_garantia --data-referencia 30/09/2026 --csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from .config import carregar_config
from .pipeline import executar


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seguro-garantia",
        description="Consolida licitações e enriquece contatos para prospecção de Seguro Garantia.",
    )
    p.add_argument("--dias", type=int, help="janela de busca em dias (DIAS_RETROATIVOS)")
    p.add_argument(
        "--data-referencia",
        help="data final da janela no formato DD/MM/AAAA (padrão: hoje)",
    )
    p.add_argument("--valor-minimo", type=float, help="valor mínimo do contrato em R$")
    p.add_argument("--percentual-garantia", type=float, help="percentual p/ estimar a garantia (ex.: 0.05)")
    p.add_argument("--ufs", help="UFs separadas por vírgula (ex.: SP,RJ,MG). Vazio = Brasil")
    p.add_argument("--modalidades", help="modalidades PNCP p/ editais (ex.: 4,5,6,7)")
    p.add_argument("--sem-editais", action="store_true", help="não buscar editais abertos")
    p.add_argument(
        "--sem-editais-sem-vencedor",
        action="store_true",
        help="excluir editais ainda sem vencedor (sem CNPJ)",
    )
    p.add_argument("--compras-gov", action="store_true", help="incluir a fonte Compras.gov.br")
    p.add_argument("--sem-ramo", dest="filtrar_por_ramo", action="store_false", help="não filtrar por ramo de atividade")
    p.set_defaults(filtrar_por_ramo=None)
    p.add_argument("--cnae", action="store_true", help="filtrar pelo CNAE da empresa (após CNPJ)")
    p.add_argument("--exigir-garantia-texto", action="store_true", help="descartar registro sem garantia explícita no texto (lê PDF)")
    p.add_argument("--filtro-estrito", action="store_true", help="manter só registros com cláusula de garantia")
    p.add_argument("--ler-pdf", action="store_true", help="ler o PDF do edital em busca da cláusula")
    # Fontes complementares
    p.add_argument("--enegocios-sp", action="store_true", help="incluir e-Negócios SP (busca por CNPJ)")
    p.add_argument("--enegocios-cnpjs", help="CNPJs extras para o e-Negócios (vírgula)")
    p.add_argument("--enegocios-detalhes", action="store_true", help="abrir a página de detalhe do e-Negócios")
    p.add_argument("--licitacoes-e", action="store_true", help="incluir Licitações-E (BB)")
    p.add_argument("--caixa", action="store_true", help="incluir CAIXA")
    p.add_argument("--bndes", action="store_true", help="incluir BNDES")
    p.add_argument("--petronect", action="store_true", help="incluir Petronect (Petrobras)")
    p.add_argument("--bec-sp", action="store_true", help="incluir BEC/SP")
    p.add_argument("--compras-rs", action="store_true", help="incluir ComprasRS")
    p.add_argument("--compras-publicas", action="store_true", help="incluir Compras Públicas")
    p.add_argument("--bll-compras", action="store_true", help="incluir BLL Compras")
    # Enriquecimento
    p.add_argument("--sem-enriquecimento", dest="enriquecer", action="store_false", help="não enriquecer CNPJ")
    p.add_argument("--receitaws", action="store_true", help="usar ReceitaWS como fallback")
    grupo_web = p.add_mutually_exclusive_group()
    grupo_web.add_argument("--web", dest="enriquecer_web", action="store_true", help="enriquecer contatos na web (padrão: ligado)")
    grupo_web.add_argument("--sem-web", dest="enriquecer_web", action="store_false", help="desligar enriquecimento web")
    p.set_defaults(enriquecer_web=None)
    p.add_argument("--web-max", type=int, help="teto de empresas no enriquecimento web (0 = sem teto)")
    p.add_argument("--workers", type=int, help="paralelismo (threads) do enriquecimento")
    p.add_argument("--sem-csv", dest="gerar_csv", action="store_false", help="não gerar CSV")
    p.add_argument("--saida", help="diretório de saída (DIRETORIO_SAIDA)")
    p.add_argument("--nome-arquivo", help="nome-base do arquivo de saída")
    p.add_argument("--max-paginas", type=int, help="teto de páginas por consulta")
    p.add_argument("--tamanho-pagina", type=int, help="registros por página da API")
    p.add_argument("--pausa", type=float, help="segundos entre requisições ao PNCP")
    p.add_argument("--limite", type=int, help="teto de registros finais (útil p/ testes)")
    p.add_argument("-v", "--verboso", action="store_true", help="log detalhado")
    return p


def executar_cli(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    overrides = {
        "dias_retroativos": args.dias,
        "valor_minimo": args.valor_minimo,
        "percentual_garantia": args.percentual_garantia,
        "ufs": _lista(args.ufs),
        "modalidades": _lista_int(args.modalidades),
        "buscar_editais": False if args.sem_editais else None,
        "incluir_editais_sem_vencedor": False if args.sem_editais_sem_vencedor else None,
        "usar_compras_gov": True if args.compras_gov else None,
        "filtrar_por_ramo": args.filtrar_por_ramo,
        "filtrar_por_cnae": True if args.cnae else None,
        "exigir_garantia_no_texto": True if args.exigir_garantia_texto else None,
        "filtro_garantia_estrito": True if args.filtro_estrito else None,
        "ler_anexos_pdf": True if args.ler_pdf else None,
        "usar_enegocios_sp": True if args.enegocios_sp else None,
        "enegocios_cnpjs": _lista(args.enegocios_cnpjs),
        "enegocios_detalhes": True if args.enegocios_detalhes else None,
        "usar_licitacoes_e": True if args.licitacoes_e else None,
        "usar_caixa": True if args.caixa else None,
        "usar_bndes": True if args.bndes else None,
        "usar_petronect": True if args.petronect else None,
        "usar_bec_sp": True if args.bec_sp else None,
        "usar_compras_rs": True if args.compras_rs else None,
        "usar_compras_publicas": True if args.compras_publicas else None,
        "usar_bll_compras": True if args.bll_compras else None,
        "enriquecer_cnpj": None if args.enriquecer else False,
        "usar_receitaws": True if args.receitaws else None,
        "enriquecer_web": args.enriquecer_web,
        "web_max_empresas": args.web_max,
        "max_workers": args.workers,
        "gerar_csv": None if args.gerar_csv else False,
        "diretorio_saida": args.saida,
        "nome_arquivo": args.nome_arquivo,
        "max_paginas": args.max_paginas,
        "tamanho_pagina": args.tamanho_pagina,
        "pausa_entre_requisicoes": args.pausa,
        "limite": args.limite,
        "verboso": args.verboso or None,
    }
    if args.data_referencia:
        overrides["data_referencia"] = _data(args.data_referencia)

    config = carregar_config(**overrides)

    def progresso(mensagem: str, atual: int = 0, total: int = 0) -> None:
        if atual and total:
            print(f"\r{mensagem} [{atual}/{total}]", end="", flush=True)
            if atual == total:
                print()
        else:
            print(mensagem, flush=True)

    try:
        resultado = executar(config, progresso)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        return 130

    print("\n=== Resumo ===")
    print(f"Registros brutos : {resultado.total_bruto}")
    print(f"Linhas exportadas: {resultado.total_final}")
    print(f"Duração          : {resultado.duracao_segundos:.0f}s")
    for formato, caminho in resultado.arquivos.items():
        print(f"Arquivo ({formato})  : {caminho}")
    return 0


def _data(valor: str) -> date:
    return datetime.strptime(valor.strip(), "%d/%m/%Y").date()


def _lista(valor: str | None):
    if not valor:
        return None
    return [v.strip() for v in valor.split(",") if v.strip()]


def _lista_int(valor: str | None):
    if not valor:
        return None
    return [int(v.strip()) for v in valor.replace(";", ",").split(",") if v.strip()]


if __name__ == "__main__":
    raise SystemExit(executar_cli())
