#!/usr/bin/env bash
# Igual ao publicar.sh, mas pergunta a senha de acesso antes de abrir o link.
# Deixe a senha em branco para publicar sem proteção.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

read -rsp 'Senha de acesso (Enter para publicar sem senha): ' SENHA
echo
export APP_SENHA="$SENHA"
exec ./publicar.sh
