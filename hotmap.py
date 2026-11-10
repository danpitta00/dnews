"""Hot Map do D.News: pautas por lugar, com "calor" que acumula e esfria.

Calor de cada pauta = temperatura inicial x 0,5^(idade em dias / MEIA_VIDA).
Temperatura inicial: urgência do radar, repercussão (quantos veículos), menção à
Dayse ou a intensidade marcada à mão. Pautas no mesmo lugar se somam como
probabilidades (1 - prod(1 - calor)), com a pauta mais quente valendo inteira e o
resto pela metade: o ponto esquenta quando o assunto acumula e nunca passa de 1. Some do mapa o que passou da janela ou esfriou.
"""
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ROTINAS = AQUI.parent / "rotinas"
MANUAL = ROTINAS / "hotmap_manual.json"
BRT = timezone(timedelta(hours=-3))
MEIA_VIDA_DIAS = 2.0
CALOR_MINIMO = 0.05
LIMIAR_QUENTE = 0.7  # a partir daqui é "quente" (alerta no WhatsApp)
PRIORIDADE = {"Hospital": 0, "UPA": 0, "RA": 2}  # "Órgão" só por local explícito (radar ou cadastro)


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def carregar_lugares():
    lugares = json.loads((AQUI / "lugares_df.json").read_text(encoding="utf-8"))
    for l in lugares:
        l["_re"] = [re.compile(r"(?<![\w-])" + re.escape(_sem_acento(a)) + r"(?![\w-])") for a in sorted(l["apelidos"], key=len, reverse=True)]
    return lugares


LUGARES = carregar_lugares()
POR_NOME = {_sem_acento(l["nome"]): l for l in LUGARES}


def achar_lugar(texto, incluir_orgaos=False):
    """Lugar mais específico citado no texto (hospital/UPA antes de RA)."""
    t = _sem_acento(texto or "")
    achados = [l for l in LUGARES if (incluir_orgaos or l["tipo"] in PRIORIDADE) and any(r.search(t) for r in l["_re"])]
    if not achados:
        return None
    return min(achados, key=lambda l: PRIORIDADE.get(l["tipo"], 1))


def lugar_por_nome(nome):
    if not nome:
        return None
    n = _sem_acento(nome)
    return POR_NOME.get(n) or achar_lugar(nome, incluir_orgaos=True)


def _idade_dias(quando, agora):
    if not quando:
        return None
    try:
        d = datetime.fromisoformat(quando if len(quando) > 10 else quando + "T12:00:00-03:00")
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=BRT)
    return max(0.0, (agora - d).total_seconds() / 86400)


def esfriar(base, idade):
    return base * 0.5 ** (idade / MEIA_VIDA_DIAS)


# ---------- temperatura inicial por origem ----------
def base_radar(it):
    b = {"Alta": 0.85, "Média": 0.55, "Baixa": 0.3}.get(it.get("urgencia"), 0.4)
    tipos = it.get("tipo") or []
    if "Defesa/risco" in tipos:
        b += 0.1
    if "Cobrança" in tipos or "Fiscalização" in tipos:
        b += 0.05
    return min(b, 1.0)


CONFLITO = re.compile(r"(?<!\w)(denúnci|denunci|falta d|faltam|sem médic|superlota|fila|espera|morte|morre|óbito|agress|violên|ameaç|"
                      r"greve|paralis|interdi|irregular|investiga|apura|cpi|polêmic|escândal|desvio|fraude|precári|abandon|"
                      r"feminic|estupr|assédi|negligên|erro médico|câmera|demiss|exonera|suspens|liminar|justiça manda)", re.I)


def base_feed(n):
    """Notícia neutra nasce morna; conflito, repercussão e menção à Dayse esquentam."""
    b = 0.12 + 0.1 * min((n.get("n_fontes") or 1) - 1, 3)
    if CONFLITO.search(f'{n.get("titulo", "")} {n.get("resumo", "")}'):
        b += 0.3
    if n.get("menciona_dayse"):
        b += 0.3
    if n.get("pilar") in ("Saúde", "Mulheres", "Guará"):
        b += 0.05
    return min(b, 1.0)


def base_manual(m):
    return {1: 0.2, 2: 0.4, 3: 0.6, 4: 0.8, 5: 1.0}.get(int(m.get("intensidade") or 3), 0.6)


# ---------- cadastro manual (denúncias, relatos da equipe) ----------
def ler_manual():
    try:
        return json.loads(MANUAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def gravar_manual(lista):
    MANUAL.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANUAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MANUAL)


def adicionar_manual(d):
    lugar = lugar_por_nome(d.get("local"))
    lat, lon = d.get("lat"), d.get("lon")
    if lat is None and not lugar:
        raise ValueError("lugar não encontrado: escolha um da lista")
    item = {
        "id": uuid.uuid4().hex[:10], "titulo": str(d.get("titulo", ""))[:200], "local": lugar["nome"] if lugar else str(d.get("local", "")),
        "lat": float(lat) if lat is not None else None, "lon": float(lon) if lon is not None else None,
        "data": d.get("data") or datetime.now(BRT).date().isoformat(), "intensidade": int(d.get("intensidade") or 3),
        "pilar": d.get("pilar") or "", "tipo": d.get("tipo") or "", "link": d.get("link") or "", "nota": str(d.get("nota", ""))[:500],
        "criado": datetime.now(BRT).isoformat(timespec="minutes"),
    }
    lista = ler_manual() + [item]
    gravar_manual(lista)
    return item


def apagar_manual(item_id):
    gravar_manual([m for m in ler_manual() if m["id"] != item_id])


# ---------- montagem do mapa ----------
def _json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pautas(janela_dias=5, agora=None):
    """Todas as pautas localizadas dentro da janela, com calor atual."""
    agora = agora or datetime.now(BRT)
    limite = (agora - timedelta(days=janela_dias)).date().isoformat()
    out = []

    def add(lugar, lat, lon, base, quando, **info):
        idade = _idade_dias(quando, agora)
        if idade is None or idade > janela_dias:
            return
        calor = esfriar(base, idade)
        if calor < CALOR_MINIMO:
            return
        out.append({**info, "lugar": lugar["nome"] if lugar else info.get("lugar_txt", "Ponto marcado"),
                    "tipo_lugar": lugar["tipo"] if lugar else "Marcado", "aprox": bool(lugar and lugar.get("aprox")),
                    "lat": lat if lat is not None else lugar["lat"], "lon": lon if lon is not None else lugar["lon"],
                    "quando": quando, "idade_dias": round(idade, 1), "base": round(base, 2), "calor": round(calor, 3)})

    for p in sorted((ROTINAS / "radar").glob("*.json")):
        if p.stem < limite:
            continue
        r = _json(p) or {}
        for it in r.get("itens") or []:
            loc = it.get("local") or {}
            lugar = lugar_por_nome(loc.get("nome")) if isinstance(loc, dict) else lugar_por_nome(loc)
            if not lugar and not (isinstance(loc, dict) and loc.get("lat")):
                lugar = achar_lugar(" ".join([it.get("titulo", ""), it.get("fato", "")]))
            if not lugar and not (isinstance(loc, dict) and loc.get("lat")):
                continue
            add(lugar, loc.get("lat") if isinstance(loc, dict) else None, loc.get("lon") if isinstance(loc, dict) else None,
                base_radar(it), p.stem, origem="Radar", titulo=it.get("titulo"), fonte=it.get("veiculo"),
                link=(it.get("links") or [None])[0], pilar=it.get("pilar"), tipos=it.get("tipo") or [], urgencia=it.get("urgencia"),
                chave=f"radar:{p.stem}:{it.get('titulo')}")

    vistos = set()
    for p in sorted((ROTINAS / "feeds").glob("????-??-??.json")):
        if p.stem < limite:
            continue
        for n in (_json(p) or {}).get("itens") or []:
            if n.get("grupo") and n["grupo"] != n["id"] or n["id"] in vistos:
                continue
            vistos.add(n["id"])
            lugar = achar_lugar(f'{n.get("titulo", "")} {n.get("resumo", "")}')
            if not lugar:
                continue
            add(lugar, None, None, base_feed(n), n.get("publicado") or p.stem, origem="Notícia", titulo=n.get("titulo"),
                fonte=n.get("fonte"), link=n.get("link_original") or n.get("link"), pilar=n.get("pilar"), imagem=n.get("imagem"),
                n_fontes=n.get("n_fontes") or 1, menciona_dayse=n.get("menciona_dayse"), chave=f"feed:{n['id']}")

    for m in ler_manual():
        lugar = lugar_por_nome(m.get("local"))
        if not lugar and m.get("lat") is None:
            continue
        add(lugar, m.get("lat"), m.get("lon"), base_manual(m), m.get("data"), origem="Cadastro", titulo=m.get("titulo"),
            fonte=m.get("nota") or "relato da equipe", link=m.get("link"), pilar=m.get("pilar"), tipos=[m["tipo"]] if m.get("tipo") else [],
            intensidade=m.get("intensidade"), id_manual=m["id"], chave=f"manual:{m['id']}", lugar_txt=m.get("local"))
    return out


def mapa(janela_dias=5):
    """Pontos agregados por lugar, do mais quente para o mais frio."""
    pontos = {}
    for p in pautas(janela_dias):
        k = (p["lugar"], round(p["lat"], 4), round(p["lon"], 4))
        pt = pontos.setdefault(k, {"lugar": p["lugar"], "tipo_lugar": p["tipo_lugar"], "aprox": p["aprox"], "lat": p["lat"], "lon": p["lon"], "pautas": [], "_frio": 1.0})
        pt["pautas"].append(p)
        pt["_frio"] *= 1 - p["calor"]
    lista = []
    for pt in pontos.values():
        # a pauta mais quente manda; as outras do mesmo lugar somam pela metade
        maior = max(x["calor"] for x in pt["pautas"])
        pt["calor"] = round(maior + 0.5 * ((1 - pt.pop("_frio")) - maior), 3)
        pt["pautas"].sort(key=lambda x: -x["calor"])
        pt["n"] = len(pt["pautas"])
        lista.append(pt)
    return sorted(lista, key=lambda x: -x["calor"])
