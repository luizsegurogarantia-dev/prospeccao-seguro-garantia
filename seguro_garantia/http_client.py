"""Cliente HTTP com headers de navegador, retries e tratamento de rate-limit.

O PNCP aplica rate-limit agressivo (HTTP 429) e alguns portais bloqueiam
requisições sem User-Agent de navegador. Este cliente centraliza:
- headers realistas;
- retries automáticos para erros 5xx;
- espera progressiva (e respeito ao `Retry-After`) no 429;
- retorno tolerante a falhas (`None` em vez de exceção).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("seguro_garantia.http")

Aviso = Callable[[str], None]

HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


class ClienteHTTP:
    def __init__(
        self,
        timeout: int = 30,
        max_tentativas: int = 4,
        pausa_base: float = 3.0,
        espera_429_base: float = 10.0,
        espera_429_maxima: float = 120.0,
        verboso: bool = False,
        aviso: Aviso | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_tentativas = max_tentativas
        self.pausa_base = pausa_base
        self.espera_429_base = espera_429_base
        self.espera_429_maxima = espera_429_maxima
        self.verboso = verboso
        self.aviso = aviso
        # Serializa avisos quando o cliente é usado por várias threads.
        self._lock = threading.Lock()

        self.session = requests.Session()
        self.session.headers.update(HEADERS_NAVEGADOR)
        # O adapter cuida apenas de falhas transitórias de gateway/rede. O 500
        # fica de fora porque, nas APIs de CNPJ, ele costuma indicar dado
        # indisponível — melhor falhar rápido do que insistir.
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry, pool_connections=10, pool_maxsize=10
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        as_json: bool = True,
        headers: dict[str, str] | None = None,
        permitir_404: bool = True,
    ) -> Any | None:
        """GET tolerante a falhas.

        Retorna o JSON (ou texto) em caso de sucesso e `None` quando esgotam as
        tentativas ou o recurso não existe.
        """
        for tentativa in range(1, self.max_tentativas + 1):
            try:
                resp = self.session.get(
                    url, params=params, timeout=self.timeout, headers=headers
                )
            except requests.RequestException as exc:
                espera = min(self.pausa_base * tentativa, 20)
                self._avisar(
                    f"erro de conexão ({exc}) — nova tentativa {tentativa}/"
                    f"{self.max_tentativas} em {espera:.0f}s"
                )
                time.sleep(espera)
                continue

            if resp.status_code == 429:
                espera = self._espera_429(resp, tentativa)
                self._avisar(
                    f"PNCP limitou as consultas (HTTP 429) — aguardando "
                    f"{espera:.0f}s (tentativa {tentativa}/{self.max_tentativas})"
                )
                time.sleep(espera)
                continue

            if resp.status_code == 404:
                if permitir_404:
                    return None
                return None

            if resp.status_code >= 400:
                self._log(
                    f"HTTP {resp.status_code} em {url} (tentativa {tentativa})"
                )
                # 400/401/403/404 normalmente são definitivos: não insiste.
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    return None
                # 5xx: pequena espera antes de tentar de novo.
                time.sleep(min(1.5 * tentativa, 6))
                continue

            if as_json:
                try:
                    return resp.json()
                except ValueError:
                    self._log(f"resposta não é JSON válido em {url}")
                    return None
            return resp.text

        return None

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        *,
        as_json: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """POST tolerante a falhas (usado em portais ASP.NET/WebForms)."""
        for tentativa in range(1, self.max_tentativas + 1):
            try:
                resp = self.session.post(
                    url, data=data, timeout=self.timeout, headers=headers
                )
            except requests.RequestException as exc:
                espera = min(self.pausa_base * tentativa, 20)
                self._avisar(
                    f"erro de conexão ({exc}) — nova tentativa {tentativa}/"
                    f"{self.max_tentativas} em {espera:.0f}s"
                )
                time.sleep(espera)
                continue

            if resp.status_code == 429:
                espera = self._espera_429(resp, tentativa)
                self._avisar(
                    f"Servidor limitou as consultas (HTTP 429) — aguardando "
                    f"{espera:.0f}s (tentativa {tentativa}/{self.max_tentativas})"
                )
                time.sleep(espera)
                continue

            if resp.status_code >= 400:
                self._log(f"HTTP {resp.status_code} em POST {url} (tentativa {tentativa})")
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    return None
                time.sleep(min(1.5 * tentativa, 6))
                continue

            if as_json:
                try:
                    return resp.json()
                except ValueError:
                    return None
            return resp.text

        return None

    def _espera_429(self, resp: requests.Response, tentativa: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), self.espera_429_maxima)
            except ValueError:
                pass
        return min(self.espera_429_base * (2 ** (tentativa - 1)), self.espera_429_maxima)

    def _log(self, msg: str) -> None:
        if self.verboso:
            log.warning(msg)
        else:
            log.debug(msg)

    def _avisar(self, msg: str) -> None:
        """Avisa o usuário (log + interface) sobre esperas/retentativas."""
        log.info(msg)
        if self.aviso:
            with self._lock:
                self.aviso(msg)

    def dormir(self, segundos: float) -> None:
        time.sleep(segundos)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ClienteHTTP":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
