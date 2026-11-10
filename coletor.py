"""Coletor automático do radar: Google News, RSS dos jornais e YouTube.

Sem custo e sem chave. Lê painel_rotinas/fontes.json, filtra pelos temas da Dayse
e grava rotinas/feeds/AAAA-MM-DD.json (acumula ao longo do dia), com imagem e
vídeo de cada notícia quando houver. O radar diário lê esse arquivo.

Uso: python painel_rotinas\\coletor.py
"""
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
FEEDS = RAIZ / "rotinas" / "feeds"
OG_CACHE = FEEDS / "og_cache.json"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Cookie": "CONSENT=YES+cb; SOCS=CAI",
}
JANELA_H = 48
MAX_OG_POR_RODADA = 40
NS = {
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
BRT = timezone(timedelta(hours=-3))


def baixar(url, timeout=15, limite=3_000_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limite).decode("utf-8", "replace")


def limpar(txt, n=280):
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt if len(txt) <= n else txt[: n - 1].rsplit(" ", 1)[0] + "…"


def data_iso(txt):
    if not txt:
        return None
    try:
        d = parsedate_to_datetime(txt)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(BRT).isoformat(timespec="minutes")


def id_de(link):
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def youtube_id(txt):
    m = re.search(r"(?:youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([\w-]{11})", txt or "")
    return m.group(1) if m else None


# ---------- og:image / vídeo da página da matéria ----------
def _meta(pagina, *props):
    for p in props:
        for padrao in (
            rf'<meta[^>]+(?:property|name)=["\']{p}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{p}["\']',
        ):
            m = re.search(padrao, pagina, re.I)
            if m:
                return html.unescape(m.group(1))
    return None


def midia_da_pagina(url):
    """{'imagem','video','descricao'} a partir das meta tags da matéria."""
    try:
        pagina = baixar(url, timeout=12, limite=600_000)
    except Exception as e:  # noqa: BLE001 — qualquer falha de rede vira "sem mídia"
        return {"erro": type(e).__name__}
    img = _meta(pagina, "og:image", "twitter:image", "og:image:url")
    if img and img.startswith("//"):
        img = "https:" + img
    elif img and img.startswith("/"):
        img = urllib.parse.urljoin(url, img)
    return {
        "imagem": img,
        "video": youtube_id(_meta(pagina, "og:video", "og:video:url", "twitter:player") or "") or youtube_id(pagina),
        "descricao": limpar(_meta(pagina, "og:description", "description"), 300),
    }


def ler_cache():
    try:
        return json.loads(OG_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def gravar_json(caminho, obj):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)


def midia_com_cache(url, cache):
    if url not in cache:
        cache[url] = midia_da_pagina(url)
    return cache[url]


# ---------- leitura das fontes ----------
def ler_rss(xml_txt, fonte):
    xml_txt = xml_txt.lstrip("﻿ \r\n\t")
    try:
        raiz = ET.fromstring(xml_txt)
    except ET.ParseError:
        # feed malformado (acontece no g1): remonta só os <item> e tenta de novo
        itens = re.findall(r"<item\b.*?</item>", xml_txt, re.S)
        cab = re.search(r"<rss\b[^>]*>", xml_txt)
        raiz = ET.fromstring((cab.group(0) if cab else "<rss>") + "<channel>" + "".join(itens) + "</channel></rss>")
    out = []
    for it in raiz.iter("item"):
        link = (it.findtext("link") or "").strip()
        if not link.startswith("http"):
            continue
        img = None
        for tag in ("media:content", "media:thumbnail"):
            el = it.find(tag, NS)
            if el is not None and el.get("url"):
                img = el.get("url")
                break
        enc = it.find("enclosure")
        if not img and enc is not None and (enc.get("type") or "").startswith("image"):
            img = enc.get("url")
        corpo = (it.findtext("content:encoded", default="", namespaces=NS) or "") + (it.findtext("description") or "")
        if not img:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', corpo)
            img = m.group(1) if m else None
        src = it.find("source")
        dominio = urllib.parse.urlparse(src.get("url", "") if src is not None else link).netloc.lower().removeprefix("www.")
        titulo = limpar(it.findtext("title"), 300)
        nome_fonte = src.text.strip() if src is not None and src.text else fonte
        if src is not None and titulo.endswith(" - " + nome_fonte):
            titulo = titulo[: -len(nome_fonte) - 3]
        out.append({
            "titulo": titulo, "link": link, "fonte": nome_fonte, "dominio": dominio,
            "publicado": data_iso(it.findtext("pubDate")),
            "resumo": limpar(it.findtext("description") or corpo),
            "imagem": img, "video": youtube_id(corpo),
        })
    return out


def ler_youtube(channel_id, nome):
    xml_txt = baixar(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    raiz = ET.fromstring(xml_txt)
    out = []
    for e in raiz.findall("atom:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        grupo = e.find("media:group", NS)
        desc = grupo.findtext("media:description", default="", namespaces=NS) if grupo is not None else ""
        out.append({
            "titulo": limpar(e.findtext("atom:title", namespaces=NS), 300),
            "link": f"https://www.youtube.com/watch?v={vid}", "fonte": f"YouTube · {nome}",
            "publicado": data_iso(e.findtext("atom:published", namespaces=NS)),
            "resumo": limpar(desc), "imagem": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "video": vid,
        })
    return out


def termos_em(texto, palavras):
    """Termos que aparecem no início de uma palavra ("upa" casa "UPA"/"UPAs", não "ocupa")."""
    t = texto.lower()
    # termos curtos (sus, upa, loa...) só como palavra inteira: "sus" não casa "suspensão"
    return [p for p in palavras if re.search(r"(?<![\w-])" + re.escape(p.lower()) + (r"s?(?![\w-])" if len(p) <= 4 else ""), t)]


# ---------- link real das matérias do Google News ----------
def decodificar_google_news(link):
    """news.google.com/rss/articles/<id> → URL da matéria (mesmo método do googlenewsdecoder, open source)."""
    gid = urllib.parse.urlparse(link).path.rsplit("/", 1)[-1]
    pagina = baixar(f"https://news.google.com/rss/articles/{gid}", timeout=15, limite=2_000_000)  # a página tem ~600 KB
    sg = re.search(r'data-n-a-sg="([^"]+)"', pagina)
    ts = re.search(r'data-n-a-ts="([^"]+)"', pagina)
    if not (sg and ts):
        return None
    interno = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
               "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, int(ts.group(1)), sg.group(1)]
    corpo = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", json.dumps(interno), None, "generic"]]])}).encode()
    req = urllib.request.Request("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=corpo,
                                 headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=12) as r:
        resp = r.read().decode("utf-8", "replace")
    return json.loads(json.loads(resp.split("\n\n", 1)[1])[0][2])[1]


def resolver_midia(item):
    """Para o cache: URL real (se for Google News) + imagem/vídeo da página."""
    url = item["link"]
    if "news.google.com/" in url:
        try:
            url = decodificar_google_news(url) or url
        except Exception as e:  # noqa: BLE001
            return {"erro": f"decodificar: {type(e).__name__}"}
    m = midia_da_pagina(url) if "news.google.com/" not in url else {}
    return {**m, "url": url}


PAGINA_NAO_NOTICIA = re.compile(
    r"^(untitled|https?\b|-\s)|\bsigen\b|anuidade|consultar profissional|acompanhamento de protocolo|\bcartilhas?\b|cronograma|"
    r"curso de verão|mestrado|doutorado|processo seletivo|extrato d[oa] (contrato|termo)|termo aditivo|chamamento público|"
    r"resolução cns|nota-tecnica|diretrizes-brasileiras|^[\w\s]+ - instituto nacional de câncer - inca$", re.I)


def pilar_por_texto(texto, cfg):
    """Pilar de notícia que veio de busca sem pilar fixo (sites de órgãos)."""
    if termos_em(texto, ["guará", "guara"]):
        return "Guará"
    if termos_em(texto, cfg.get("palavras_tema", {}).get("Mulheres", [])):
        return "Mulheres"
    if termos_em(texto, cfg.get("palavras_tema", {}).get("Saúde", [])):
        return "Saúde"
    if termos_em(texto, ["cldf", "câmara legislativa", "orçamento", "loa", "tcdf", "distrital", "governadora", "gdf"]):
        return "Política e orçamento"
    return "Transversais"


OUTRO_ESTADO = re.compile(
    r"\b(goiás|goiânia|são paulo|rio de janeiro|minas gerais|belo horizonte|paraná|curitiba|bahia|salvador|pernambuco|recife|ceará|fortaleza|"
    r"rio grande do sul|porto alegre|santa catarina|florianópolis|espírito santo|mato grosso|amazonas|manaus|pará|belém|maranhão|piauí|"
    r"paraíba|alagoas|sergipe|tocantins|rondônia|acre|amapá|roraima|rio grande do norte|natal|ucrânia|eua|estados unidos)\b", re.I)


PARADAS = set("a o as os de da do das dos e em no na nos nas um uma para por com que se ao à é após sobre diz df".split())


def _palavras(titulo):
    return {w for w in re.findall(r"\w{3,}", titulo.lower()) if w not in PARADAS}


def agrupar(itens):
    """Marca a mesma história contada por vários veículos: 'grupo' = id do item principal."""
    itens = sorted(itens, key=lambda i: (not i.get("imagem"), i.get("publicado") or ""))
    principais = []
    for it in itens:
        p = _palavras(it["titulo"])
        dono = next((c for c, pc in principais if len(p & pc) / max(1, len(p | pc)) >= 0.35), None)
        if dono is None:
            principais.append((it, p))
            it["grupo"], it["n_fontes"] = it["id"], 1
        else:
            it["grupo"] = dono["id"]
            dono["n_fontes"] = dono.get("n_fontes", 1) + 1


def coletar(verbose=True):
    cfg = json.loads((AQUI / "fontes.json").read_text(encoding="utf-8"))
    chaves, df, fontes_df = cfg["palavras_chave"], cfg["palavras_df"], cfg.get("fontes_df", [])
    limite = datetime.now(BRT) - timedelta(hours=JANELA_H)
    tarefas = []
    for g in cfg.get("google_news", []):
        if "q" not in g:  # linha de comentário/bloco
            continue
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f'{g["q"]} when:2d', "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
        tarefas.append(("google_news", g, url))
    for r in cfg.get("rss", []):
        tarefas.append(("rss", r, r["url"]))
    for y in cfg.get("youtube", []):
        tarefas.append(("youtube", y, None))

    def rodar(t):
        origem, f, url = t
        try:
            if origem == "youtube":
                return t, ler_youtube(f["channel_id"], f["nome"]), None
            return t, ler_rss(baixar(url), f.get("nome", "Google News")), None
        except Exception as e:  # noqa: BLE001
            return t, [], f"{type(e).__name__}: {e}"[:160]

    with ThreadPoolExecutor(max_workers=4) as ex:
        resultados = list(ex.map(rodar, tarefas))

    achados, erros = {}, []
    for (origem, f, _), itens, erro in resultados:
        nome_fonte = f.get("nome") or f"Google News: {f.get('q')}"
        if erro:
            erros.append({"fonte": nome_fonte, "erro": erro})
        for it in itens:
            # blogs e institutos temáticos publicam pouco: olham 7 dias em vez de 48 h
            lim = limite - timedelta(days=5) if f.get("tema") else limite
            if it["publicado"] and datetime.fromisoformat(it["publicado"]) < lim:
                continue
            texto = f'{it["titulo"]} {it["resumo"]}'
            termos = termos_em(texto, chaves)
            menciona = bool(re.search(r"dayse|amar[ií]lio", texto, re.I))
            cita_df = bool(termos_em(texto, df))
            # veículo do DF conta como DF, a não ser que a notícia seja de outro estado
            do_df = cita_df or (any(s in it["fonte"].lower() for s in fontes_df) and not OUTRO_ESTADO.search(texto))
            if origem == "google_news" and f.get("exige") and not termos_em(texto, f["exige"]):
                continue
            if PAGINA_NAO_NOTICIA.search(it["titulo"]):
                continue
            dom = it.get("dominio", "")
            # "df.gov.br" aceita subdomínios (saude.df.gov.br); "=gov.br" só o próprio domínio (não goias.gov.br)
            if f.get("dominio") and not any(dom == d.lstrip("=") or (not d.startswith("=") and dom.endswith("." + d)) for d in f["dominio"].split()):
                continue  # o Google News ignorou o site: e trouxe outro órgão (ex.: goias.gov.br)
            if f.get("exige_titulo"):
                # buscas por site de órgão: o título tem que tocar os temas (da Dayse ou da lista temática)
                listas = [chaves if t == "chave" else cfg.get("palavras_tema", {}).get(t, []) for t in f["exige_titulo"].split("+")]
                achou = [p for lista in listas for p in termos_em(it["titulo"], lista)]
                if not achou and not menciona:
                    continue
                termos = termos or achou
            if f.get("tema"):
                # fonte temática nacional (ex.: base Mulheres da Chris): basta o título tocar o tema
                termos = termos_em(it["titulo"], cfg.get("palavras_tema", {}).get(f["tema"], []))
                if not termos and not menciona:
                    continue
            elif origem == "rss" and not termos_em(it["titulo"], chaves):
                continue
            elif origem == "google_news" and f.get("nacional"):
                pass  # órgão nacional: já filtrado pelo título
            elif origem != "youtube" and not menciona and not (termos_em(texto, df) if f.get("nacional") or origem == "rss" else do_df):
                continue  # notícia de fora do DF (SP, PR...) não entra
            if origem == "youtube" and not (f.get("proprio") or f.get("aceita_tudo")) and not termos:
                continue
            if f.get("excluir") and re.search(f["excluir"], it["titulo"], re.I):
                continue  # conteúdo interno do canal (aulas, sessões solenes...)
            chave = re.sub(r"\W+", " ", it["titulo"].lower()).strip()[:90]
            if chave in achados:  # mesma manchete vinda de duas buscas
                achados[chave]["buscas"] = sorted(set(achados[chave]["buscas"] + [f.get("q", nome_fonte)]))
                continue
            achados[chave] = {
                **it, "id": id_de(it["link"]), "origem": origem,
                "pilar": "Menções" if menciona else f.get("pilar") or f.get("tema") or pilar_por_texto(texto, cfg),
                "nacional": bool(f.get("tema") or f.get("nacional")),
                "termos": termos[:6], "menciona_dayse": menciona,
                "buscas": [f.get("q", nome_fonte)], "proprio": bool(f.get("proprio")),
            }

    # imagem/vídeo e link real pela página da matéria (Google News não traz; alguns RSS também não).
    # Menções à Dayse primeiro; o resto entra nas próximas rodadas (cache).
    cache = ler_cache()
    faltando = sorted((a for a in achados.values() if not a.get("imagem") and a["link"] not in cache),
                      key=lambda a: (not a["menciona_dayse"], a.get("publicado") or ""), reverse=False)[:MAX_OG_POR_RODADA]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for a, m in zip(faltando, ex.map(resolver_midia, faltando)):
            cache[a["link"]] = m
    for a in achados.values():
        m = cache.get(a["link"]) or {}
        a["imagem"] = a.get("imagem") or m.get("imagem")
        a["video"] = a.get("video") or m.get("video")
        if m.get("url") and m["url"] != a["link"]:
            a["link_original"] = m["url"]
        if not a.get("resumo") or a["resumo"].startswith(a["titulo"][:30]):
            a["resumo"] = m.get("descricao") or a.get("resumo", "")
    gravar_json(OG_CACHE, dict(list(cache.items())[-3000:]))

    # acumula no arquivo do dia
    hoje = datetime.now(BRT).date().isoformat()
    arq = FEEDS / f"{hoje}.json"
    try:
        dia = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        dia = {"data": hoje, "itens": []}
    por_id = {i["id"]: i for i in dia["itens"]}
    agora = datetime.now(BRT).isoformat(timespec="minutes")
    novos = 0
    for a in achados.values():
        if a["id"] in por_id:
            por_id[a["id"]].update({k: v for k, v in a.items() if v})
        else:
            a["visto_em"] = agora
            por_id[a["id"]] = a
            novos += 1
    agrupar(por_id.values())
    dia.update({
        "itens": sorted(por_id.values(), key=lambda i: i.get("publicado") or "", reverse=True),
        "atualizado": agora, "erros": erros, "fontes_ok": len(tarefas) - len(erros), "fontes_total": len(tarefas),
    })
    gravar_json(arq, dia)
    if verbose:
        print(f"{hoje}: {len(dia['itens'])} itens no dia ({novos} novos) · fontes {dia['fontes_ok']}/{len(tarefas)}")
        for e in erros:
            print("  falhou:", e["fonte"], "→", e["erro"])
    return dia


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    coletar()
