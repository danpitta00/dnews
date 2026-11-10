"""Trilhas de notícia do D.News: a cronologia de um assunto contada por vários portais.

Trilhas fixas (painel_rotinas/trilhas.json): buscas no Google News dos últimos
30 dias na primeira rodada e das últimas 48 h depois, acumuladas em
rotinas/trilhas/<id>.json. Trilhas automáticas: histórias que vários portais
repetem nas notícias coletadas dos últimos 14 dias (rotinas/feeds/).

Uso: python painel_rotinas\\trilhas.py
"""
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coletor  # noqa: E402

AQUI = Path(__file__).resolve().parent
ROTINAS = AQUI.parent / "rotinas"
PASTA = ROTINAS / "trilhas"
BRT = coletor.BRT
JANELA_INICIAL = "90d"
MAX_MIDIA = 12  # imagens buscadas por trilha a cada rodada (as mais recentes primeiro)


def cfg():
    c = json.loads((AQUI / "trilhas.json").read_text(encoding="utf-8"))
    df = json.loads((AQUI / "fontes.json").read_text(encoding="utf-8"))["palavras_df"]
    for t in c["trilhas"]:  # "@df" = qualquer termo do DF
        if "@df" in t.get("exige_tambem", []):
            t["exige_tambem"] = [x for x in t["exige_tambem"] if x != "@df"] + df
    return c


def _chave(titulo):
    return re.sub(r"\W+", " ", (titulo or "").lower()).strip()[:90]


def _ler(p, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return padrao


def buscar(q, janela):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{q} when:{janela}", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
    return coletor.ler_rss(coletor.baixar(url), "Google News")


def atualizar_trilha(t, cache):
    arq = PASTA / f"{t['id']}.json"
    dados = _ler(arq, {"id": t["id"], "itens": []})
    janela = "2d" if dados.get("itens") else JANELA_INICIAL
    por_chave = {_chave(i["titulo"]): i for i in dados["itens"]}
    novos, erros = 0, []
    for q in t["buscas"]:
        try:
            achados = buscar(q, janela)
        except Exception as e:  # noqa: BLE001
            erros.append(f"{q}: {type(e).__name__}")
            continue
        for it in achados:
            texto = f'{it["titulo"]} {it["resumo"]}'
            if not coletor.termos_em(texto, t["exige"]) or coletor.PAGINA_NAO_NOTICIA.search(it["titulo"]):
                continue
            if t.get("exige_tambem") and not coletor.termos_em(texto, t["exige_tambem"]):
                continue  # segunda condição (ex.: urologia E fila; feminicídio E DF)
            k = _chave(it["titulo"])
            if k in por_chave:
                continue
            por_chave[k] = {"titulo": it["titulo"], "fonte": it["fonte"], "dominio": it.get("dominio"), "link": it["link"],
                            "publicado": it["publicado"], "resumo": it["resumo"] if not it["resumo"].startswith(it["titulo"][:25]) else "",
                            "achado_em": datetime.now(BRT).isoformat(timespec="minutes")}
            novos += 1
    itens = sorted(por_chave.values(), key=lambda i: i.get("publicado") or "")
    # imagem e link real das mais recentes (cache compartilhado com o coletor)
    faltam = [i for i in reversed(itens) if not i.get("imagem") and i["link"] not in cache][:MAX_MIDIA]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, m in zip(faltam, ex.map(lambda i: coletor.resolver_midia({"link": i["link"]}), faltam)):
            cache[i["link"]] = m
    for i in itens:
        m = cache.get(i["link"]) or {}
        i["imagem"] = i.get("imagem") or m.get("imagem")
        if m.get("url") and m["url"] != i["link"]:
            i["link_original"] = m["url"]
    dados.update({"id": t["id"], "itens": itens, "atualizado": datetime.now(BRT).isoformat(timespec="minutes")})
    PASTA.mkdir(parents=True, exist_ok=True)
    coletor.gravar_json(arq, dados)
    return novos, erros


def atualizar_todas(verbose=True):
    cache = coletor.ler_cache()
    total = 0
    for t in cfg()["trilhas"]:
        if t.get("ativa", True) is False:
            continue
        novos, erros = atualizar_trilha(t, cache)
        total += novos
        if verbose:
            print(f"  {t['id']}: +{novos}" + (f" (erros: {erros})" if erros else ""))
    coletor.gravar_json(coletor.OG_CACHE, dict(list(cache.items())[-3000:]))
    return total


# ---------- leitura para o painel ----------
def _dia(iso):
    return (iso or "")[:10]


def resumo_trilha(meta, itens, hoje):
    itens = [i for i in itens if i.get("publicado")]
    dias = [_dia(i["publicado"]) for i in itens]
    inicio = (datetime.fromisoformat(hoje) - timedelta(days=29)).date()
    por_dia = [sum(1 for d in dias if d == (inicio + timedelta(days=k)).isoformat()) for k in range(30)]
    fontes = sorted({i["fonte"] for i in itens})
    ultimo = max(dias) if dias else None
    dias_sem = (datetime.fromisoformat(hoje).date() - datetime.fromisoformat(ultimo).date()).days if ultimo else None
    # "temperatura" da trilha: volume recente (7 dias) e quantos portais
    recentes = sum(por_dia[-7:])
    calor = min(1.0, 0.12 * recentes + 0.05 * len(fontes)) if itens else 0
    capa = next((i.get("imagem") for i in reversed(itens) if i.get("imagem")), None)
    return {**{k: meta.get(k) for k in ("id", "titulo", "pilar", "fio")}, "n": len(itens), "n_fontes": len(fontes), "fontes": fontes[:12],
            "primeiro": min(dias) if dias else None, "ultimo": ultimo, "dias_sem_noticia": dias_sem, "por_dia": por_dia,
            "inicio_grafico": inicio.isoformat(), "calor": round(calor, 3), "imagem": capa,
            "manchete": itens[-1]["titulo"] if itens else None, "automatica": meta.get("automatica", False)}


def trilhas_automaticas(hoje, dias=14):
    """Histórias que 3+ portais diferentes contaram nas notícias coletadas."""
    limite = (datetime.fromisoformat(hoje) - timedelta(days=dias)).date().isoformat()
    todos, vistos = [], set()
    for p in sorted((ROTINAS / "feeds").glob("????-??-??.json")):
        if p.stem < limite:
            continue
        for n in (_ler(p, {}) or {}).get("itens") or []:
            if n["id"] in vistos:
                continue
            vistos.add(n["id"])
            todos.append({k: n.get(k) for k in ("id", "titulo", "fonte", "dominio", "link", "link_original", "publicado", "imagem", "resumo", "pilar")})
    grupos = []
    for it in sorted(todos, key=lambda i: i.get("publicado") or ""):
        p = coletor._palavras(it["titulo"])
        g = next((g for g in grupos if len(p & g["_p"]) / max(1, len(p | g["_p"])) >= 0.3), None)
        if g is None:
            grupos.append({"_p": p, "itens": [it]})
        else:
            g["itens"].append(it)
            g["_p"] |= p
    out = []
    for g in grupos:
        fontes = {i["fonte"] for i in g["itens"]}
        if len(fontes) >= 3:
            meta = {"id": "auto-" + g["itens"][0]["id"], "titulo": g["itens"][0]["titulo"], "pilar": g["itens"][0].get("pilar"), "automatica": True}
            out.append((meta, g["itens"]))
    return out


def listar(hoje=None):
    hoje = hoje or datetime.now(BRT).date().isoformat()
    lista = []
    for t in cfg()["trilhas"]:
        if t.get("ativa", True) is False:
            continue
        lista.append(resumo_trilha(t, _ler(PASTA / f"{t['id']}.json", {}).get("itens") or [], hoje))
    for meta, itens in trilhas_automaticas(hoje):
        lista.append(resumo_trilha(meta, itens, hoje))
    return sorted(lista, key=lambda x: (-x["calor"], -(x["n"] or 0)))


def detalhe(tid, hoje=None):
    hoje = hoje or datetime.now(BRT).date().isoformat()
    if tid.startswith("auto-"):
        for meta, itens in trilhas_automaticas(hoje):
            if meta["id"] == tid:
                return {**resumo_trilha(meta, itens, hoje), "itens": sorted(itens, key=lambda i: i.get("publicado") or "")}
        return None
    meta = next((t for t in cfg()["trilhas"] if t["id"] == tid), None)
    if not meta:
        return None
    itens = _ler(PASTA / f"{tid}.json", {}).get("itens") or []
    return {**resumo_trilha(meta, itens, hoje), "itens": itens, "buscas": meta["buscas"]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("trilhas:", atualizar_todas(), "matérias novas")
