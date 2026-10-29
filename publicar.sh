#!/usr/bin/env bash
# Publica a interface (Streamlit) em um link HTTPS temporário via Cloudflare Tunnel.
#
# Uso:
#   ./publicar.sh              # sobe o app local + túnel e mostra o link
#   APP_SENHA=minhasenha ./publicar.sh   # exige senha para entrar
#
# O link gerado é do tipo https://algo-aleatorio.trycloudflare.com e MUDA a cada
# vez que o túnel é reiniciado. Ele só funciona enquanto este computador estiver
# ligado e com internet. Para um link fixo (com domínio próprio), veja o README.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PORTA="${PORTA:-8501}"
LOG_APP="/tmp/seguro_garantia_app.log"
LOG_TUNEL="/tmp/seguro_garantia_tunel.log"
ARQ_URL="/tmp/seguro_garantia_url.txt"

parar_ao_sair() {
  echo
  echo "Encerrando o túnel público..."
  pkill -f "cloudflared tunnel --url http://localhost:${PORTA}" 2>/dev/null || true
  rm -f "$ARQ_URL"
}

# 1) Sobe a interface local, se ainda não estiver rodando.
if curl -s -o /dev/null --max-time 2 "http://localhost:${PORTA}"; then
  echo "Interface já estava rodando em http://localhost:${PORTA}"
else
  echo "Subindo a interface local (porta ${PORTA})..."
  setsid nohup python3 -m streamlit run app.py \
    --server.port "$PORTA" \
    --server.headless true \
    --server.address 127.0.0.1 \
    > "$LOG_APP" 2>&1 < /dev/null &

  for _ in $(seq 1 40); do
    if curl -s -o /dev/null --max-time 2 "http://localhost:${PORTA}"; then break; fi
    sleep 1
  done

  if ! curl -s -o /dev/null --max-time 2 "http://localhost:${PORTA}"; then
    echo "ERRO: a interface não subiu. Veja o log: $LOG_APP" >&2
    exit 1
  fi
fi

# 2) Abre o túnel do Cloudflare e descobre o link público.
echo "Abrindo túnel do Cloudflare..."
: > "$LOG_TUNEL"
setsid nohup cloudflared tunnel --no-autoupdate \
  --url "http://localhost:${PORTA}" \
  > "$LOG_TUNEL" 2>&1 < /dev/null &
TUNEL_PID=$!

trap parar_ao_sair EXIT INT TERM

URL=""
for _ in $(seq 1 45); do
  URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_TUNEL" | head -1 || true)"
  if [ -n "$URL" ]; then break; fi
  sleep 1
done

if [ -z "$URL" ]; then
  echo "ERRO: não foi possível obter o link público. Veja o log: $LOG_TUNEL" >&2
  exit 1
fi

echo "$URL" > "$ARQ_URL"

echo
echo "=============================================================="
echo "  LINK PÚBLICO: $URL"
echo "=============================================================="
echo "  Local:      http://localhost:${PORTA}"
echo "  Este link funciona enquanto este computador estiver ligado."
echo "  Pressione Ctrl+C para encerrar o acesso público."
echo

xdg-open "$URL" >/dev/null 2>&1 || true

# Mantém o túnel vivo até o usuário encerrar.
wait "$TUNEL_PID" 2>/dev/null || sleep infinity
