#!/usr/bin/env bash
# Abre a interface (Streamlit) da aplicação de prospecção de Seguro Garantia.
# Se o aplicativo já estiver rodando, apenas abre o navegador na página.
# Dê dois cliques no atalho da área de trabalho ou execute este arquivo.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PORTA="${PORTA:-8501}"
URL="http://localhost:${PORTA}"
LOG="/tmp/seguro_garantia_app.log"

# Já está rodando? Então só abre o navegador.
if curl -s -o /dev/null --max-time 2 "$URL"; then
  xdg-open "$URL" >/dev/null 2>&1 || true
  exit 0
fi

# Sobe o servidor em segundo plano (continua rodando após fechar o atalho).
setsid nohup python3 -m streamlit run app.py \
  --server.port "$PORTA" \
  --server.headless true \
  > "$LOG" 2>&1 < /dev/null &

# Espera o servidor responder (até 40s) e abre o navegador.
for _ in $(seq 1 40); do
  if curl -s -o /dev/null --max-time 2 "$URL"; then
    break
  fi
  sleep 1
done

xdg-open "$URL" >/dev/null 2>&1 || true
