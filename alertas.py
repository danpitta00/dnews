"""Alertas do D.News: avisa no próprio sistema quando sai pauta quente.

"Quente" = calor atual >= limiar (mesma conta do Hot Map, com ou sem lugar):
item Alta do radar, notícia com conflito + repercussão ou menção à Dayse, ou
pauta cadastrada com intensidade alta. Cada pauta entra uma vez só na fila
(rotinas/alertas_fila.json), que o painel mostra com alarme sonoro até alguém
marcar como visto. Também toca o som de alerta do Windows (fora do silêncio
das 23h às 7h). Nada é enviado para fora da máquina.

Uso: python painel_rotinas\\alertas.py [--teste]
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hotmap  # noqa: E402

AQUI = Path(__file__).resolve().parent
ROTINAS = AQUI.parent / "rotinas"
ENVIADOS = ROTINAS / "alertas_enviados.json"
FILA = ROTINAS / "alertas_fila.json"
PASTA_LOG = ROTINAS / "alertas"


def cfg():
    return json.loads((AQUI / "alertas.json").read_text(encoding="utf-8"))


def _ler(p, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return padrao


def _gravar(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def pautas_quentes(limiar):
    """Pautas (com ou sem lugar) com calor atual acima do limiar, das últimas 48 h."""
    agora = datetime.now(hotmap.BRT)
    out = [p for p in hotmap.pautas(janela_dias=2, agora=agora) if p["calor"] >= limiar]
    vistos = {p["chave"] for p in out}
    hoje = agora.date().isoformat()
    for it in (_ler(ROTINAS / "radar" / f"{hoje}.json", {}) or {}).get("itens") or []:
        chave = f"radar:{hoje}:{it.get('titulo')}"
        c = hotmap.base_radar(it)
        if chave not in vistos and c >= limiar:
            out.append({"chave": chave, "titulo": it.get("titulo"), "fonte": it.get("veiculo"), "calor": c, "origem": "Radar",
                        "lugar": None, "link": (it.get("links") or [None])[0]})
    for n in (_ler(ROTINAS / "feeds" / f"{hoje}.json", {}) or {}).get("itens") or []:
        if n.get("grupo") and n["grupo"] != n["id"]:
            continue
        chave = f"feed:{n['id']}"
        c = hotmap.esfriar(hotmap.base_feed(n), hotmap._idade_dias(n.get("publicado"), agora) or 0)
        if chave not in vistos and c >= limiar:
            out.append({"chave": chave, "titulo": n.get("titulo"), "fonte": n.get("fonte"), "calor": c, "origem": "Notícia",
                        "lugar": None, "link": n.get("link_original") or n.get("link"), "menciona_dayse": n.get("menciona_dayse")})
    return sorted(out, key=lambda x: -x["calor"])


def em_silencio(c, agora):
    s = c.get("silencio") or {}
    de, ate = s.get("de"), s.get("ate")
    if not (de and ate):
        return False
    h = agora.strftime("%H:%M")
    return (de <= h or h < ate) if de > ate else (de <= h < ate)


def tocar_som_windows():
    try:
        import winsound
        for _ in range(3):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            winsound.Beep(1200, 220)
            winsound.Beep(900, 220)
    except Exception:  # noqa: BLE001 — sem placa de som / fora do Windows: segue sem som
        pass


def registrar(novas):
    PASTA_LOG.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(hotmap.BRT)
    with open(PASTA_LOG / f"{agora.date().isoformat()}.md", "a", encoding="utf-8") as f:
        f.write(f"\n## {agora.strftime('%H:%M')} · {len(novas)} pauta(s) quente(s)\n\n")
        for p in novas:
            onde = f" · {p['lugar']}" if p.get("lugar") else ""
            f.write(f"- **{p['titulo']}** · {p.get('fonte') or p['origem']}{onde} · {round(p['calor'] * 100)}°" + (f" · {p['link']}" if p.get("link") else "") + "\n")


def fila():
    return _ler(FILA, [])


def marcar_visto(chaves=None):
    """Marca alertas da fila como vistos (todos, se chaves=None)."""
    lista = fila()
    agora = datetime.now(hotmap.BRT).isoformat(timespec="minutes")
    for a in lista:
        if not a.get("visto") and (chaves is None or a["chave"] in chaves):
            a["visto"] = agora
    _gravar(FILA, lista)
    return lista


def rodar(teste=False):
    c = cfg()
    if not c.get("ativo"):
        return "alertas desligados (alertas.json)"
    agora = datetime.now(hotmap.BRT)
    enviados = {k: v for k, v in _ler(ENVIADOS, {}).items() if not k.startswith("log:")}
    if teste:
        novas = [{"chave": f"teste:{agora.isoformat(timespec='seconds')}", "titulo": "Teste do D.News: se tocou e apareceu, os alertas funcionam",
                  "origem": "Teste", "calor": 1.0, "fonte": "D.News", "lugar": None, "link": None}]
    else:
        novas = [p for p in pautas_quentes(float(c.get("limiar", hotmap.LIMIAR_QUENTE))) if p["chave"] not in enviados]
    if not novas:
        return "nenhuma pauta quente nova"
    silencio = enfileirar(novas, gravar_enviados=not teste, forcar_som=teste)
    return f"{len(novas)} pauta(s) quente(s) nova(s) no painel" + (" (sem som: silêncio noturno)" if silencio and not teste else "")


def enfileirar(novas, gravar_enviados=True, forcar_som=False):
    """Põe alertas na fila do painel (sino + sirene), registra e toca o som. Usado também pela agenda legislativa.
    Cada alerta: chave, titulo, origem, e opcionais fonte, lugar, calor, link, menciona_dayse. Devolve True se estava em silêncio."""
    c = cfg()
    agora = datetime.now(hotmap.BRT)
    enviados = {k: v for k, v in _ler(ENVIADOS, {}).items() if not k.startswith("log:")}
    lista = fila()
    for p in novas:
        lista.append({"chave": p["chave"], "titulo": p["titulo"], "fonte": p.get("fonte") or p["origem"], "origem": p["origem"],
                      "lugar": p.get("lugar"), "calor": round(p.get("calor", 1.0), 3), "link": p.get("link"),
                      "menciona_dayse": bool(p.get("menciona_dayse")), "quando": agora.isoformat(timespec="minutes"), "visto": False})
        enviados[p["chave"]] = agora.isoformat(timespec="minutes")
    # fila: guarda 30 dias; enviados: idem
    corte = agora.date().toordinal() - 30
    lista = [a for a in lista if datetime.fromisoformat(a["quando"]).date().toordinal() >= corte]
    enviados = {k: v for k, v in enviados.items() if datetime.fromisoformat(v).date().toordinal() >= corte}
    _gravar(FILA, lista)
    if gravar_enviados:
        _gravar(ENVIADOS, enviados)
    registrar(novas)
    silencio = em_silencio(c, agora)
    if c.get("som_windows", True) and (forcar_som or not silencio):
        tocar_som_windows()
    return silencio


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(rodar(teste="--teste" in sys.argv))
