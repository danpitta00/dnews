"""Painel local das rotinas da Dayse.

Serve os relatórios de D:\\CORTES_DAYSE\\rotinas (radar, drive, pauta, saúde)
organizados por dia. Só biblioteca padrão do Python; a interface usa Tabler
(open source, MIT) via CDN.

Uso: python painel_rotinas\\server.py   →  http://localhost:8790
"""
import json
import re
import socket
import sys
import threading
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import agenda
import alertas
import coletor
import hotmap
import trilhas

RAIZ = Path(__file__).resolve().parent.parent
ROTINAS = RAIZ / "rotinas"
STATIC = Path(__file__).resolve().parent / "static"
RADAR_TEMAS = RAIZ / "contextos" / "radar_temas.md"
ESTADO = ROTINAS / "painel_estado.json"
REDES = RAIZ / "contextos" / "redes_dayse.json"
PASTAS = ("radar", "drive", "pauta", "saude", "feeds")
PORTA = 8790  # 5060 é bloqueada pelo Chrome (SIP); 8765 é usada por outra conversa
DATA_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")
_trava = threading.Lock()


def ler(p: Path):
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def datas_da_pasta(pasta: str):
    d = ROTINAS / pasta
    if not d.is_dir():
        return set()
    return {p.stem for p in d.iterdir() if p.suffix in (".md", ".json") and DATA_RE.match(p.stem)}


def mais_recente_ate(pasta: str, dia: str):
    """Arquivo .md mais recente da pasta com data <= dia (pauta e saúde são semanais)."""
    candidatos = sorted(x for x in datas_da_pasta(pasta) if x <= dia)
    if not candidatos:
        return None, None
    d = candidatos[-1]
    return d, ler(ROTINAS / pasta / f"{d}.md")


def carregar_radar_json(dia: str):
    txt = ler(ROTINAS / "radar" / f"{dia}.json")
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        return {"erro_json": str(e)}


def listar_dias():
    todas = set()
    for p in PASTAS:
        todas |= datas_da_pasta(p)
    dias = []
    for d in sorted(todas, reverse=True):
        rj = carregar_radar_json(d)
        itens = (rj or {}).get("itens") or []
        dias.append({
            "data": d,
            "tem": {p: d in datas_da_pasta(p) for p in PASTAS},
            "itens": len(itens),
            "alta": sum(1 for i in itens if i.get("urgencia") == "Alta"),
        })
    return dias


def fios_atuais():
    """Lê a tabela 'Fios em acompanhamento' de radar_temas.md (fonte viva)."""
    txt = ler(RADAR_TEMAS) or ""
    m = re.search(r"^## Fios em acompanhamento.*?$(.*?)(?=^## |\Z)", txt, re.S | re.M)
    if not m:
        return {"colunas": [], "linhas": []}
    linhas = [l.strip() for l in m.group(1).splitlines() if l.strip().startswith("|")]
    if len(linhas) < 2:
        return {"colunas": [], "linhas": []}
    cel = lambda l: [c.strip() for c in l.strip("|").split("|")]
    return {"colunas": cel(linhas[0]), "linhas": [cel(l) for l in linhas[2:]]}


def ler_estado():
    txt = ler(ESTADO)
    try:
        return json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        return {}


def gravar_estado(item_id: str, status: str, nota: str = ""):
    with _trava:
        est = ler_estado()
        if status == "novo":
            est.pop(item_id, None)
        else:
            est[item_id] = {"status": status, "nota": nota, "em": datetime.now().isoformat(timespec="seconds")}
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        tmp = ESTADO.with_suffix(".tmp")
        tmp.write_text(json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ESTADO)
        return est


def dados_do_dia(dia: str):
    pauta_d, pauta_md = mais_recente_ate("pauta", dia)
    saude_d, saude_md = mais_recente_ate("saude", dia)
    return {
        "data": dia,
        "radar": carregar_radar_json(dia),
        "radar_md": ler(ROTINAS / "radar" / f"{dia}.md"),
        "drive_md": ler(ROTINAS / "drive" / f"{dia}.md"),
        "pauta": {"data": pauta_d, "md": pauta_md},
        "saude": {"data": saude_d, "md": saude_md},
    }


def feeds_do_dia(dia: str):
    txt = ler(ROTINAS / "feeds" / f"{dia}.json")
    try:
        return json.loads(txt) if txt else {"data": dia, "itens": []}
    except json.JSONDecodeError:
        return {"data": dia, "itens": [], "erro": "json inválido"}


_cache_midia = {}


def midia_de(url: str):
    """Imagem/vídeo da matéria (para itens do radar sem mídia). Usa o cache do coletor."""
    if url in _cache_midia:
        return _cache_midia[url]
    cache = coletor.ler_cache()
    m = cache.get(url) or coletor.resolver_midia({"link": url})
    _cache_midia[url] = m
    return m


ESTADO_COLETA = {"rodando": False, "ultima": None, "resumo": None}


def rodar_coleta():
    if ESTADO_COLETA["rodando"]:
        return
    ESTADO_COLETA["rodando"] = True
    try:
        d = coletor.coletar(verbose=False)
        ESTADO_COLETA["resumo"] = f'{len(d["itens"])} notícias · fontes {d["fontes_ok"]}/{d["fontes_total"]}'
        ESTADO_COLETA["alertas"] = alertas.rodar()
        ESTADO_COLETA["trilhas"] = trilhas.atualizar_todas(verbose=False)
    except Exception as e:  # noqa: BLE001 — o painel segue de pé mesmo se a coleta falhar
        ESTADO_COLETA["resumo"] = f"falhou: {type(e).__name__}: {e}"[:200]
    finally:
        ESTADO_COLETA["ultima"] = datetime.now().isoformat(timespec="minutes")
        ESTADO_COLETA["rodando"] = False


ESTADO_AGENDA = {"rodando": False, "ultima": None, "resumo": None}


def rodar_agenda():
    """Checagem da agenda legislativa sob demanda (botão do painel). As rodadas fixas são das 7h e 17h."""
    if ESTADO_AGENDA["rodando"]:
        return
    ESTADO_AGENDA["rodando"] = True
    try:
        d = agenda.rodar(verbose=False)
        ESTADO_AGENDA["resumo"] = d["resumo"][0]
    except Exception as e:  # noqa: BLE001
        ESTADO_AGENDA["resumo"] = f"falhou: {type(e).__name__}: {e}"[:200]
    finally:
        ESTADO_AGENDA["ultima"] = datetime.now().isoformat(timespec="minutes")
        ESTADO_AGENDA["rodando"] = False


def dados_agenda(dia=None):
    pasta = RAIZ / "rotinas" / "agenda"
    dias = sorted((p.stem for p in pasta.glob("????-??-??.json")), reverse=True) if pasta.exists() else []
    dia = dia if dia in dias else (dias[0] if dias else None)
    d = agenda._ler(pasta / f"{dia}.json", None) if dia else None
    return {"dias": dias, "dia": dia, "dados": d, "coleta": ESTADO_AGENDA}


def laco_coleta(intervalo_s=3600):
    """Coleta ao abrir o painel e depois a cada hora (sem custo: só RSS/Google News)."""
    while True:
        rodar_coleta()
        threading.Event().wait(intervalo_s)


def todos_itens():
    """Itens de todos os dias, para busca e visão de prazos."""
    out = []
    for d in sorted(datas_da_pasta("radar"), reverse=True):
        rj = carregar_radar_json(d) or {}
        for n, it in enumerate(rj.get("itens") or []):
            out.append({**it, "_dia": d, "_n": n})
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        # arquivos do painel: o navegador sempre confere se mudou (evita JS velho com HTML novo)
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        caminho = urlparse(self.path).path
        if caminho == "/api/dias":
            return self._json({"hoje": date.today().isoformat(), "dias": listar_dias()})
        if caminho.startswith("/api/dia/"):
            dia = caminho.rsplit("/", 1)[-1]
            if not DATA_RE.match(dia):
                return self._json({"erro": "data inválida"}, 400)
            return self._json(dados_do_dia(dia))
        if caminho == "/api/fios":
            return self._json(fios_atuais())
        if caminho == "/api/itens":
            return self._json(todos_itens())
        if caminho == "/api/estado":
            return self._json(ler_estado())
        if caminho.startswith("/api/feeds/"):
            dia = caminho.rsplit("/", 1)[-1]
            if not DATA_RE.match(dia):
                return self._json({"erro": "data inválida"}, 400)
            return self._json({**feeds_do_dia(dia), "coleta": ESTADO_COLETA})
        if caminho == "/api/midia":
            url = (parse_qs(urlparse(self.path).query).get("url") or [""])[0]
            if not url.startswith("http"):
                return self._json({"erro": "url inválida"}, 400)
            return self._json(midia_de(url))
        if caminho == "/api/hotmap":
            q = parse_qs(urlparse(self.path).query)
            dias = max(1, min(30, int((q.get("dias") or ["5"])[0] or 5)))
            return self._json({"pontos": hotmap.mapa(dias), "dias": dias, "limiar": hotmap.LIMIAR_QUENTE,
                               "meia_vida": hotmap.MEIA_VIDA_DIAS,
                               "lugares": [{"nome": l["nome"], "tipo": l["tipo"]} for l in hotmap.LUGARES]})
        if caminho == "/api/trilhas":
            return self._json(trilhas.listar())
        if caminho == "/api/agenda" or caminho.startswith("/api/agenda/"):
            dia = caminho.rsplit("/", 1)[-1] if caminho.startswith("/api/agenda/") else None
            return self._json(dados_agenda(dia if dia and DATA_RE.match(dia) else None))
        if caminho.startswith("/api/trilha/"):
            d = trilhas.detalhe(caminho.rsplit("/", 1)[-1])
            return self._json(d) if d else self._json({"erro": "trilha não encontrada"}, 404)
        if caminho == "/api/alertas":
            lista = alertas.fila()
            return self._json({"nao_vistos": [a for a in lista if not a.get("visto")], "recentes": lista[-30:][::-1]})
        if caminho == "/api/redes":
            txt = ler(REDES)
            return self._json(json.loads(txt) if txt else {})
        return super().do_GET()

    def _corpo(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        caminho = urlparse(self.path).path
        if caminho == "/api/coletar":
            threading.Thread(target=rodar_coleta, daemon=True).start()
            return self._json({"ok": True})
        if caminho == "/api/agenda/coletar":
            threading.Thread(target=rodar_agenda, daemon=True).start()
            return self._json({"ok": True})
        if caminho == "/api/hotmap/manual":
            try:
                return self._json(hotmap.adicionar_manual(self._corpo()))
            except (ValueError, json.JSONDecodeError) as e:
                return self._json({"erro": str(e)}, 400)
        if caminho == "/api/alertas/visto":
            try:
                chaves = self._corpo().get("chaves")
            except json.JSONDecodeError:
                chaves = None
            alertas.marcar_visto(chaves)
            return self._json({"ok": True})
        if caminho == "/api/alertas/teste":
            return self._json({"resultado": alertas.rodar(teste=True)})
        if caminho == "/api/hotmap/apagar":
            try:
                hotmap.apagar_manual(str(self._corpo()["id"]))
            except (KeyError, json.JSONDecodeError):
                return self._json({"erro": "id faltando"}, 400)
            return self._json({"ok": True})
        if urlparse(self.path).path != "/api/estado":
            return self._json({"erro": "não encontrado"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            item_id, status = str(body["id"]), str(body["status"])
        except (ValueError, KeyError, json.JSONDecodeError):
            return self._json({"erro": "corpo inválido"}, 400)
        if status not in ("novo", "encaminhado", "feito", "descartado"):
            return self._json({"erro": "status inválido"}, 400)
        return self._json(gravar_estado(item_id, status, str(body.get("nota", ""))[:500]))


class ServidorV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def main():
    nums = [a for a in sys.argv[1:] if a.isdigit()]
    porta = int(nums[0]) if nums else PORTA
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    # "localhost" pode resolver para ::1 no navegador; atende também ali (só loopback, nada exposto na rede).
    try:
        srv6 = ServidorV6(("::1", porta), Handler)
        threading.Thread(target=srv6.serve_forever, daemon=True).start()
    except OSError:
        pass
    if "--sem-coleta" not in sys.argv:
        threading.Thread(target=laco_coleta, daemon=True).start()
    print(f"Painel das rotinas da Dayse em http://localhost:{porta}  (Ctrl+C para sair)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
