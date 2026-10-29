#!/usr/bin/env bash
# Atalho para gerar a carteira de prospecção de Seguro Garantia.
# Ajuste as variáveis abaixo ou passe os argumentos desejados para o script.
#
# Exemplos:
#   ./rodar.sh
#   ./rodar.sh --dias 7 --valor-minimo 500000 --ufs SP,RJ
#   ./rodar.sh --web --limite 50

set -euo pipefail
cd "$(dirname "$0")"

DIAS="${DIAS:-30}"
VALOR_MINIMO="${VALOR_MINIMO:-0}"
PAUSA="${PAUSA:-3}"

exec python3 -m seguro_garantia \
  --dias "$DIAS" \
  --valor-minimo "$VALOR_MINIMO" \
  --pausa "$PAUSA" \
  "$@"
