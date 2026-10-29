"""Enriquecimento web: contatos diretos (telefone, celular/WhatsApp, e-mail).

Estratégia 100% baseada em fontes abertas, sem chaves de API:
1. Busca o nome/fantasia da empresa no Bing (HTML).
2. Abre as páginas candidatas (site da empresa e páginas de contato).
3. Extrai telefones, links de WhatsApp (`wa.me`) e e-mails por expressão regular.

É um processo *best-effort*: nem toda empresa expõe contato, e alguns sites
bloqueiam requisições automatizadas. Cada CNPJ é cacheado em disco, então rodar
de novo é instantâneo.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import socket
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup

from ..config import Config
from ..http_client import ClienteHTTP
from ..models import ContatoEnriquecido
from .email import DOMINIOS_PLACEHOLDER

log = logging.getLogger("seguro_garantia.web")

URL_BUSCA = "https://www.bing.com/search"

# Domínios que nunca são o site da empresa (redes sociais, agregadores, ruído).
DOMINIOS_IGNORADOS = (
    "duckduckgo.com",
    "bing.com",
    "microsoft.com",
    "msn.com",
    "google.",
    "bing.",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "linkedin.com",
    "pinterest.",
    "wikipedia.org",
    "reclameaqui.com.br",
    "cnpj.biz",
    "casadosdados.com.br",
    "econodata.com.br",
    "consultacnpj.com",
    "gov.br",
    "jusbrasil.com.br",
    "tiktok.com",
    # Diretórios/guias de telefone e agregadores de empresas (alto ruído).
    "guiatelefone.com",
    "guiamais.com.br",
    "guiafacil.com",
    "telelistas.net",
    "apontador.com.br",
    "solutudo.com.br",
    "listamais.com.br",
    "encontrapi.com",
    "telefoneempresas.com",
    "guiaempresas.com",
    "empresasddf.com",
    "b2c-listagem.com",
    "advdinheiro.com",
)

# Trechos de e-mail que não são contato comercial (placeholders/robôs).
EMAILS_IGNORADOS = (
    "noreply",
    "no-reply",
    "naoresponda",
    "sentry",
    "example",
    "wixpress",
    "domain.com",
    "email.com",
    "exemplo",
    "empresa.com",
    "dominio",
    "seudominio",
    "seusite",
    "seuemail",
    "suaempresa",
)

EXTENSOES_ARQUIVO = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    ".pdf", ".zip", ".ico", ".xml", ".woff", ".woff2", ".mp4",
)

RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
RE_TELEFONE = re.compile(
    r"(?:\+?55[\s\-]?)?\(?\b([1-9][0-9])\)?[\s.\-]?(9?\d{4})[\s.\-]?(\d{4})\b"
)
RE_WHATSAPP = re.compile(
    r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send\?phone=)(\+?\d{10,15})",
    re.IGNORECASE,
)


class EnriquecendorWeb:
    def __init__(self, http: ClienteHTTP, config: Config) -> None:
        self.http = http
        self.config = config
        self.diretorio_cache: Path = config.diretorio_cache_web
        self.diretorio_cache.mkdir(parents=True, exist_ok=True)

    def enriquecer(self, cnpj: str, razao_social: str, nome_fantasia: str = "") -> ContatoEnriquecido:
        cnpj_limpo = re.sub(r"\D", "", cnpj or "")
        vazio = ContatoEnriquecido(cnpj=cnpj_limpo)
        if not cnpj_limpo or not (razao_social or nome_fantasia):
            return vazio

        cache = self._ler_cache(cnpj_limpo)
        if cache is not None:
            return cache

        contato = ContatoEnriquecido(cnpj=cnpj_limpo)
        tokens = _tokens_empresa(razao_social, nome_fantasia)

        # Três consultas aumentam a chance de achar o site oficial e contatos
        # publicados em diretórios/anúncios que citam o CNPJ.
        resultados: list[dict[str, str]] = []
        for termo in _montar_consultas(cnpj_limpo, razao_social, nome_fantasia):
            resultados.extend(self._buscar(termo))
            self.http.dormir(self.config.pausa_web)

        compacto = _nome_compacto(razao_social, nome_fantasia)
        pontuados = self._pontuar_candidatos(resultados, tokens, cnpj_limpo, compacto)
        if pontuados:
            contato.site = pontuados[0][1]

        # Se a busca não achou o site, tenta adivinhar pelo próprio nome
        # (ex.: "RDS Engenharia" -> rdsengenharia.com.br) e confere o conteúdo.
        if not contato.site:
            descoberto = self._descobrir_site(razao_social, nome_fantasia, cnpj_limpo)
            if descoberto:
                contato.site = descoberto

        urls = [u for _, u in pontuados[:5]]

        sites = list(urls)
        if contato.site:
            base = _raiz_url(contato.site)
            sites = list({base, f"{base}/contato", f"{base}/fale-conosco", *sites})

        for url in sites:
            if len(contato.emails) >= 3 and (contato.whatsapp or contato.telefones):
                break
            self._extrair_de_pagina(url, contato)

        self._gravar_cache(cnpj_limpo, contato)
        return contato

    # --------------------------------------------------------- busca (Bing)
    def _buscar(self, termo: str) -> list[dict[str, str]]:
        html = self.http.get(
            URL_BUSCA,
            params={"q": termo, "count": 20, "setlang": "pt-br"},
            as_json=False,
        )
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        resultados = []
        for bloco in soup.select("li.b_algo"):
            link = bloco.select_one("h2 a") or bloco.select_one("a")
            if not link:
                continue
            url = _desembrulhar_bing(link.get("href", ""))
            if not url:
                continue
            snippet_el = bloco.select_one(".b_caption p, p")
            resultados.append(
                {
                    "url": url,
                    "titulo": link.get_text(" ", strip=True),
                    "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
                }
            )
        return resultados

    @staticmethod
    def _pontuar_candidatos(
        resultados: list[dict[str, str]],
        tokens: set[str],
        cnpj: str = "",
        nome_compacto: str = "",
    ) -> list[tuple[int, str]]:
        """Pontua cada domínio pela semelhança com o nome/CNPJ da empresa.

        Só aceita domínios com um sinal FORTE, para não confundir a empresa com
        concorrentes que compartilham uma palavra genérica:

        - o próprio CNPJ aparece no texto/domínio; ou
        - o domínio reproduz o nome da empresa "grudado" (ex.: rdsengenharia
          para "RDS Engenharia"); ou
        - pelo menos DOIS termos do nome batem no domínio/título.
        """
        cnpj_digitos = re.sub(r"\D", "", cnpj or "")
        melhores: dict[str, tuple[int, str]] = {}
        for r in resultados:
            url = r["url"]
            dominio = urllib.parse.urlparse(url).netloc.lower()
            if any(ruido in dominio for ruido in DOMINIOS_IGNORADOS):
                continue
            if url.lower().endswith(EXTENSOES_ARQUIVO):
                continue
            dominio_limpo = dominio.replace("www.", "")
            # Páginas de consulta de CNPJ contêm o número e seriam aceitas como
            # "site da empresa"; nunca são o site oficial.
            if "cnpj" in dominio_limpo:
                continue
            titulo = r.get("titulo", "")
            texto = f"{titulo} {r.get('snippet', '')} {dominio_limpo}"
            raiz = dominio_limpo.split(".")[0]

            cnpj_match = bool(cnpj_digitos) and _contem_cnpj(texto, cnpj_digitos)
            slug_match = bool(nome_compacto) and len(raiz) >= 6 and (
                raiz in nome_compacto or nome_compacto.startswith(raiz)
            )
            # Só conta palavras do nome presentes no DOMÍNIO. Bater no título é
            # fraco demais (páginas de terceiros citam o nome da empresa).
            distintos = {t for t in tokens if t in dominio_limpo}
            score = len(distintos) * 2
            if any(t in titulo.lower() for t in tokens):
                score += 1
            if cnpj_match:
                score += 10
            if slug_match:
                score += 5
            if not cnpj_match and not slug_match and len(distintos) < 2:
                continue
            if dominio not in melhores or score > melhores[dominio][0]:
                melhores[dominio] = (score, url)
        return sorted(melhores.values(), key=lambda x: x[0], reverse=True)

    def _descobrir_site(
        self, razao_social: str, nome_fantasia: str, cnpj_digitos: str
    ) -> str:
        """Tenta achar o site oficial montando domínios a partir do nome.

        Testa combinações como "rdsengenharia.com.br" (primeiras palavras do
        nome coladas). Só aceita se o domínio resolver e a página citar a
        empresa (CNPJ ou palavras do nome).
        """
        palavras = _palavras_relevantes(razao_social, nome_fantasia)
        if not palavras:
            return ""
        for slug in _slugs_nome(razao_social, nome_fantasia):
            if slug in DOMINIOS_GENERICOS:
                continue
            for tld in (".com.br", ".com"):
                dominio = f"{slug}{tld}"
                if not _resolve_dominio(dominio):
                    continue
                html = self.http.get(f"https://{dominio}", as_json=False)
                if not html:
                    html = self.http.get(f"http://{dominio}", as_json=False)
                if html and _pagina_e_da_empresa(html, cnpj_digitos, palavras):
                    return f"https://{dominio}"
                self.http.dormir(self.config.pausa_web)
        return ""

    # -------------------------------------------------- extração de contatos
    def _extrair_de_pagina(self, url: str, contato: ContatoEnriquecido) -> None:
        html = self.http.get(url, as_json=False)
        if not html:
            return

        host = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
        self._extrair_contatos_texto(html, contato, host)
        texto = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
        self._extrair_contatos_texto(texto, contato, host)
        self.http.dormir(self.config.pausa_web)

    @staticmethod
    def _extrair_contatos_texto(
        texto: str, contato: ContatoEnriquecido, dominio_host: str = ""
    ) -> None:
        """Extrai e-mails, telefones e WhatsApp de uma página.

        Quando `dominio_host` é informado, só aceita e-mails do próprio domínio da
        página — evita capturar contatos de terceiros que aparecem no rodapé/link.
        """
        raiz_host = _dominio_raiz(dominio_host)

        for whats in RE_WHATSAPP.findall(texto):
            numero = _formatar_whatsapp(whats)
            if numero and not contato.whatsapp and not _numero_fake(numero):
                contato.whatsapp = numero

        for email in RE_EMAIL.findall(texto):
            email_l = urllib.parse.unquote(email).lower().strip()
            if any(ruim in email_l for ruim in EMAILS_IGNORADOS):
                continue
            if email_l.endswith(EXTENSOES_ARQUIVO):
                continue
            dominio_email = email_l.rsplit("@", 1)[-1]
            if dominio_email in DOMINIOS_PLACEHOLDER:
                continue
            # Só aceita e-mail do domínio da própria página (evita terceiros).
            if raiz_host and _dominio_raiz(dominio_email) != raiz_host:
                continue
            if email_l not in contato.emails and len(contato.emails) < 5:
                contato.emails.append(email_l)

        for ddd, prefixo, sufixo in RE_TELEFONE.findall(texto):
            if not (11 <= int(ddd) <= 99):
                continue
            if _subscritor_fake(f"{prefixo}{sufixo}"):
                continue
            telefone = f"({ddd}) {prefixo}-{sufixo}"
            if telefone not in contato.telefones and len(contato.telefones) < 10:
                contato.telefones.append(telefone)

    # ------------------------------------------------------------- cache
    def _caminho_cache(self, cnpj: str) -> Path:
        return self.diretorio_cache / f"{cnpj}.json"

    def _ler_cache(self, cnpj: str) -> ContatoEnriquecido | None:
        caminho = self._caminho_cache(cnpj)
        if not caminho.exists():
            return None
        try:
            d = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return ContatoEnriquecido(
            cnpj=d.get("cnpj", cnpj),
            telefones=list(d.get("telefones") or []),
            emails=list(d.get("emails") or []),
            site=d.get("site", ""),
            whatsapp=d.get("whatsapp", ""),
        )

    def _gravar_cache(self, cnpj: str, contato: ContatoEnriquecido) -> None:
        try:
            self._caminho_cache(cnpj).write_text(
                json.dumps(contato.__dict__, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass


# ------------------------------------------------------------- utilitários
STOPWORDS_EMPRESA = {
    "ltda", "me", "epp", "eireli", "sa", "s/a", "s.a", "mei", "cia",
    "comercio", "comércio", "servicos", "serviços", "servico", "serviço",
    "solucoes", "soluções", "solucao", "solução",
    "empresa", "grupo", "industria", "indústria", "distribuidora", "filial",
    "matriz", "brasil", "brazil", "and", "the", "de", "da", "do", "dos", "das",
    "e", "em", "para", "por",
    # Palavras genéricas de segmento: casam com sites de concorrentes, não
    # necessariamente com a empresa pesquisada.
    "papelaria", "mercado", "farmácia", "farmacia", "padaria", "restaurante",
    "lanchonete", "loja", "lojas", "supermercado", "transportadora",
    "transportes", "construcoes", "construções", "construção", "materiais",
    "produtos", "equipamentos", "assistencia", "assistência", "tecnologia",
    "sistemas", "consultoria", "escritorio", "escritório", "gabinete",
    "construtora", "engenharia", "serviç", "agencia", "agência",
}


CONECTORES_IGNORADOS = {"de", "da", "do", "dos", "das", "e", "em", "para", "por", "com"}

# Palavras genéricas demais para virar domínio adivinhado (viram sites errados).
DOMINIOS_GENERICOS = {
    "negocios", "comercio", "servicos", "empresa", "grupo", "centro", "brasil",
    "market", "mercado", "loja", "lojas", "supermercado", "construcao",
    "construcoes", "engenharia", "tecnologia", "sistema", "sistemas", "solucao",
    "solucoes", "eventos", "evento", "transportes", "transporte", "materiais",
    "produtos", "energia", "consultoria", "agencia", "rede", "central",
    "nacional", "geral", "popular", "ideal", "real", "master", "premium",
    "express", "uniao", "familia", "irmaos", "filhos", "construtora",
}


def _nome_compacto(razao_social: str, nome_fantasia: str) -> str:
    """Nome da empresa sem espaços/pontuação, para comparar com o domínio."""
    base = f"{razao_social} {nome_fantasia}".lower()
    return re.sub(r"[^a-z0-9]", "", base)


def _palavras_relevantes(razao_social: str, nome_fantasia: str) -> list[str]:
    """Palavras (3+ letras) do nome, sem conectores, para conferir uma página."""
    base = f"{razao_social} {nome_fantasia}".lower()
    palavras = re.findall(r"[a-z0-9]{3,}", base)
    return [p for p in palavras if p not in CONECTORES_IGNORADOS]


def _slugs_nome(razao_social: str, nome_fantasia: str) -> list[str]:
    """Candidatos de domínio a partir do nome (ex.: rds + engenharia)."""
    base = f"{razao_social} {nome_fantasia}".lower()
    palavras = re.findall(r"[a-z0-9]+", base)
    base_cmd = [p for p in palavras if p not in CONECTORES_IGNORADOS and len(p) >= 2]
    candidatos: list[str] = []
    if len(base_cmd) >= 2:
        candidatos.append(base_cmd[0] + base_cmd[1])
    if len(base_cmd) >= 3:
        candidatos.append(base_cmd[0] + base_cmd[1] + base_cmd[2])
    if base_cmd and len(base_cmd[0]) >= 5:
        candidatos.append(base_cmd[0])
    candidatos.append("".join(palavras))

    vistos: set[str] = set()
    saida: list[str] = []
    for slug in candidatos:
        slug = re.sub(r"[^a-z0-9]", "", slug)
        if len(slug) >= 6 and slug not in vistos:
            vistos.add(slug)
            saida.append(slug)
    return saida


def _resolve_dominio(dominio: str) -> bool:
    try:
        socket.getaddrinfo(dominio, 443)
        return True
    except OSError:
        return False


def _pagina_e_da_empresa(html: str, cnpj_digitos: str, palavras: list[str]) -> bool:
    """Confere se a página parece ser mesmo da empresa (evita site errado)."""
    if cnpj_digitos and cnpj_digitos in re.sub(r"\D", "", html):
        return True
    texto = html.lower()
    acertos = sum(1 for p in palavras if p in texto)
    return acertos >= min(2, len(palavras))


def _tokens_empresa(razao_social: str, nome_fantasia: str) -> set[str]:
    base = f"{razao_social} {nome_fantasia}".lower()
    base = re.sub(r"[^a-z0-9áàâãéêíóôõúç ]", " ", base)
    tokens = {
        t for t in base.split()
        if len(t) >= 4 and t not in STOPWORDS_EMPRESA
    }
    return tokens


def _montar_consultas(cnpj: str, razao_social: str, nome_fantasia: str) -> list[str]:
    consultas = []
    if cnpj:
        consultas.append(f"{cnpj} telefone whatsapp email contato")
    if razao_social:
        consultas.append(f"{razao_social} telefone email whatsapp")
    fantasia = (nome_fantasia or "").strip()
    if fantasia and fantasia.lower() not in (razao_social or "").lower():
        consultas.append(f"{fantasia} telefone email whatsapp")
    return consultas or [razao_social or cnpj]


def _contem_cnpj(texto: str, cnpj_digitos: str) -> bool:
    """True se o CNPJ aparece no texto, com ou sem pontuação."""
    if not cnpj_digitos:
        return False
    if cnpj_digitos in re.sub(r"\D", "", texto):
        return True
    formatado = f"{cnpj_digitos[:2]}.{cnpj_digitos[2:5]}.{cnpj_digitos[5:8]}/{cnpj_digitos[8:12]}-{cnpj_digitos[12:]}"
    return formatado in texto


def _desembrulhar_bing(href: str) -> str:
    """O Bing devolve links como /ck/a?...&u=a1<base64-url>."""
    if href.startswith("//"):
        href = "https:" + href
    if not href.startswith("http"):
        return ""
    match = re.search(r"[?&]u=a1([^&]+)", href)
    if match:
        codificado = match.group(1).replace("-", "+").replace("_", "/")
        codificado += "=" * (-len(codificado) % 4)
        try:
            return base64.b64decode(codificado).decode("utf-8", "ignore")
        except (ValueError, UnicodeDecodeError):
            return ""
    return href


def _raiz_url(url: str) -> str:
    p = urllib.parse.urlparse(url)
    if not p.scheme or not p.netloc:
        return url
    return f"{p.scheme}://{p.netloc}"


def _dominio_raiz(host: str) -> str:
    """Domínio registrável aproximado (ex.: www.x.com.br -> x.com.br)."""
    host = (host or "").lower().strip(". ")
    if not host:
        return ""
    partes = host.split(".")
    if (
        len(partes) >= 3
        and partes[-1] == "br"
        and partes[-2] in {"com", "net", "org", "gov", "edu", "art", "emp", "ind"}
    ):
        return ".".join(partes[-3:])
    if len(partes) >= 2:
        return ".".join(partes[-2:])
    return host


def _subscritor_fake(subscritor: str) -> bool:
    """True para números inválidos/placeholder (ex.: 999990000, 00000000)."""
    d = re.sub(r"\D", "", subscritor or "")
    if len(d) < 8:
        return True
    if len(set(d)) <= 2:
        return True
    if d.endswith("0000") and len(set(d[:-4])) <= 1:
        return True
    return False


def _numero_fake(numero: str) -> bool:
    d = re.sub(r"\D", "", numero or "")
    if not d:
        return False
    if len(d) >= 12 and d.startswith("55"):
        sub = d[4:]
    elif len(d) >= 10:
        sub = d[2:]
    else:
        sub = d
    if len(sub) == 9 and sub.startswith("9"):
        sub = sub[1:]
    return _subscritor_fake(sub)


def _formatar_whatsapp(numero: str) -> str:
    digitos = re.sub(r"\D", "", numero)
    if digitos.startswith("55") and len(digitos) >= 12:
        ddi, resto = "55", digitos[2:]
    elif len(digitos) in (10, 11):
        ddi, resto = "55", digitos
    else:
        return ""
    ddd, telefone = resto[:2], resto[2:]
    return f"+{ddi} ({ddd}) {telefone[:5]}-{telefone[5:]}"
