"""Radar de Agenda Legislativa do D.News: CLDF, Câmara dos Deputados e Senado Federal.

Antecipa o que vai ser discutido e votado nos próximos dias, filtra pelas pautas do
mandato (agenda_config.json, editável) e gera:
- rotinas/agenda/AAAA-MM-DD.json  (lido pela aba Agenda do painel)
- rotinas/agenda/AAAA-MM-DD.md    (boletim da manhã; o da tarde vai em AAAA-MM-DD-tarde.md)
- alertas curtos no sino/sirene do painel (pauta extraordinária, urgência em saúde,
  votação hoje/amanhã de item importante, item da Dayse)
- rotinas/agenda/log.jsonl (uma linha por execução: fontes, itens, erros)

Fontes (só dados públicos, sem cadastro):
- Câmara: dadosabertos.camara.leg.br/api/v2 (eventos + pauta de cada evento deliberativo)
- Senado: legis.senado.leg.br/dadosabertos (agenda do plenário do mês + agenda das comissões, 1 semana por consulta)
- CLDF: PDFs da Ordem do Dia (cl.df.gov.br/ordem-do-dia), agenda do site (exportação CSV)
  e a API pública do PLe (ple.cl.df.gov.br/pleservico/api/public) para cruzar ementa, autoria e etapa.

Nunca inventa pauta: se uma fonte falha, o boletim diz qual e por quê.

Uso: python painel_rotinas\\agenda.py [--rodada manha|tarde] [--sem-alertas]
     python painel_rotinas\\agenda.py --pendentes            (grava rotinas/agenda/pendentes_resumo.json com os itens sem resumo simples)
     python painel_rotinas\\agenda.py --resumos arquivo.json  ({id: resumo} → grava e refaz o boletim)
     python painel_rotinas\\agenda.py --so-boletim           (refaz o .md a partir do .json)
"""
import csv
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
ROTINAS = AQUI.parent / "rotinas"
PASTA = ROTINAS / "agenda"
ESTADO = PASTA / "estado.json"
LOG = PASTA / "log.jsonl"
BRT = timezone(timedelta(hours=-3))
UA = "Mozilla/5.0 (D.News radar legislativo; uso interno de mandato)"
PAUSA = 0.35  # segundos entre chamadas à mesma API

CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
SENADO = "https://legis.senado.leg.br/dadosabertos"
PLE = "https://ple.cl.df.gov.br/pleservico/api/public"
CLDF_OD = "https://www.cl.df.gov.br/ordem-do-dia"
CLDF_AGENDA_CSV = ("https://www.cl.df.gov.br/agenda?p_p_id=br_com_seatecnologia_in_CalendarListPortlet&p_p_lifecycle=2&p_p_state=normal"
                   "&p_p_mode=view&p_p_resource_id=calendar%2Fbookings%2Fexport_csv&p_p_cacheability=cacheLevelPage"
                   "&_br_com_seatecnologia_in_CalendarListPortlet_isSearch=false"
                   "&_br_com_seatecnologia_in_CalendarListPortlet_startTime={ini}&_br_com_seatecnologia_in_CalendarListPortlet_endTime={fim}")
PRIORIDADES = {"Alta": 0, "Média": 1, "Baixa": 2}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ---------- utilidades ----------
def cfg():
    return json.loads((AQUI / "agenda_config.json").read_text(encoding="utf-8"))


def _ler(p, padrao):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return padrao


def _gravar(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def baixar(url, corpo=None, aceitar="application/json", tentativas=3, timeout=45):
    ultimo = None
    for i in range(tentativas):
        try:
            h = {"User-Agent": UA, "Accept": aceitar}
            if corpo is not None:
                h["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=json.dumps(corpo).encode() if corpo is not None else None, headers=h,
                                         method="POST" if corpo is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — tenta de novo e, no fim, devolve o erro para o boletim
            ultimo = e
            if getattr(e, "code", None) in (400, 404):
                break
            time.sleep(1.5 * (i + 1))
    raise ultimo


def jget(url, corpo=None):
    time.sleep(PAUSA)
    return json.loads(baixar(url, corpo).decode("utf-8"))


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def casa_termos(texto, palavras):
    """Palavras que aparecem no texto (sem acento; até 4 letras só como palavra inteira)."""
    t = " " + norm(texto) + " "
    achou = []
    for p in palavras:
        q = norm(p).strip()
        if not q:
            continue
        fim = r"s?(?![\w])" if len(q) <= 4 else ""
        if re.search(r"(?<![\w])" + re.escape(q) + fim, t):
            achou.append(p.strip())
    return achou


def limpa(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def frase_curta(s, n=230):
    s = limpa(s)
    if len(s) <= n:
        return s
    corte = s[:n].rsplit(" ", 1)[0]
    return corte.rstrip(",;:") + "…"


def hoje_brt():
    return datetime.now(BRT).date()


# ---------- item padrão ----------
def novo_item(**kw):
    it = {"id": None, "casa": None, "data": None, "hora": None, "evento": None, "orgao": None, "plenario": False,
          "tipo_item": "proposicao", "proposicao": None, "ementa": "", "resumo_simples": None, "autor": None, "etapa": None,
          "regime": None, "situacao_evento": None, "confirmado": False, "status_pauta": None, "link": None, "link_evento": None,
          "tema_oficial": None, "extraordinaria": False, "terminativo": False}
    it.update(kw)
    return it


# ---------- Câmara dos Deputados ----------
def coletar_camara(ini, fim, log):
    itens = []
    url = f"{CAMARA}/eventos?dataInicio={ini}&dataFim={fim}&ordem=ASC&ordenarPor=dataHoraInicio&itens=100"
    eventos = []
    while url:
        r = jget(url)
        eventos += r.get("dados") or []
        url = next((l["href"] for l in r.get("links") or [] if l.get("rel") == "next"), None)
    log["eventos"] = len(eventos)
    for e in eventos:
        tipo = e.get("descricaoTipo") or ""
        orgaos = e.get("orgaos") or []
        siglas = [o.get("sigla") for o in orgaos]
        nomes = [o.get("nome") for o in orgaos]
        plen = "PLEN" in siglas
        dh = e.get("dataHoraInicio") or ""
        base = dict(casa="Câmara", data=dh[:10], hora=dh[11:16] or None, plenario=plen,
                    evento=f"{tipo} · {', '.join(nomes) or 'Câmara'}", orgao=", ".join(siglas),
                    situacao_evento=e.get("situacao"), link_evento=f"https://www.camara.leg.br/evento-legislativo/{e['id']}",
                    extraordinaria="extraordin" in norm(tipo + " " + (e.get("descricao") or "")))
        if "solene" in norm(tipo) or tipo in ("Reunião Técnica",):
            continue
        deliberativa = "deliber" in norm(tipo)
        pauta = []
        if deliberativa:
            try:
                pauta = jget(f"{CAMARA}/eventos/{e['id']}/pauta").get("dados") or []
            except Exception as x:  # noqa: BLE001
                log.setdefault("erros", []).append(f"pauta do evento {e['id']}: {x}")
        for p in pauta:
            prop = p.get("proposicaoRelacionada_") or p.get("proposicao_") or {}
            if not prop:
                continue
            sig = p.get("titulo") or f"{prop.get('siglaTipo')} {prop.get('numero')}/{prop.get('ano')}"
            rel = p.get("relator") or {}
            etapa = limpa(p.get("topico"))
            if rel.get("nome"):
                etapa += f" · relator(a): {rel['nome']} ({'-'.join(filter(None, [rel.get('siglaPartido'), rel.get('siglaUf')]))})"
            if p.get("textoParecer"):
                etapa += f" · {frase_curta(p['textoParecer'], 160)}"
            itens.append(novo_item(**base, id=f"camara:{e['id']}:{prop.get('id')}", proposicao=sig, ementa=limpa(prop.get("ementa")),
                                   etapa=etapa, regime=p.get("regime"), confirmado=e.get("situacao") != "Cancelada",
                                   status_pauta="pauta publicada" if e.get("situacao") != "Cancelada" else "evento cancelado",
                                   link=f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={prop.get('id')}",
                                   _id_prop=prop.get("id")))
        if not pauta:
            # audiência, seminário ou deliberativa sem pauta publicada: entra como evento (o filtro decide)
            desc = limpa((e.get("descricao") or "").split("\r\n")[0])
            itens.append(novo_item(**base, id=f"camara:{e['id']}", tipo_item="evento", ementa=desc or tipo,
                                   confirmado=False, status_pauta="evento agendado, pauta ainda não publicada" if deliberativa else "evento agendado",
                                   link=base["link_evento"]))
    return itens


def autores_camara(itens, log):
    """Busca o autor só dos itens que passaram no filtro (poupa a API)."""
    for it in itens:
        pid = it.pop("_id_prop", None)
        if it["casa"] != "Câmara" or not pid or it.get("autor"):
            continue
        try:
            a = jget(f"{CAMARA}/proposicoes/{pid}/autores").get("dados") or []
            if a:
                nome = a[0].get("nome") or ""
                it["autor"] = nome + (f" e outros ({len(a) - 1})" if len(a) > 1 else "")
        except Exception as x:  # noqa: BLE001
            log.setdefault("erros", []).append(f"autor da proposição {pid}: {x}")


# ---------- Senado Federal ----------
def _lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def coletar_senado_plenario(ini, fim, log):
    itens, sessoes = [], []
    meses = {ini.strftime("%Y%m%d")}
    if fim.month != ini.month:
        meses.add(fim.replace(day=1).strftime("%Y%m%d"))
    for m in sorted(meses):
        r = jget(f"{SENADO}/plenario/agenda/mes/{m}.json")
        sessoes += _lista(((r.get("AgendaPlenario") or {}).get("Sessoes") or {}).get("Sessao"))
    for s in sessoes:
        d = s.get("Data")
        if not d or not (ini.isoformat() <= d <= fim.isoformat()):
            continue
        tipo = limpa(s.get("TipoSessao"))
        casa = "Congresso" if s.get("Casa") == "CN" else "Senado"
        base = dict(casa=casa, data=d, hora=(s.get("Hora") or "")[:5] or None, plenario=True,
                    evento=f"{tipo.capitalize()} · {limpa(s.get('LocalSessao'))}", orgao="Plenário",
                    situacao_evento=s.get("SituacaoSessao"), extraordinaria="extraordin" in norm(tipo),
                    link_evento=f"https://www25.senado.leg.br/web/atividade/sessao-plenaria/-/pauta/{s.get('CodigoSessao')}")
        conf = s.get("PautaConfirmada") == "Sim"
        materias = _lista((s.get("Materias") or {}).get("Materia"))
        for m in materias:
            parecer = limpa(m.get("Parecer"))
            itens.append(novo_item(**base, id=f"senado:{s.get('CodigoSessao')}:{m.get('CodigoMateria')}",
                                   proposicao=m.get("DescricaoIdentificacaoMateria"), ementa=limpa(m.get("Ementa")),
                                   autor=m.get("NomeAutor"), etapa=limpa(m.get("Apreciacao")) + (f" · {frase_curta(parecer, 200)}" if parecer else ""),
                                   regime="urgência" if "urgencia" in norm(parecer + " " + (m.get("Apreciacao") or "")) else None,
                                   confirmado=conf, status_pauta="pauta confirmada" if conf else "pauta prevista (ainda não confirmada)",
                                   link=f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{m.get('CodigoMateria')}"))
        if not materias and "deliberativa" in norm(tipo) and "nao deliberativa" not in norm(tipo):
            itens.append(novo_item(**base, id=f"senado:{s.get('CodigoSessao')}", tipo_item="sessao", ementa=f"{tipo.capitalize()} sem matérias publicadas na pauta",
                                   confirmado=False, status_pauta="sessão marcada, pauta ainda não publicada", link=base["link_evento"]))
    log["sessoes"] = len(sessoes)
    return itens


def _partes(r):
    p = r.get("partes")
    if isinstance(p, dict) and "parte" in p:
        p = p["parte"]
    return _lista(p)


def coletar_senado_comissoes(ini, fim, log):
    itens, n = [], 0
    a = ini
    while a <= fim:  # a agenda detalhada aceita no máximo uma semana por consulta
        b = min(fim, a + timedelta(days=6))
        r = jget(f"{SENADO}/comissao/agenda/{a.strftime('%Y%m%d')}/{b.strftime('%Y%m%d')}.json")
        reunioes = _lista((((r.get("AgendaReuniao") or {}).get("reunioes") or {}).get("reuniao")))
        n += len(reunioes)
        for x in reunioes:
            col = x.get("colegiadoCriador") or {}
            di = x.get("dataInicio") or ""
            base = dict(casa="Senado", data=di[:10], hora=di[11:16] or None, plenario=False,
                        evento=f"{limpa(x.get('titulo'))} · {col.get('nome') or col.get('sigla')}", orgao=col.get("sigla"),
                        situacao_evento=x.get("situacao"), extraordinaria="extraordin" in norm(x.get("titulo")),
                        link_evento=f"https://legis.senado.leg.br/comissoes/reuniao?reuniao={x.get('codigo')}")
            conf = x.get("confirmada") == "true"
            achou = False
            for parte in _partes(x):
                for i in _lista(parte.get("itens")):
                    doma = i.get("doma") or {}
                    if not doma:
                        continue
                    achou = True
                    sig = doma.get("identificacao") or i.get("nome")
                    cod = doma.get("codigoMateria")
                    itens.append(novo_item(**base, id=f"senado-com:{x.get('codigo')}:{cod or sig}", proposicao=i.get("nome") or sig,
                                           ementa=limpa(doma.get("ementa")), autor=limpa(doma.get("autoria")),
                                           etapa=limpa(f"{parte.get('descricaoTipo') or ''} · {i.get('siglaRelatorio') or i.get('relatorio') or 'sem relatório'}"),
                                           terminativo=i.get("isTerminativo") == "true",
                                           confirmado=True, status_pauta="pauta publicada" + (" e reunião confirmada" if conf else ", reunião ainda não confirmada"),
                                           link=f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{cod}" if cod else base["link_evento"]))
                if not _lista(parte.get("itens")) and (parte.get("evento") or {}).get("finalidade"):
                    fin = limpa(parte["evento"]["finalidade"])
                    itens.append(novo_item(**base, id=f"senado-com:{x.get('codigo')}:{parte.get('codigo')}", tipo_item="evento",
                                           ementa=f"{parte.get('descricaoTipo')}: {fin}", confirmado=conf,
                                           status_pauta="reunião confirmada" if conf else "reunião agendada", link=base["link_evento"]))
                    achou = True
            if not achou:
                itens.append(novo_item(**base, id=f"senado-com:{x.get('codigo')}", tipo_item="evento", ementa=limpa(x.get("titulo")),
                                       confirmado=False, status_pauta="reunião agendada, pauta ainda não publicada", link=base["link_evento"]))
        a = b + timedelta(days=1)
    log["reunioes"] = n
    return itens


# ---------- CLDF ----------
RE_PDF = re.compile(r'href="(https://www\.cl\.df\.gov\.br/documents/[^"]*?Ordem\+do\+Dia\+Sess%C3%A3o\+([A-Za-z%0-9]+?)\+de\+(\d{2})-(\d{2})([A-Za-z]*)\.pdf[^"]*)"')
RE_PROP = re.compile(r"(Proposta de Emenda à Lei Orgânica(?: do Distrito Federal)?|Projeto de Lei Complementar|Projeto de Lei|Projeto de Resolução|"
                     r"Projeto de Decreto Legislativo|Requerimento|Moção|Veto (?:Parcial|Total) ao Projeto de Lei(?: Complementar)?)\s+n[º°o]\.?\s*([\d.]+)\s*,?\s*de\s*(\d{4})", re.I)
SIGLA_CLDF = {"proposta de emenda a lei organica": "PELO", "projeto de lei complementar": "PLC", "projeto de lei": "PL",
              "projeto de resolucao": "PR", "projeto de decreto legislativo": "PDL", "requerimento": "REQ", "mocao": "MO"}
TIPO_PLE = {"PELO": "Proposta de Emenda à Lei Orgânica", "PLC": "Projeto de Lei Complementar", "PL": "Projeto de Lei",
            "PR": "Projeto de Resolução", "PDL": "Projeto de Decreto Legislativo", "MO": "Moção", "REQ": "Requerimento"}


def _data_od(dd, mm, hoje):
    # o nome do PDF só traz dia e mês; a página lista o ano corrente (e, em dezembro, pode aparecer janeiro do ano seguinte)
    d = date(hoje.year, int(mm), int(dd))
    if (d - hoje).days > 60:
        d = date(hoje.year - 1, int(mm), int(dd))
    elif (d - hoje).days < -300:
        d = date(hoje.year + 1, int(mm), int(dd))
    return d


def ler_pdf(conteudo):
    import pypdf  # só quando precisa
    r = pypdf.PdfReader(io.BytesIO(conteudo))
    return "\n".join(p.extract_text() or "" for p in r.pages)


def itens_da_ordem_do_dia(texto):
    """Separa os ITENS da pauta do PDF (até a tabela de vetos)."""
    t = re.sub(r"CÂMARA LEGISLATIVA DO DISTRITO FEDERAL\s*\nPresidência\s*\nSecretaria Legislativa\s*\n\s*\nFontes:[^\n]*\n", "\n", texto)
    t = t.split("TABELA DE VETOS PARA DELIBERAÇÃO")[0]
    partes = re.split(r"\n\s*ITEM\s+(\d+)\s*:\s*", "\n" + t)
    out = []
    for k in range(1, len(partes) - 1, 2):
        bloco = limpa(re.sub(r"(\d)\s+(\d)", r"\1\2", partes[k + 1]))  # "202 3" -> "2023"
        bloco = re.split(r"\s(?:PROJETOS ACORDADOS|SEMANA LEGISLATIVA)\b", bloco)[0]
        m = RE_PROP.search(bloco)
        sigla = num = ano = None
        if m:
            nome = norm(m.group(1))
            sigla = "VETO" if nome.startswith("veto") else next((v for k2, v in SIGLA_CLDF.items() if nome.startswith(k2)), None)
            num, ano = m.group(2).replace(".", ""), m.group(3)
        etapa = limpa(bloco[:m.start()] if m else bloco[:80]).rstrip(" ,").removesuffix(" do").removesuffix(" da").removesuffix(" ao")
        aut = re.search(r"de autoria\s+(?:do|da|dos|das)?\s*(.+?)\s*,?\s+que\s+[“\"]", bloco)
        em = re.search(r"[“\"]\s*(.+?)\s*[”\"]", bloco)
        sit = re.findall(r"(TRAMITAÇÃO CONCLUÍDA|APROVADO EM 1º TURNO|A proposição não recebeu parecer[^.]*|As proposições não receberam pareceres[^.]*|Aprovados? pareceres? [^.]*)", bloco)
        out.append({"item": int(partes[k]), "sigla": sigla, "numero": num, "ano": ano, "texto": bloco, "etapa": etapa,
                    "autor": limpa(aut.group(1)) if aut else None, "ementa": limpa(em.group(1)) if em else frase_curta(bloco, 260),
                    "situacao": "; ".join(dict.fromkeys(limpa(s) for s in sit)) or None,
                    "urgencia": "urgência" in bloco.lower()})
    return out


def ple_buscar(sigla, num, ano, cache, log):
    """Cruza com a API do PLe (ementa, autoria, etapa, tema). Usa cache para não repetir consulta."""
    if sigla not in TIPO_PLE or not num:
        return None
    chave = f"{sigla}-{num}-{ano}"
    if chave in cache:
        return cache[chave]
    try:
        r = jget(f"{PLE}/proposicao/filter?page=0&size=5", {"tipoProposicao": TIPO_PLE[sigla], "numeroProposicao": str(num), "ano": str(ano)})
        achou = next((c for c in r.get("content") or [] if re.sub(r"\D", "", (c.get("siglaNumeroAno") or "").split("/")[0]) == str(num)
                      and (c.get("siglaNumeroAno") or "").endswith(str(ano))), None)
        cache[chave] = {k: achou.get(k) for k in ("id", "ementa", "autoria", "etapa", "temaNome", "siglaNumeroAno", "regiaoAdministrativaNome")} if achou else {}
    except Exception as x:  # noqa: BLE001
        log.setdefault("erros", []).append(f"PLe {chave}: {x}")
        return None
    return cache[chave]


def coletar_cldf(ini, fim, estado, log, avisos):
    itens = []
    hoje = hoje_brt()
    cache_ple = estado.setdefault("ple", {})
    pdfs_lidos = estado.setdefault("pdfs", {})
    # 1) agenda do site (sessões, comissões, audiências)
    sessoes_agenda = {}
    try:
        t0 = datetime(ini.year, ini.month, ini.day, tzinfo=BRT)
        t1 = datetime(fim.year, fim.month, fim.day, 23, 59, tzinfo=BRT)
        bruto = baixar(CLDF_AGENDA_CSV.format(ini=int(t0.timestamp() * 1000), fim=int(t1.timestamp() * 1000)), aceitar="text/csv,*/*").decode("utf-8-sig")
        linhas = [l for l in bruto.splitlines() if not l.startswith("sep=")]
        rd = csv.DictReader(linhas, delimiter=";")
        n = 0
        for row in rd:
            row = {limpa(k): limpa(v) for k, v in row.items() if k}
            n += 1
            ini_s = row.get("Data Início") or ""
            try:
                dt = datetime.strptime(ini_s, "%d/%m/%Y %H:%M")
            except ValueError:
                continue
            tipo, titulo, autor = row.get("Tipo") or "", row.get("Título") or "", row.get("Autor") or ""
            if tipo in (cfg().get("cldf_tipos_ignorados") or []):
                continue
            d = dt.date().isoformat()
            plen = tipo in ("Sessão Ordinária", "Sessão Extraordinária")
            if plen:
                sessoes_agenda[d] = {"hora": dt.strftime("%H:%M"), "tipo": tipo}
            itens.append(novo_item(casa="CLDF", data=d, hora=dt.strftime("%H:%M"), id=f"cldf-agenda:{d}:{dt.strftime('%H%M')}:{norm(titulo)[:40]}",
                                   tipo_item="sessao" if plen else "evento", plenario=plen, evento=f"{tipo} · {row.get('Local') or 'CLDF'}",
                                   orgao=autor if "Comissão" in autor or " - " in autor else None, ementa=titulo, autor=autor,
                                   extraordinaria="extraordin" in norm(tipo + " " + titulo),
                                   confirmado=False, status_pauta="na agenda da CLDF" + (" (pauta = Ordem do Dia)" if plen else ""),
                                   link=f"https://www.cl.df.gov.br/web/guest/agenda/-/calendar/{dt.strftime('%d-%m-%Y')}"))
        log["agenda"] = n
    except Exception as x:  # noqa: BLE001
        avisos.append(f"CLDF · agenda do site fora do ar ou ilegível ({x}). Comissões e audiências da CLDF podem estar faltando.")
        log.setdefault("erros", []).append(f"agenda CSV: {x}")
    # 2) Ordem do Dia (PDF) das sessões de hoje em diante
    html = baixar(CLDF_OD, aceitar="text/html").decode("utf-8", "replace")
    pdfs = {}
    for m in RE_PDF.finditer(html):
        url, tipo, dd, mm, suf = m.group(1).replace("&amp;", "&"), urllib.parse.unquote_plus(m.group(2)), m.group(3), m.group(4), m.group(5)
        d = _data_od(dd, mm, hoje)
        pdfs.setdefault((d, tipo, suf), url)
    ultimas = sorted(pdfs)[-1:] if pdfs else []
    futuras = sorted(k for k in pdfs if ini <= k[0] <= fim)
    log["pdfs_na_pagina"], log["pdfs_futuros"] = len(pdfs), len(futuras)
    for (d, tipo, suf) in futuras:
        url = pdfs[(d, tipo, suf)]
        sessao = f"Sessão {tipo}" + (" (Comissão Geral)" if suf.upper() == "CG" else "")
        try:
            texto = ler_pdf(baixar(url, aceitar="application/pdf", timeout=90))
            od = itens_da_ordem_do_dia(texto)
        except Exception as x:  # noqa: BLE001
            avisos.append(f"CLDF · não consegui ler a Ordem do Dia de {d.strftime('%d/%m')} ({x}). Conferir no PDF: {url}")
            continue
        if not od:
            avisos.append(f"CLDF · a Ordem do Dia de {d.strftime('%d/%m')} foi publicada, mas não achei os itens no texto do PDF. Conferir: {url}")
            continue
        pdfs_lidos[url] = {"data": d.isoformat(), "itens": len(od), "lido": datetime.now(BRT).isoformat(timespec="minutes")}
        hora = (sessoes_agenda.get(d.isoformat()) or {}).get("hora") or "15:00"
        for o in od:
            ple = ple_buscar(o["sigla"], o["numero"], o["ano"], cache_ple, log) or {}
            sig = ple.get("siglaNumeroAno") or (f"{o['sigla']} {o['numero']}/{o['ano']}" if o["sigla"] and o["numero"] else f"Item {o['item']}")
            etapa = o["etapa"] + (f" · {o['situacao']}" if o["situacao"] else "") + (f" · PLe: {ple['etapa']}" if ple.get("etapa") else "")
            itens.append(novo_item(casa="CLDF", data=d.isoformat(), hora=hora, plenario=True, id=f"cldf-od:{d.isoformat()}:{sig}",
                                   evento=f"{sessao} · Plenário (item {o['item']} da Ordem do Dia)", orgao="Plenário",
                                   proposicao=sig, ementa=limpa(ple.get("ementa")) or o["ementa"], autor=limpa(ple.get("autoria")) or o["autor"],
                                   etapa=etapa, regime="urgência" if o["urgencia"] else None, tema_oficial=(ple.get("temaNome") or "").strip("#") or None,
                                   extraordinaria="extraordin" in norm(tipo), confirmado=True, status_pauta="na Ordem do Dia publicada",
                                   link=url, link_evento=CLDF_OD))
        # a sessão da agenda vira desnecessária: a pauta já está nos itens
        itens = [i for i in itens if not (i["tipo_item"] == "sessao" and i["casa"] == "CLDF" and i["data"] == d.isoformat())]
    # sessões futuras sem Ordem do Dia ainda
    for i in itens:
        if i["casa"] == "CLDF" and i["tipo_item"] == "sessao":
            i["ementa"] = f"{i['evento'].split(' · ')[0]}: a Ordem do Dia ainda não foi publicada (costuma sair na véspera)"
            i["status_pauta"] = "sessão na agenda, pauta ainda não publicada"
    if not futuras:
        ult = ultimas[0][0].strftime("%d/%m") if ultimas else "?"
        avisos.append(f"CLDF · ainda não há Ordem do Dia publicada para as próximas sessões (a última no site é de {ult}). "
                      "Ela costuma sair na véspera; a checagem das 17h pega.")
    return itens


def proposicoes_dayse(estado, log):
    """Proposições da Dayse lidas recentemente no PLe (para marcar destaque se aparecerem na pauta)."""
    try:
        r = jget(f"{PLE}/proposicao/filter?page=0&size=50&sort=dataLeitura,DESC", {"autoria": "Dayse Amarilio"})
        return {c.get("siglaNumeroAno") for c in r.get("content") or [] if c.get("siglaNumeroAno")}
    except Exception as x:  # noqa: BLE001
        log.setdefault("erros", []).append(f"PLe Dayse: {x}")
        return set()


# ---------- filtro de relevância ----------
TEMA_PLE = {"saude": "Saúde", "mulher": "Mulheres", "esporte": "Esporte", "idoso": "Melhor idade e Guará", "pessoa idosa": "Melhor idade e Guará"}


def classificar(it, c, props_dayse):
    pautas_cfg = c["pautas"]
    texto = " ".join(filter(None, [it.get("proposicao"), it.get("ementa"), it.get("evento") if it["tipo_item"] != "proposicao" else "",
                                   it.get("orgao") if it["tipo_item"] != "proposicao" else ""]))
    pautas = [nome for nome, p in pautas_cfg.items() if casa_termos(texto, p["palavras"])]
    if casa_termos(it.get("ementa"), c.get("rebaixar_ementas") or []):
        pautas = []  # homenagem, título, nome de logradouro: só entra pela regra geral (plenário = Baixa)
    tema = norm(it.get("tema_oficial"))
    for k, v in TEMA_PLE.items():
        if k in tema and v not in pautas:
            pautas.append(v)
    ai = c["alto_impacto"]
    sinais = []
    if casa_termos(" ".join(filter(None, [it.get("regime"), it.get("etapa"), it.get("ementa")])), ai["urgencia"]) or it.get("regime") == "urgência":
        sinais.append("urgência")
    if it["plenario"] and it["tipo_item"] == "proposicao":
        sinais.append("votação em plenário")
    if it.get("extraordinaria") and it["plenario"]:  # reunião extraordinária de comissão é rotina; só sessão de plenário conta
        sinais.append("sessão extraordinária")
    if casa_termos(texto, ai["repercussao"]):
        sinais.append("alta repercussão")
    if it["casa"] != "CLDF" and casa_termos(texto, ai["df"]):
        sinais.append("impacto no DF")
    if it.get("terminativo"):
        sinais.append("decisão terminativa")  # só informativo: não basta para entrar
    dy = c["dayse"]
    autor_txt = it.get("autor") or ""
    destaque = []
    if casa_termos(autor_txt, dy["nomes"]):
        destaque.append("autoria da Dayse")
    elif casa_termos(texto, dy["nomes"]):
        destaque.append("cita a Dayse")
    if it.get("proposicao") in props_dayse:
        destaque.append("proposição da Dayse")
    if casa_termos(texto, dy["projetos_acompanhados"]):
        destaque.append("projeto que a Dayse acompanha")
    if pautas:
        prio = min((pautas_cfg[p]["prioridade"] if p in pautas_cfg else "Média" for p in pautas), key=PRIORIDADES.get)
        principal = min(pautas, key=lambda p: PRIORIDADES.get(pautas_cfg.get(p, {}).get("prioridade", "Média"), 1))
    elif destaque:
        prio, principal, pautas = "Alta", "Outras", ["Outras"]
    elif it["tipo_item"] == "sessao" and it["casa"] == "CLDF":
        prio, principal, pautas = "Baixa", "Outras", ["Outras"]
    elif {"urgência", "votação em plenário", "sessão extraordinária", "impacto no DF"} & set(sinais) and \
            (it["casa"] != "CLDF" or not ai.get("so_plenario_cldf") or it["plenario"] or "urgência" in sinais):
        # outras áreas só com sinal de alto impacto (repercussão sozinha não basta: é só rótulo)
        fortes = {"urgência", "sessão extraordinária"}
        prio, principal, pautas = ("Média" if fortes & set(sinais) else "Baixa"), "Outras", ["Outras"]
    else:
        return None
    if destaque:
        prio = "Alta"
    it.update(pautas=pautas, pauta=principal, prioridade=prio, sinais=sinais, destaque=bool(destaque), motivo_destaque=", ".join(destaque) or None)
    it["autor"] = ocultar_autor(it.get("autor"), c)
    return it


def ocultar_autor(autor, c):
    """Troca só o nome vetado (regra da casa) por 'outro parlamentar', mantendo os coautores."""
    if not autor:
        return autor
    for n in (c.get("ocultar_autores") or {}).get("nomes") or []:
        pad = r"(?:Deputad[oa]\s+|Dep\.\s*)?" + r"\s+".join(re.escape(p) for p in n.split())
        autor = re.sub(pad, "outro parlamentar", autor, flags=re.I)
    return autor


# ---------- novidade, alertas, boletim ----------
def assinatura(it):
    return hashlib.sha1(json.dumps([it["data"], it["hora"], it.get("etapa"), it.get("regime"), it.get("status_pauta"), it.get("situacao_evento")],
                                   ensure_ascii=False).encode()).hexdigest()[:12]


def marcar_novidade(itens, estado, hoje):
    vistos = estado.setdefault("itens", {})
    for it in itens:
        h = assinatura(it)
        v = vistos.get(it["id"])
        it["novidade"] = "novo" if not v else ("mudou" if v["hash"] != h else "repetido")
        vistos[it["id"]] = {"hash": h, "primeira_vez": (v or {}).get("primeira_vez") or hoje.isoformat(), "data": it["data"]}
    corte = (hoje - timedelta(days=10)).isoformat()
    estado["itens"] = {k: v for k, v in vistos.items() if (v.get("data") or "9999") >= corte}


def gerar_alertas(itens, estado, hoje):
    amanha = (hoje + timedelta(days=1)).isoformat()
    ja = estado.setdefault("alertas", {})
    novos, sessoes_extra, votacoes = [], set(), {}
    quando_de = lambda it: f"{datetime.fromisoformat(it['data']).strftime('%d/%m')}" + (f" às {it['hora']}" if it.get("hora") else "")

    def emitir(chave, frase, it, tipo):
        if chave in ja:
            return
        ja[chave] = datetime.now(BRT).isoformat(timespec="minutes")
        novos.append({"chave": chave, "titulo": frase, "link": it.get("link") or it.get("link_evento"), "horario": quando_de(it),
                      "origem": "Agenda", "fonte": it["casa"], "calor": 1.0, "menciona_dayse": it["destaque"], "motivo": tipo, "item": it["id"]})

    for it in itens:
        quando, nome = quando_de(it), it.get("proposicao") or it.get("evento")
        dia = "hoje" if it["data"] == hoje.isoformat() else "amanhã" if it["data"] == amanha else None
        if it.get("extraordinaria") and it["plenario"] and f"{it['casa']}:{it['data']}" not in sessoes_extra:
            sessoes_extra.add(f"{it['casa']}:{it['data']}")
            emitir(f"agenda:{it['casa']}:{it['data']}:extra", f"{it['casa']}: sessão extraordinária marcada para {quando}.", it, "extra")
        if "Saúde" in it["pautas"] and "urgência" in it["sinais"]:
            emitir(f"agenda:{it['id']}:urg-saude", f"{it['casa']}: {nome} (saúde) em regime de urgência, {quando}.", it, "urg-saude")
        if it["destaque"] and "Dayse" in (it.get("motivo_destaque") or ""):
            # item da Dayse: um alerta só, já dizendo se vota hoje/amanhã
            frase = f"{it['casa']}: {nome}, da Dayse, " + (f"vai a votação {dia}, {quando}." if dia and it["tipo_item"] == "proposicao" else f"está na pauta de {quando}.")
            emitir(f"agenda:{it['id']}:dayse", frase, it, "dayse")
        elif it["tipo_item"] == "proposicao" and dia and it["prioridade"] == "Alta":
            # os demais itens importantes de hoje/amanhã viram UM alerta por sessão/reunião
            votacoes.setdefault((it["casa"], it["data"], it.get("hora"), it.get("evento", "").split(" (item")[0]), []).append(it)
    for (casa, data, hora, evento), its in votacoes.items():
        it0, dia = its[0], "hoje" if data == hoje.isoformat() else "amanhã"
        temas = sorted({i["pauta"] for i in its})
        nomes = ", ".join(i.get("proposicao") for i in its[:3]) + (f" e mais {len(its) - 3}" if len(its) > 3 else "")
        onde = "o plenário" if it0["plenario"] else evento.split(" · ")[-1]
        frase = f"{casa}: {dia} ({quando_de(it0)}) {onde} vota {len(its)} {'item' if len(its) == 1 else 'itens'} de prioridade alta ({', '.join(temas)}): {nomes}."
        emitir(f"agenda:votacao:{casa}:{data}:{hora}:{evento}", frase, {**it0, "link": it0.get("link_evento") or it0.get("link")}, "votacao")
    corte = (datetime.now(BRT) - timedelta(days=30)).isoformat()
    estado["alertas"] = {k: v for k, v in ja.items() if v >= corte}
    return novos


def resumo_tres_linhas(itens, alertas, ini, fim):
    rel = [i for i in itens if i["tipo_item"] != "sessao"]
    novos = sum(1 for i in rel if i["novidade"] != "repetido")
    por_casa = {c: sum(1 for i in rel if i["casa"] == c) for c in ("CLDF", "Câmara", "Senado", "Congresso")}
    casas = " · ".join(f"{c} {n}" for c, n in por_casa.items() if n)
    l1 = f"{len(rel)} itens relevantes entre {ini.strftime('%d/%m')} e {fim.strftime('%d/%m')} ({novos} novos ou com mudança){': ' + casas if casas else ''}."
    top = sorted([i for i in rel if i["prioridade"] == "Alta"],
                 key=lambda i: (not i["destaque"], not i["plenario"], i["tipo_item"] != "proposicao", not i["confirmado"], i["data"], i.get("hora") or ""))[:3]
    l2 = "Mais importantes: " + ("; ".join(f"{i['casa']} {fmt_dia(i['data'], curto=True)} · {i.get('proposicao') or ''} {frase_curta(i.get('resumo_simples') or i['ementa'], 70)}".replace("  ", " ") for i in top)
                                 if top else "nenhum item de prioridade alta na janela.")
    l3 = ("Urgente: " + " ".join(a["titulo"] for a in alertas[:3])) if alertas else "Nada urgente nesta rodada."
    return [l1, l2, l3]


def fmt_dia(iso, curto=False):
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()][:3]} {d.strftime('%d/%m')}" if curto else f"{DIAS[d.weekday()].capitalize()}, {d.strftime('%d/%m/%Y')}"


ICONE_NOV = {"novo": "🆕 ", "mudou": "✏️ ", "repetido": ""}


def boletim_md(dados):
    L = [f"# Agenda Legislativa · {fmt_dia(dados['data'])} ({'tarde' if dados['rodada'] == 'tarde' else 'manhã'})", "",
         f"_Gerado às {dados['gerado'][11:16]} · janela {dados['janela']['de'][8:10]}/{dados['janela']['de'][5:7]} a {dados['janela']['ate'][8:10]}/{dados['janela']['ate'][5:7]} · "
         "🆕 novo · ✏️ mudou desde a última checagem_", "", "## Resumo", ""]
    L += [f"- {l}" for l in dados["resumo"]] + [""]
    if dados["alertas"]:
        L += ["## 🚨 Alertas", ""] + [f"- {a['titulo']} [fonte]({a['link']})" for a in dados["alertas"]] + [""]
    if dados["avisos"]:
        L += ["## Avisos das fontes", ""] + [f"- {a}" for a in dados["avisos"]] + [""]
    por_dia = {}
    for it in dados["itens"]:
        por_dia.setdefault(it["data"], []).append(it)
    for d in sorted(por_dia):
        L += [f"## {fmt_dia(d)}", ""]
        lst = sorted(por_dia[d], key=lambda i: (PRIORIDADES[i["prioridade"]], not i["destaque"], i.get("hora") or "", i["casa"]))
        cheios = [i for i in lst if i["novidade"] != "repetido" and i["prioridade"] != "Baixa" and i["tipo_item"] != "sessao"]
        baixos = [i for i in lst if i["novidade"] != "repetido" and (i["prioridade"] == "Baixa" or i["tipo_item"] == "sessao")]
        repetidos = [i for i in lst if i["novidade"] == "repetido"]
        for i in cheios:
            estrela = "⭐ " if i["destaque"] else ""
            L.append(f"### {ICONE_NOV[i['novidade']]}{estrela}{i.get('hora') or '--:--'} · {i['casa']} · {i.get('proposicao') or i['evento']}")
            L.append(f"**{i['prioridade']} · {', '.join(i['pautas'])}**" + (f" · {i['motivo_destaque']}" if i["destaque"] else "")
                     + (f" · sinais: {', '.join(i['sinais'])}" if i["sinais"] else ""))
            L.append("")
            L.append(i.get("resumo_simples") or frase_curta(i["ementa"]))
            L.append("")
            det = [f"Onde: {i['evento']}"]
            if i.get("autor"):
                det.append(f"Autor: {i['autor']}")
            if i.get("etapa"):
                det.append(f"Etapa: {frase_curta(i['etapa'], 220)}")
            det.append(f"Pauta: {'✅ confirmada' if i['confirmado'] else '⏳ expectativa'} ({i['status_pauta']})")
            det.append(f"[Fonte oficial]({i['link'] or i['link_evento']})")
            L += [f"- {x}" for x in det] + [""]
        if baixos:
            L += [f"**Outros itens do dia ({len(baixos)})**", ""]
            L += [f"- {ICONE_NOV[i['novidade']]}{i.get('hora') or ''} {i['casa']} · {i.get('proposicao') or i['evento']}: {frase_curta(i.get('resumo_simples') or i['ementa'], 140)} "
                  f"({i['pauta']}{', ' + ', '.join(i['sinais']) if i['sinais'] else ''}) [fonte]({i['link'] or i['link_evento']})" for i in baixos]
            L.append("")
        if repetidos:
            L += [f"<details><summary>Já reportados, sem mudança ({len(repetidos)})</summary>", ""]
            L += [f"- {i.get('hora') or ''} {i['casa']} · {i.get('proposicao') or i['evento']} ({i['prioridade']} · {i['pauta']}) [fonte]({i['link'] or i['link_evento']})" for i in repetidos]
            L += ["", "</details>", ""]
    if not por_dia:
        L += ["Nenhum item relevante encontrado na janela.", ""]
    L += ["## Fontes consultadas", ""]
    for f in dados["fontes"]:
        L.append(f"- {'✅' if f['ok'] else '❌'} {f['nome']}: " + (f"{f.get('itens', 0)} itens lidos" if f["ok"] else f"falhou ({f.get('erro')})") + f" · {f['url']}")
    L += ["", "_Regras: nada aqui é inventado; ✅ = está na pauta publicada; ⏳ = expectativa (agenda marcada, pauta ainda não publicada). "
          "A pauta do plenário costuma fechar poucos dias antes._", ""]
    return "\n".join(L)


# ---------- execução ----------
def rodar(rodada=None, alertas_painel=True, verbose=True):
    t_ini = time.time()
    c = cfg()
    agora = datetime.now(BRT)
    hoje = agora.date()
    rodada = rodada or ("tarde" if agora.hour >= 12 else "manha")
    ini, fim = hoje, hoje + timedelta(days=int(c.get("janela_dias", 8)))
    estado = _ler(ESTADO, {})
    fontes, avisos, brutos = [], [], []

    def fonte(nome, url, func, *args):
        log = {}
        t = time.time()
        try:
            r = func(*args, log)
            fontes.append({"nome": nome, "url": url, "ok": True, "itens": len(r), "ms": int((time.time() - t) * 1000), **log})
            return r
        except Exception as x:  # noqa: BLE001 — a fonte fora do ar vai para o boletim, não some em silêncio
            fontes.append({"nome": nome, "url": url, "ok": False, "erro": str(x)[:200], "ms": int((time.time() - t) * 1000), **log})
            avisos.append(f"{nome}: fonte fora do ar ou com erro ({str(x)[:120]}). Os itens dessa fonte podem estar faltando.")
            return []

    brutos += fonte("Câmara dos Deputados · eventos e pautas", "https://dadosabertos.camara.leg.br", coletar_camara, ini, fim)
    brutos += fonte("Senado · agenda do plenário", "https://legis.senado.leg.br/dadosabertos/plenario/agenda/mes", coletar_senado_plenario, ini, fim)
    brutos += fonte("Senado · agenda das comissões", "https://legis.senado.leg.br/dadosabertos/comissao/agenda", coletar_senado_comissoes, ini, fim)
    brutos += fonte("CLDF · Ordem do Dia (PDF), agenda e PLe", CLDF_OD, lambda a, b, log: coletar_cldf(a, b, estado, log, avisos), ini, fim)
    props_dayse = proposicoes_dayse(estado, {})

    itens, vistos = [], set()
    for it in brutos:
        if it["id"] in vistos:
            continue
        vistos.add(it["id"])
        if it.get("situacao_evento") == "Cancelada" and it["id"] not in estado.get("itens", {}):
            continue
        if classificar(it, c, props_dayse):
            itens.append(it)
    log_autores = {}
    autores_camara(itens, log_autores)
    for it in itens:
        it.pop("_id_prop", None)
        it["autor"] = ocultar_autor(it.get("autor"), c)
    # mantém o resumo simples já escrito numa rodada anterior do mesmo dia
    arq_anterior = _ler(PASTA / f"{hoje.isoformat()}.json", {}) or {}
    anterior = {i["id"]: i for i in arq_anterior.get("itens", [])}
    for it in itens:
        if anterior.get(it["id"], {}).get("resumo_simples") and anterior[it["id"]].get("ementa") == it["ementa"]:
            it["resumo_simples"] = anterior[it["id"]]["resumo_simples"]
    marcar_novidade(itens, estado, hoje)
    itens.sort(key=lambda i: (i["data"], PRIORIDADES[i["prioridade"]], not i["destaque"], i.get("hora") or ""))
    novos_alertas = gerar_alertas(itens, estado, hoje)
    # o boletim guarda todos os alertas do dia; só os novos vão para o sino
    vistos_a = {a["chave"] for a in novos_alertas}
    alertas = [a for a in arq_anterior.get("alertas", []) if a["chave"] not in vistos_a] + novos_alertas
    dados = {"data": hoje.isoformat(), "rodada": rodada, "gerado": agora.isoformat(timespec="minutes"),
             "janela": {"de": ini.isoformat(), "ate": fim.isoformat()}, "resumo": resumo_tres_linhas(itens, alertas, ini, fim),
             "avisos": avisos, "fontes": fontes, "alertas": alertas, "alertas_novos": novos_alertas, "itens": itens,
             "contagem": {"total": len(itens), "novos": sum(1 for i in itens if i["novidade"] == "novo"),
                          "mudaram": sum(1 for i in itens if i["novidade"] == "mudou"),
                          **{p: sum(1 for i in itens if i["prioridade"] == p) for p in PRIORIDADES}}}
    entregar(dados, c, alertas_painel)
    _gravar(ESTADO, estado)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"quando": dados["gerado"], "rodada": rodada, "segundos": round(time.time() - t_ini, 1),
                            "fontes": [{k: v for k, v in x.items() if k != "url"} for x in fontes], "itens": len(itens),
                            "novos": dados["contagem"]["novos"], "mudaram": dados["contagem"]["mudaram"], "alertas": len(novos_alertas),
                            "avisos": avisos}, ensure_ascii=False) + "\n")
    if verbose:
        print("\n".join(dados["resumo"]))
        for a in avisos:
            print("AVISO:", a)
    return dados


def entregar(dados, c, alertas_painel=True):
    """Canais de saída (agenda_config.json → saidas). Novo canal = nova função aqui."""
    s = c.get("saidas") or {}
    if s.get("arquivo", True):
        salvar_arquivos(dados)
    if s.get("painel", True) and alertas_painel and dados["alertas_novos"]:
        try:
            import alertas as al
            al.enfileirar([{k: a[k] for k in ("chave", "titulo", "link", "origem", "fonte", "calor", "menciona_dayse")} for a in dados["alertas_novos"]])
        except Exception as x:  # noqa: BLE001
            dados["avisos"].append(f"Não consegui pôr os alertas no painel ({x}).")
    if s.get("email"):
        dados["avisos"].append("Entrega por e-mail ainda não configurada (falta conta de envio).")


def salvar_arquivos(dados):
    PASTA.mkdir(parents=True, exist_ok=True)
    _gravar(PASTA / f"{dados['data']}.json", dados)
    nome = f"{dados['data']}{'-tarde' if dados['rodada'] == 'tarde' else ''}.md"
    (PASTA / nome).write_text(boletim_md(dados), encoding="utf-8")
    if dados.get("alertas_novos"):
        with open(PASTA / "alertas.md", "a", encoding="utf-8") as f:
            f.write(f"\n## {dados['gerado'][:16].replace('T', ' ')}\n\n" + "".join(f"- {a['titulo']} {a['link']}\n" for a in dados["alertas_novos"]))


def refazer_boletim(dia=None):
    """Regrava o .md a partir do .json (depois que a rotina escreve os resumos simples)."""
    dia = dia or hoje_brt().isoformat()
    dados = _ler(PASTA / f"{dia}.json", None)
    if not dados:
        return f"sem {dia}.json"
    dados["resumo"] = resumo_tres_linhas(dados["itens"], dados["alertas"], date.fromisoformat(dados["janela"]["de"]), date.fromisoformat(dados["janela"]["ate"]))
    _gravar(PASTA / f"{dia}.json", dados)
    nome = f"{dia}{'-tarde' if dados['rodada'] == 'tarde' else ''}.md"
    (PASTA / nome).write_text(boletim_md(dados), encoding="utf-8")
    return f"boletim regravado: {nome}"


def gravar_resumos(arquivo, dia=None):
    """Junta os resumos em linguagem simples ({id: texto}) escritos pela rotina e regrava o boletim."""
    dia = dia or hoje_brt().isoformat()
    dados = _ler(PASTA / f"{dia}.json", None)
    resumos = _ler(arquivo, {})
    if not dados or not isinstance(resumos, dict):
        return "nada para gravar"
    n = 0
    for it in dados["itens"]:
        if limpa(resumos.get(it["id"])):
            it["resumo_simples"] = limpa(resumos[it["id"]])
            n += 1
    _gravar(PASTA / f"{dia}.json", dados)
    return f"{n} resumo(s) gravado(s); " + refazer_boletim(dia)


def pendentes_de_resumo(dia=None):
    """Lista (id, casa, proposição, ementa) dos itens Alta/Média ainda sem resumo simples."""
    dados = _ler(PASTA / f"{dia or hoje_brt().isoformat()}.json", None) or {}
    return [{"id": i["id"], "casa": i["casa"], "proposicao": i.get("proposicao"), "ementa": i["ementa"]}
            for i in dados.get("itens", []) if not i.get("resumo_simples") and i["prioridade"] != "Baixa" and i["tipo_item"] == "proposicao"]


def ultimo():
    arqs = sorted(PASTA.glob("????-??-??.json"))
    return _ler(arqs[-1], None) if arqs else None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if "--so-boletim" in a:
        print(refazer_boletim())
    elif "--pendentes" in a:
        # grava em arquivo (o terminal do Windows estraga acentos em pipe)
        destino = PASTA / "pendentes_resumo.json"
        p = pendentes_de_resumo()
        _gravar(destino, p)
        print(f"{len(p)} item(ns) sem resumo simples → {destino}")
    elif "--resumos" in a:
        print(gravar_resumos(a[a.index("--resumos") + 1]))
    else:
        rd = a[a.index("--rodada") + 1] if "--rodada" in a else None
        rodar(rodada=rd, alertas_painel="--sem-alertas" not in a)
