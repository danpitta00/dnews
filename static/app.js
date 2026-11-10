// Painel local do Radar da Dayse. Lê /api/* do server.py e organiza tudo por dia.
const URG = ["Alta", "Média", "Baixa"];
const TIPOS = {
  "Cobrança": { cor: "#E8590C", ic: "ti-speakerphone" },
  "Fiscalização": { cor: "#047B98", ic: "ti-zoom-check" },
  "Conteúdo": { cor: "#2EB8BE", ic: "ti-camera" },
  "Ação legislativa": { cor: "#0E3B4C", ic: "ti-gavel" },
  "Defesa/risco": { cor: "#D63939", ic: "ti-shield-exclamation" },
};
const PILARES = {
  "Saúde": { cor: "#047B98", ic: "ti-stethoscope" },
  "Guará": { cor: "#2EB8BE", ic: "ti-home-heart" },
  "Mulheres": { cor: "#C2185B", ic: "ti-gender-female" },
  "Transversais": { cor: "#6B7A88", ic: "ti-arrows-cross" },
  "Política e orçamento": { cor: "#0E3B4C", ic: "ti-building-bank" },
  "Menções": { cor: "#F8AA12", ic: "ti-user-check" },
};
const STATUS = { encaminhado: ["Encaminhar", "ti-send"], feito: ["Feito", "ti-check"], descartado: ["Descartar", "ti-x"] };

const st = {
  dias: [], hoje: null, dia: null, dados: null, feeds: null, estado: {}, todos: null, midia: {},
  f: { busca: "", escopo: "dia", status: "abertos", urg: new Set(), tipo: new Set(), pilar: new Set() },
  n: { busca: "", ordem: "recente", pilar: new Set() },
  aba: "geral", rel: "relatorio",
};

// ---------- utilidades ----------
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (t) => (t ? DOMPurify.sanitize(marked.parse(t)) : '<p class="vazio">Sem relatório para este dia.</p>');
const slug = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
const idItem = (dia, it) => `${dia}#${slug(it.titulo)}`;
const statusDe = (id) => (st.estado[id] || {}).status || "novo";
const SEM = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const dt = (iso) => new Date(iso.length <= 10 ? iso + "T12:00:00" : iso);
const fmtData = (iso) => { if (!iso) return ""; const p = iso.split("-"); return p.length === 3 ? `${p[2]}/${p[1]}` : p.length === 2 ? `${p[1]}/${p[0]}` : iso; };
const diasAte = (iso) => (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? Math.round((dt(iso) - dt(st.hoje)) / 864e5) : null);
const quandoTxt = (d) => (d < 0 ? `venceu há ${-d}d` : d === 0 ? "hoje" : d === 1 ? "amanhã" : `em ${d} dias`);
const classeDias = (d) => (d < 0 ? "vencido" : d <= 7 ? "perto" : "longe");
function haQuanto(iso) {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso)) / 6e4);
  if (min < 60) return `há ${Math.max(min, 1)} min`;
  if (min < 1440) return `há ${Math.round(min / 60)} h`;
  return `há ${Math.round(min / 1440)} d`;
}
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
const pilarCor = (p) => (PILARES[p] || { cor: "#6B7A88" }).cor;
const pilarIc = (p) => (PILARES[p] || { ic: "ti-news" }).ic;

async function api(c, opts) { const r = await fetch(c, { cache: "no-store", ...opts }); if (!r.ok) throw new Error(`${c}: ${r.status}`); return r.json(); }

// ---------- peças visuais ----------
function capa(img, opts = {}) {
  const { video, pilar, rotulo, faixa = "" } = opts;
  const fundo = `background:linear-gradient(135deg, ${pilarCor(pilar)}, #0E3B4C)`;
  const semImg = `<div class="sem-img" style="${fundo}"><div><i class="ti ${pilarIc(pilar)}"></i><span>${esc(rotulo || pilar || "")}</span></div></div>`;
  const imagem = img ? `<img src="${esc(img)}" loading="lazy" referrerpolicy="no-referrer" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'sem-img',style:'${fundo}',innerHTML:'<i class=\\'ti ${pilarIc(pilar)}\\'></i>'}))">` : semImg;
  const play = video ? `<div class="play" data-video="${esc(video)}" data-vtitulo="${esc(opts.titulo || "")}"><i class="ti ti-player-play-filled"></i></div>` : "";
  return `<div class="capa">${imagem}${play}<div class="faixa">${faixa}</div></div>`;
}
const seloUrg = (u) => `<span class="selo u-${esc(u)}">${u === "Alta" ? '<i class="ti ti-flame"></i>' : ""}${esc(u || "?")}</span>`;
const seloTipo = (t) => `<span class="selo tipo"><i class="ti ${(TIPOS[t] || {}).ic || "ti-tag"}" style="color:${(TIPOS[t] || {}).cor}"></i>${esc(t)}</span>`;
const seloPilar = (p) => (p ? `<span class="selo" style="background:${pilarCor(p)}1f;color:${pilarCor(p)}"><i class="ti ${pilarIc(p)}"></i>${esc(p)}</span>` : "");
function seloPrazo(iso) {
  const d = diasAte(iso);
  if (!iso) return "";
  return `<span class="selo prazo ${d !== null && d > 7 ? "longe" : ""}"><i class="ti ti-clock"></i>${fmtData(iso)}${d !== null ? " · " + quandoTxt(d) : ""}</span>`;
}

// mídia de cada item do radar: do JSON (campo "midia") ou buscada na página da matéria
function midiaDoItem(it) {
  if (it.midia && it.midia.length) {
    const img = it.midia.find((m) => m.tipo === "imagem"), vid = it.midia.find((m) => m.tipo === "video");
    return { imagem: img && img.url, video: vid && (vid.youtube || vid.url) };
  }
  const url = (it.links || [])[0];
  return url ? st.midia[url] || null : null;
}
async function carregarMidias(itens) {
  const faltam = [...new Set(itens.filter((i) => !(i.midia && i.midia.length)).map((i) => (i.links || [])[0]).filter((u) => u && !(u in st.midia)))];
  if (!faltam.length) return;
  faltam.forEach((u) => (st.midia[u] = null));
  await Promise.all(faltam.map(async (u) => { try { st.midia[u] = await api("/api/midia?url=" + encodeURIComponent(u)); } catch (e) { st.midia[u] = {}; } }));
  renderGeral(); if (st.aba === "radar") renderRadar(); if (st.aba === "videos") renderVideos();
}

function cardRadar(it, grande) {
  const s = statusDe(it._id), m = midiaDoItem(it) || {};
  const faixa = seloUrg(it.urgencia) + (it.tipo || []).map(seloTipo).join("");
  const flags = [it.checar_tom ? '<span class="selo flag"><i class="ti ti-alert-triangle"></i>checar tom com o gabinete</span>' : "",
    it.a_confirmar ? '<span class="selo flag"><i class="ti ti-help-circle"></i>a confirmar</span>' : ""].join("");
  const links = (it.links || []).map((l) => `<a href="${esc(l)}" target="_blank" rel="noopener"><i class="ti ti-external-link"></i> ${esc(host(l))}</a>`).join("");
  const botoes = Object.entries(STATUS).map(([k, [rot, ic]]) => `<button class="bt ${s === k ? "ativo" : ""}" data-status="${k}" data-id="${esc(it._id)}" title="${rot}"><i class="ti ${ic}"></i>${grande ? " " + rot : ""}</button>`).join("")
    + (s !== "novo" ? `<button class="bt" data-status="novo" data-id="${esc(it._id)}" title="Reabrir"><i class="ti ti-rotate"></i></button>` : "");
  return `<article class="mcard st-${s}">
    ${capa(m.imagem, { video: m.video, pilar: it.pilar, faixa, titulo: it.titulo, rotulo: it.veiculo })}
    <div class="corpo">
      <div class="meta">${seloPilar(it.pilar)}${seloPrazo(it.prazo)}${flags}${s !== "novo" ? `<span class="selo st">${esc(s)}</span>` : ""}</div>
      <h3>${esc(it.titulo)}</h3>
      <div class="meta"><span>${esc(it.veiculo || "")}</span>${it.data_fonte ? `<span>· ${fmtData(it.data_fonte)}</span>` : ""}${st.f.escopo === "todos" ? `<span>· radar de ${fmtData(it._dia)}</span>` : ""}</div>
      <p class="fato">${esc(it.fato)}</p>
      ${it.angulo ? `<div class="angulo">“${esc(it.angulo)}” <button class="bt" data-copiar="${esc(it.angulo)}" title="Copiar"><i class="ti ti-copy"></i></button></div>` : ""}
      <div class="acao"><i class="ti ti-arrow-big-right-lines"></i><div><b>Ação:</b> ${esc(it.acao)}</div></div>
      ${it.conexao ? `<details class="detalhes"><summary>Conexão com o que a Dayse já tem</summary><p>${esc(it.conexao)}</p></details>` : ""}
      <div class="rodape-card"><div class="links">${links}</div><div class="botoes">${botoes}</div></div>
    </div></article>`;
}

function linhaRadar(it) {
  const m = midiaDoItem(it) || {};
  const mini = m.imagem ? `<img src="${esc(m.imagem)}" loading="lazy" referrerpolicy="no-referrer" alt="" onerror="this.remove()">` : `<div class="sem-img" style="background:linear-gradient(135deg, ${pilarCor(it.pilar)}, #0E3B4C)"><i class="ti ${pilarIc(it.pilar)}"></i></div>`;
  return `<div class="linha-item" data-ir="radar"><div class="mini">${mini}</div><div class="txt">
    <div class="meta">${seloUrg(it.urgencia)}${(it.tipo || []).slice(0, 1).map(seloTipo).join("")}${seloPrazo(it.prazo)}</div>
    <div class="tit">${esc(it.titulo)}</div>
    <div class="meta">${esc(it.acao).slice(0, 140)}${(it.acao || "").length > 140 ? "…" : ""}</div></div></div>`;
}

function cardNoticia(n) {
  const link = n.link_original || n.link;
  const extra = (n.n_fontes > 1 ? `<span class="selo st"><i class="ti ti-stack-2"></i>${n.n_fontes} veículos</span>` : "")
    + (n.nacional ? '<span class="selo" style="background:#6B7A881f;color:#6B7A88"><i class="ti ti-world"></i>nacional</span>' : "");
  const faixa = (n.menciona_dayse ? '<span class="selo dayse"><i class="ti ti-star-filled"></i>Cita a Dayse</span>' : "") + (n.pilar ? `<span class="selo tipo"><i class="ti ${pilarIc(n.pilar)}" style="color:${pilarCor(n.pilar)}"></i>${esc(n.pilar)}</span>` : "");
  return `<a class="ncard" href="${esc(link)}" target="_blank" rel="noopener">
    ${capa(n.imagem, { video: n.video, pilar: n.pilar, faixa, titulo: n.titulo, rotulo: n.fonte })}
    <div class="corpo"><div class="meta"><b>${esc(n.fonte)}</b><span>· ${haQuanto(n.publicado)}</span>${extra}</div>
    <div class="tit">${esc(n.titulo)}</div>${n.resumo && !n.resumo.startsWith(n.titulo.slice(0, 25)) ? `<div class="res">${esc(n.resumo)}</div>` : ""}</div></a>`;
}

// ---------- dados ----------
function itensRadar() {
  if (st.f.escopo === "todos" && st.todos) return st.todos.map((it) => ({ ...it, _id: idItem(it._dia, it) }));
  return (((st.dados || {}).radar || {}).itens || []).map((it) => ({ ...it, _dia: st.dia, _id: idItem(st.dia, it) }));
}
const itensDoDia = () => ((((st.dados || {}).radar || {}).itens) || []).map((it) => ({ ...it, _dia: st.dia, _id: idItem(st.dia, it) }));
const noticias = () => ((st.feeds || {}).itens || []).filter((n) => !n.grupo || n.grupo === n.id);
const abertos = (l) => l.filter((i) => !["feito", "descartado"].includes(statusDe(i._id)));

function eventosComData() {
  const r = (st.dados || {}).radar || {}, ev = [];
  (r.fios || []).forEach((f) => f.prazo && ev.push({ data: f.prazo, titulo: f.fio, nota: `${f.status} · próximo marco: ${f.proximo_marco}`, origem: "Fio", ic: "ti-route" }));
  itensDoDia().forEach((i) => i.prazo && statusDe(i._id) !== "descartado" && ev.push({ data: i.prazo, titulo: i.titulo, nota: i.acao, origem: `Radar · ${i.urgencia}`, ic: "ti-target-arrow" }));
  (r.calendario || []).forEach((c) => ev.push({ data: c.data, titulo: c.titulo, nota: c.nota, origem: "Calendário", ic: "ti-calendar-event" }));
  const vistos = new Set();
  return ev.filter((e) => diasAte(e.data) !== null).sort((a, b) => a.data.localeCompare(b.data))
    .filter((e) => { const k = e.data + slug(e.titulo).slice(0, 25); if (vistos.has(k)) return false; vistos.add(k); return true; });
}

function videos() {
  const out = [], vistos = new Set();
  itensDoDia().forEach((it) => { const m = midiaDoItem(it); if (m && m.video && !vistos.has(m.video)) { vistos.add(m.video); out.push({ video: m.video, titulo: it.titulo, fonte: it.veiculo, imagem: m.imagem, pilar: it.pilar, quando: it.data_fonte, origem: "Radar" }); } });
  ((st.feeds || {}).itens || []).forEach((n) => { if (n.video && !vistos.has(n.video)) { vistos.add(n.video); out.push({ video: n.video, titulo: n.titulo, fonte: n.fonte, imagem: n.imagem, pilar: n.proprio ? "Menções" : n.pilar, quando: n.publicado, origem: n.proprio ? "Canal da Dayse" : "Notícias" }); } });
  return out;
}

// ---------- telas ----------
function renderGeral() {
  const itens = itensDoDia(), ab = abertos(itens), r = (st.dados || {}).radar || {};
  const alta = ab.filter((i) => i.urgencia === "Alta");
  const ev7 = eventosComData().filter((e) => { const d = diasAte(e.data); return d >= 0 && d <= 7; });
  const mencoes = ((st.feeds || {}).itens || []).filter((n) => n.menciona_dayse);
  const kpi = (ic, cor, num, rot, aba) => `<div class="kpi" data-ir="${aba}"><div class="ic" style="background:${cor}1a;color:${cor}"><i class="ti ${ic}"></i></div><div><div class="num">${num}</div><div class="rot">${rot}</div></div></div>`;
  $("#kpis").innerHTML = kpi("ti-flame", "#D63939", alta.length, "alta urgência", "radar")
    + kpi("ti-target-arrow", "#047B98", ab.length, `itens abertos no radar (de ${itens.length})`, "radar")
    + kpi("ti-calendar-due", "#E8590C", ev7.length, "prazos nos próximos 7 dias", "prazos")
    + kpi("ti-news", "#2EB8BE", noticias().length, "notícias coletadas hoje", "noticias");
  $("#resumo").innerHTML = (r.resumo || []).length
    ? `<h3><span>Resumo do dia</span><span>${esc(r.janela || "")}</span></h3><ul>${r.resumo.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`
    : `<h3><span>Resumo do dia</span></h3><ul><li>O radar curado deste dia ainda não saiu (roda às 7h). As notícias coletadas automaticamente estão em "Notícias ao vivo".</li></ul>`;
  $("#destaques").innerHTML = alta.length ? alta.map((i) => cardRadar(i, true)).join("") : '<p class="vazio">Nada de alta urgência em aberto.</p>';
  const resto = ab.filter((i) => i.urgencia !== "Alta");
  $("#radar-compacto").innerHTML = resto.length ? resto.map(linhaRadar).join("") : '<p class="vazio">Sem outros itens abertos.</p>';
  $("#prazos-mini").innerHTML = ev7.length ? `<div class="mini-lista">${ev7.map((e) => { const d = diasAte(e.data); return `<div class="l"><div class="dia-chip ${classeDias(d)}">${dt(e.data).getDate()}<small>${MES[dt(e.data).getMonth()]}</small></div><div><div class="t">${esc(e.titulo)}</div><div class="s">${quandoTxt(d)} · ${esc(e.origem)}</div></div></div>`; }).join("")}</div>` : '<p class="vazio">Nada nos próximos 7 dias.</p>';
  $("#mencoes").innerHTML = mencoes.length ? `<div class="mini-lista">${mencoes.slice(0, 6).map(miniNoticia).join("")}</div>` : '<p class="vazio">Nenhuma menção nas últimas 48 h.</p>';
  const top = noticias().slice().sort((a, b) => (b.n_fontes || 1) - (a.n_fontes || 1) || (b.publicado || "").localeCompare(a.publicado || "")).slice(0, 6);
  $("#imprensa-mini").innerHTML = top.length ? `<div class="mini-lista">${top.map(miniNoticia).join("")}</div>` : '<p class="vazio">Coleta ainda não rodou hoje.</p>';
}
function miniNoticia(n) {
  const img = n.imagem ? `<img src="${esc(n.imagem)}" loading="lazy" referrerpolicy="no-referrer" alt="" onerror="this.style.visibility='hidden'">` : `<div class="dia-chip longe"><i class="ti ${pilarIc(n.pilar)}"></i></div>`;
  return `<a href="${esc(n.link_original || n.link)}" target="_blank" rel="noopener">${img}<div><div class="t">${esc(n.titulo)}</div><div class="s">${esc(n.fonte)} · ${haQuanto(n.publicado)}${n.n_fontes > 1 ? ` · ${n.n_fontes} veículos` : ""}</div></div></a>`;
}

function filtrarRadar(lista, ignorar) {
  const f = st.f, q = f.busca.trim().toLowerCase();
  return lista.filter((it) => {
    const s = statusDe(it._id);
    if (f.status === "abertos" && (s === "feito" || s === "descartado")) return false;
    if (!["abertos", "todos"].includes(f.status) && s !== f.status) return false;
    if (ignorar !== "urg" && f.urg.size && !f.urg.has(it.urgencia)) return false;
    if (ignorar !== "tipo" && f.tipo.size && !(it.tipo || []).some((t) => f.tipo.has(t))) return false;
    if (ignorar !== "pilar" && f.pilar.size && !f.pilar.has(it.pilar)) return false;
    return !q || [it.titulo, it.fato, it.acao, it.veiculo, it.angulo, it.conexao].join(" ").toLowerCase().includes(q);
  });
}
function chips(el, valores, conj, contar, attr, cor) {
  $(el).innerHTML = valores.map((v) => `<span class="chip ${conj.has(v) ? "on" : ""}" data-${attr}="${esc(v)}">${cor ? `<span class="pon" style="background:${cor(v)}"></span>` : ""}${esc(v)}<span class="n">${contar(v)}</span></span>`).join("");
}
function renderRadar() {
  const base = itensRadar();
  chips("#f-urgencia", URG, st.f.urg, (u) => filtrarRadar(base, "urg").filter((i) => i.urgencia === u).length, "urg", (u) => ({ Alta: "#D63939", "Média": "#F8AA12", Baixa: "#B0BEC5" }[u]));
  chips("#f-tipo", Object.keys(TIPOS), st.f.tipo, (t) => filtrarRadar(base, "tipo").filter((i) => (i.tipo || []).includes(t)).length, "tipo", (t) => TIPOS[t].cor);
  const pils = [...new Set(base.map((i) => i.pilar).filter(Boolean))];
  chips("#f-pilar", pils, st.f.pilar, (p) => filtrarRadar(base, "pilar").filter((i) => i.pilar === p).length, "pilar", pilarCor);
  const lista = filtrarRadar(base), el = $("#lista-radar");
  if (st.f.escopo === "dia" && !(st.dados || {}).radar) { el.innerHTML = '<p class="vazio">Sem radar curado neste dia. Veja "Notícias ao vivo".</p>'; return; }
  if (!lista.length) { el.innerHTML = '<p class="vazio">Nenhum item com esses filtros.</p>'; return; }
  el.innerHTML = URG.map((u) => { const g = lista.filter((i) => i.urgencia === u); return g.length ? `<div class="grupo">${seloUrg(u)} ${g.length} ${g.length === 1 ? "item" : "itens"}</div><div class="grade-radar">${g.map((i) => cardRadar(i)).join("")}</div>` : ""; }).join("");
}

function renderNoticias() {
  const todas = noticias(), q = st.n.busca.trim().toLowerCase();
  const pils = [...new Set(todas.map((n) => n.pilar).filter(Boolean))];
  const semPilar = todas.filter((n) => !q || (n.titulo + " " + n.resumo + " " + n.fonte).toLowerCase().includes(q));
  chips("#n-pilar", pils, st.n.pilar, (p) => semPilar.filter((n) => n.pilar === p).length, "npilar", pilarCor);
  let lista = semPilar.filter((n) => !st.n.pilar.size || st.n.pilar.has(n.pilar));
  lista = lista.sort(st.n.ordem === "repercussao"
    ? (a, b) => (b.n_fontes || 1) - (a.n_fontes || 1) || (b.publicado || "").localeCompare(a.publicado || "")
    : (a, b) => (b.publicado || "").localeCompare(a.publicado || ""));
  lista.sort((a, b) => (b.menciona_dayse ? 1 : 0) - (a.menciona_dayse ? 1 : 0));
  $("#lista-noticias").innerHTML = lista.length ? lista.map(cardNoticia).join("") : '<p class="vazio">Nenhuma notícia coletada para este dia.</p>';
}

function renderVideos() {
  const v = videos();
  $("#lista-videos").innerHTML = v.length ? v.map((x) => `<article class="mcard">${capa(x.imagem || `https://i.ytimg.com/vi/${x.video}/hqdefault.jpg`, { video: x.video, pilar: x.pilar, titulo: x.titulo, faixa: `<span class="selo tipo"><i class="ti ti-brand-youtube" style="color:#D63939"></i>${esc(x.origem)}</span>` })}
    <div class="corpo"><h3>${esc(x.titulo)}</h3><div class="meta">${esc(x.fonte || "")}${x.quando ? " · " + (x.quando.length > 10 ? haQuanto(x.quando) : fmtData(x.quando)) : ""}</div></div></article>`).join("")
    : '<p class="vazio">Nenhum vídeo encontrado neste dia.</p>';
}

function renderPrazos() {
  const ev = eventosComData();
  let semana = null;
  $("#lista-prazos").innerHTML = ev.length ? ev.map((e) => {
    const d = diasAte(e.data);
    const s = d < 0 ? "Vencidos" : d <= 7 ? "Próximos 7 dias" : d <= 30 ? "Este mês" : "Mais adiante";
    const cab = s !== semana ? `<div class="lt-semana">${(semana = s)}</div>` : "";
    return cab + `<div class="lt-item"><div class="dia-chip ${classeDias(d)}">${dt(e.data).getDate()}<small>${MES[dt(e.data).getMonth()]}</small></div>
      <div><div class="tit"><i class="ti ${e.ic}"></i> ${esc(e.titulo)}</div><div class="nota">${quandoTxt(d)} · ${SEM[dt(e.data).getDay()]} · ${esc(e.origem)}${e.nota ? " · " + esc(e.nota) : ""}</div></div></div>`;
  }).join("") : '<p class="vazio">Nada com data neste radar.</p>';
}

async function renderRedes() {
  const r = await api("/api/redes"), ig = r.instagram || {}, yt = r.youtube || {}, ms = r.mapa_seguidores || {};
  const proprios = ((st.feeds || {}).itens || []).filter((n) => n.proprio);
  const card = (ic, nome, num, rot, url) => `<div class="rede"><div class="cab"><i class="ti ${ic}"></i>${esc(nome)}</div><div class="num">${esc(num)}</div><div class="rot">${esc(rot)}</div>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener" class="small">abrir <i class="ti ti-external-link"></i></a>` : ""}</div>`;
  $("#redes").innerHTML = `<div class="redes-grade">
      ${card("ti-brand-instagram", ig.perfil || "Instagram", ig.seguidores || "?", `seguidores · segue ${ig.seguindo ?? "?"} · ${ig.posts ?? "?"} posts · conferido ${fmtData(ig.conferido_em)}`, ig.url)}
      ${(r.outras || []).map((o) => card({ Threads: "ti-brand-threads", Facebook: "ti-brand-facebook", X: "ti-brand-x" }[o.rede] || "ti-world", o.rede, o.seguidores || o.perfil || "", o.seguidores ? "seguidores" : "", o.url)).join("")}
      ${card("ti-brand-youtube", yt.canal || "YouTube", proprios.length, "vídeos novos no canal (48 h)", yt.url)}
    </div>
    <div class="pendente"><b><i class="ti ti-hourglass"></i> Quem segue a Dayse e quem ela segue: ${esc(ms.status || "pendente")}</b><p class="mb-1">${esc(ms.como || "")}</p><p class="small text-secondary mb-0">${esc(ms.motivo || "")}</p></div>
    ${((r.canais_saude || {}).grupos || []).length ? `<h2 class="sec"><i class="ti ti-stethoscope"></i> Canais de saúde acompanhados</h2>
      ${r.canais_saude.grupos.map((g) => `<div class="grupo">${esc(g.grupo)}</div><div class="canais">${g.canais.map((c) => `<div class="canal">
        <div class="canal-nome">${esc(c.nome)}</div><div class="canal-o">${esc(c.acompanhar || "")}</div>
        <div class="canal-links">
          ${c.instagram ? `<a href="https://www.instagram.com/${esc(c.instagram)}/" target="_blank" rel="noopener"><i class="ti ti-brand-instagram"></i>@${esc(c.instagram)}${c.seguidores ? ` · ${esc(c.seguidores)}` : ""}</a>` : '<span class="falta"><i class="ti ti-brand-instagram"></i>a confirmar</span>'}
          ${c.youtube ? `<a href="https://www.youtube.com/channel/${esc(c.youtube)}" target="_blank" rel="noopener"><i class="ti ti-brand-youtube"></i>${esc(c.youtube_nome || "YouTube")}</a>` : ""}
          ${c.tiktok ? `<a href="https://www.tiktok.com/@${esc(c.tiktok)}" target="_blank" rel="noopener"><i class="ti ti-brand-tiktok"></i>TikTok</a>` : ""}
          ${c.site ? `<a href="${esc(c.site)}" target="_blank" rel="noopener"><i class="ti ti-world"></i>site</a>` : ""}
        </div>${c.obs ? `<div class="canal-obs">${esc(c.obs)}</div>` : ""}</div>`).join("")}</div>`).join("")}` : ""}
    <h2 class="sec"><i class="ti ti-broadcast"></i> Veículos acompanhados</h2>
    <div class="chips">${(r.imprensa_seguir || []).map((v) => `<span class="chip">${esc(v.nome)}${v.youtube_id ? ' <i class="ti ti-brand-youtube" style="color:#D63939"></i>' : ""}</span>`).join("")}</div>`;
}

async function renderRelatorio() {
  document.querySelectorAll("#sub-abas a").forEach((a) => a.classList.toggle("on", a.dataset.rel === st.rel));
  const d = st.dados || {}, el = $("#md-rel");
  const cab = (rot, data) => (data && data !== st.dia ? `<div class="alert alert-secondary py-2">${rot} mais recente até este dia: ${fmtData(data)}</div>` : "");
  if (st.rel === "fios") {
    const f = await api("/api/fios");
    el.innerHTML = f.linhas.length ? `<h3>Fios em acompanhamento</h3><table><thead><tr>${f.colunas.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${f.linhas.map((l) => `<tr>${l.map((c) => `<td>${DOMPurify.sanitize(marked.parseInline(c))}</td>`).join("")}</tr>`).join("")}</tbody></table>` : '<p class="vazio">Sem fios.</p>';
  } else if (st.rel === "pauta") el.innerHTML = cab("Pauta", d.pauta && d.pauta.data) + md(d.pauta && d.pauta.md);
  else if (st.rel === "drive") el.innerHTML = md(d.drive_md);
  else if (st.rel === "saude") el.innerHTML = cab("Checagem", d.saude && d.saude.data) + md(d.saude && d.saude.md);
  else el.innerHTML = md(d.radar_md);
  el.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener"; });
}

// ---------- Alertas (só no sistema, com alarme sonoro) ----------
const al = { conhecidos: null, audio: null, somLiberado: false, tituloOrig: document.title, pisca: null, dados: null };

function liberarSom() {  // navegadores só tocam som depois de um clique na página
  if (al.somLiberado) return;
  try { al.audio = al.audio || new (window.AudioContext || window.webkitAudioContext)(); al.audio.resume(); al.somLiberado = true; } catch (e) {}
  $("#btn-sino").classList.toggle("mudo", !al.somLiberado);
}
function tocarAlarme() {
  if (!al.audio || !al.somLiberado) return;
  const ctx = al.audio, t0 = ctx.currentTime;
  for (let i = 0; i < 3; i++) {  // três toques de sirene sobe-desce
    const o = ctx.createOscillator(), g = ctx.createGain(), t = t0 + i * 0.7;
    o.type = "sawtooth"; o.frequency.setValueAtTime(700, t); o.frequency.linearRampToValueAtTime(1300, t + 0.3); o.frequency.linearRampToValueAtTime(700, t + 0.6);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.05); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.62);
    o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + 0.65);
  }
}
function piscarTitulo(n) {
  clearInterval(al.pisca);
  if (!n) { document.title = al.tituloOrig; return; }
  let on = false;
  al.pisca = setInterval(() => { on = !on; document.title = on ? `🔥 (${n}) PAUTA QUENTE` : al.tituloOrig; }, 1000);
}

async function checarAlertas() {
  let r; try { r = await api("/api/alertas"); } catch (e) { return; }
  al.dados = r;
  const nv = r.nao_vistos || [];
  const novos = al.conhecidos ? nv.filter((a) => !al.conhecidos.has(a.chave)) : nv;
  al.conhecidos = new Set(nv.map((a) => a.chave));
  $("#n-alertas").textContent = nv.length || "";
  $("#btn-sino").classList.toggle("toca", nv.length > 0);
  const faixa = $("#faixa-alerta");
  if (!nv.length) { faixa.hidden = true; piscarTitulo(0); return; }
  $("#fa-txt").innerHTML = `<b>${nv.length} pauta${nv.length > 1 ? "s" : ""} quente${nv.length > 1 ? "s" : ""}</b><ul>${nv.slice(0, 4).map((a) =>
    `<li>${esc(a.titulo)} · ${esc(a.fonte || "")}${a.lugar ? " · 📍" + esc(a.lugar) : ""} · ${Math.round(a.calor * 100)}°${a.link ? ` · <a href="${esc(a.link)}" target="_blank" rel="noopener">abrir</a>` : ""}</li>`).join("")}${nv.length > 4 ? `<li>e mais ${nv.length - 4}…</li>` : ""}</ul>`;
  faixa.hidden = false;
  piscarTitulo(nv.length);
  if (novos.length) tocarAlarme();
}
function renderPainelAlertas() {
  const r = al.dados || { recentes: [] }, el = $("#painel-alertas");
  el.innerHTML = `<h4><span>Alertas de pauta quente</span><button class="bt" id="pa-teste" title="Tocar um alerta de teste"><i class="ti ti-volume"></i> testar</button></h4>`
    + ((r.recentes || []).length ? r.recentes.map((a) => `<div class="pa-item ${a.visto ? "visto" : ""}"><div class="hm-temp" style="background:${corCalor(a.calor)};width:36px;height:36px;font-size:.72rem">${Math.round(a.calor * 100)}°</div>
      <div><div class="t">${esc(a.titulo)}</div><div class="s">${esc(a.fonte || "")}${a.lugar ? " · " + esc(a.lugar) : ""} · ${haQuanto(a.quando)}${a.visto ? " · visto" : ""}</div>
      ${a.link ? `<a href="${esc(a.link)}" target="_blank" rel="noopener">abrir <i class="ti ti-external-link"></i></a>` : ""}</div></div>`).join("") : '<p class="vazio">Nenhum alerta ainda.</p>');
  el.hidden = false;
}

// ---------- Trilhas de notícia ----------
const tr = { lista: null, sel: null };
const favicon = (d) => (d ? `https://www.google.com/s2/favicons?sz=32&domain=${encodeURIComponent(d)}` : "");

async function carregarTrilhas() {
  tr.lista = await api("/api/trilhas");
  $("#n-trilhas").textContent = tr.lista.filter((t) => t.n).length || "";
  if (st.aba === "trilhas") renderTrilhas();
}

function renderTrilhas() {
  if (!tr.lista) { carregarTrilhas(); return; }
  const lista = tr.lista.filter((t) => t.n);
  const max = Math.max(1, ...lista.map((t) => t.n));
  $("#nuvem").innerHTML = lista.map((t) => {
    const tam = 0.8 + 1.1 * Math.sqrt(t.n / max);  // em rem
    const calado = t.fio && t.dias_sem_noticia >= 7 ? `<span class="calado">⏳ ${t.dias_sem_noticia}d</span>` : "";
    return `<span class="bolha ${t.automatica ? "auto" : ""} ${tr.sel === t.id ? "on" : ""}" data-trilha="${esc(t.id)}" style="font-size:${tam.toFixed(2)}rem;background:${corCalor(t.calor)}">${esc(t.titulo.length > 46 ? t.titulo.slice(0, 44) + "…" : t.titulo)}<small>${t.n}</small>${calado}</span>`;
  }).join("") + tr.lista.filter((t) => !t.n).map((t) => `<span class="bolha" data-trilha="${esc(t.id)}" style="font-size:.75rem;background:#B0BEC5">${esc(t.titulo)}<small>0</small></span>`).join("");
  $("#tr-lista").innerHTML = tr.lista.map((t) => `<div class="tr-card ${tr.sel === t.id ? "on" : ""}" data-trilha="${esc(t.id)}" style="border-left-color:${corCalor(t.calor)}">
      <div class="t">${t.automatica ? '<i class="ti ti-sparkles" title="trilha automática"></i> ' : ""}${esc(t.titulo)}</div>
      <div class="s">${seloPilar(t.pilar)}<span>${t.n} matérias · ${t.n_fontes} portais</span>${t.primeiro ? `<span>· ${fmtData(t.primeiro)} → ${fmtData(t.ultimo)}</span>` : ""}
        ${t.dias_sem_noticia >= 7 ? `<span class="selo prazo"><i class="ti ti-hourglass"></i>${t.dias_sem_noticia} dias sem notícia</span>` : ""}</div>
      <div class="spark" title="matérias por dia (30 dias)">${t.por_dia.map((n) => `<i class="${n ? "" : "zero"}" style="height:${n ? Math.min(100, 20 + n * 20) : 4}%"></i>`).join("")}</div>
    </div>`).join("");
  if (!tr.sel && tr.lista.length) abrirTrilha(tr.lista[0].id);
}

async function abrirTrilha(id) {
  tr.sel = id;
  document.querySelectorAll("[data-trilha]").forEach((e) => e.classList.toggle("on", e.dataset.trilha === id));
  const d = await api(`/api/trilha/${encodeURIComponent(id)}`), el = $("#tr-detalhe");
  const itens = (d.itens || []).filter((i) => i.publicado);
  let html = `<div class="tr-cab">${d.imagem ? `<img src="${esc(d.imagem)}" referrerpolicy="no-referrer" alt="" onerror="this.remove()">` : ""}
    <div><h3>${esc(d.titulo)}</h3><div class="s">${d.n} matérias em ${d.n_fontes} portais${d.primeiro ? ` · de ${fmtData(d.primeiro)} a ${fmtData(d.ultimo)}` : ""}${d.automatica ? " · trilha automática (3+ portais contando a mesma história)" : ""}</div>
    ${d.buscas ? `<div class="s">Buscas: ${d.buscas.map(esc).join(" · ")}</div>` : ""}</div></div>`;
  if (!itens.length) { el.innerHTML = html + '<p class="vazio">Nenhuma matéria encontrada nos últimos 90 dias.</p>'; return; }
  html += '<div class="tempo">';
  let diaAnt = null;
  itens.forEach((i, k) => {
    const dia = i.publicado.slice(0, 10);
    if (dia !== diaAnt) {
      if (diaAnt) {
        const gap = Math.round((dt(dia) - dt(diaAnt)) / 864e5) - 1;
        if (gap >= 3) html += `<div class="tm-silencio">··· ${gap} dias sem notícia ···</div>`;
      }
      const n = itens.filter((x) => x.publicado.slice(0, 10) === dia).length;
      html += `<div class="tm-dia">${SEM[dt(dia).getDay()]} ${fmtData(dia)}/${dia.slice(0, 4)} · ${n} ${n === 1 ? "matéria" : "matérias"}</div>`;
      diaAnt = dia;
    }
    const link = i.link_original || i.link;
    const hora = i.publicado.slice(11, 16);  // hora "redonda" é só a data da matéria, sem horário real
    html += `<div class="tm-item"><div class="tm-hora">${hora.endsWith(":00") ? "" : hora}</div>
      <div><div class="t"><a href="${esc(link)}" target="_blank" rel="noopener">${esc(i.titulo)}</a></div>
      <div class="f">${i.dominio ? `<img src="${favicon(i.dominio)}" alt="" onerror="this.remove()">` : ""}${esc(i.fonte)}${k === 0 ? ' <span class="tm-primeiro">primeiro a noticiar</span>' : ""}</div></div>
      ${i.imagem ? `<img class="mini" src="${esc(i.imagem)}" loading="lazy" referrerpolicy="no-referrer" alt="" onerror="this.remove()">` : "<span></span>"}</div>`;
  });
  if (d.dias_sem_noticia >= 3) html += `<div class="tm-silencio ${d.fio && d.dias_sem_noticia >= 7 ? "alerta" : ""}">⏳ ${d.dias_sem_noticia} dias sem notícia até hoje${d.fio && d.dias_sem_noticia >= 7 ? " · fio parado: cabe cobrança" : ""}</div>`;
  el.innerHTML = html + "</div>";
  el.scrollTop = el.scrollHeight;  // a parte mais recente fica à vista
}

// ---------- Hot Map ----------
const hm = { mapa: null, camada: null, dados: null, dias: 5, origem: new Set(), marcadores: {} };
const ESCALA = [[0, [43, 108, 176]], [0.35, [46, 184, 190]], [0.55, [248, 170, 18]], [0.75, [232, 89, 12]], [1, [214, 57, 57]]];
function corCalor(c) {
  c = Math.max(0, Math.min(1, c));
  for (let i = 1; i < ESCALA.length; i++) {
    const [p1, c1] = ESCALA[i - 1], [p2, c2] = ESCALA[i];
    if (c <= p2) { const t = (c - p1) / (p2 - p1); return `rgb(${c1.map((v, k) => Math.round(v + (c2[k] - v) * t)).join(",")})`; }
  }
  return "rgb(214,57,57)";
}
const rotuloCalor = (c) => (c >= 0.7 ? "quente" : c >= 0.4 ? "morno" : "frio");
const ORIGENS = { Radar: "ti-target-arrow", "Notícia": "ti-news", Cadastro: "ti-map-pin-plus" };

async function carregarHotmap() {
  hm.dados = await api(`/api/hotmap?dias=${hm.dias}`);
  $("#hm-lugares").innerHTML = hm.dados.lugares.map((l) => `<option value="${esc(l.nome)}">${esc(l.tipo)}</option>`).join("");
  $("#hm-nota").textContent = `Cada pauta esfria pela metade a cada ${String(hm.dados.meia_vida).replace(".0", "")} dias e some depois de ${hm.dias} dias. Pautas no mesmo lugar se somam.`;
  contadores();
  if (st.aba === "hotmap") renderHotmap();
}

function pontosFiltrados() {
  return ((hm.dados || {}).pontos || []).map((p) => {
    const pautas = p.pautas.filter((x) => !hm.origem.size || hm.origem.has(x.origem));
    if (!pautas.length) return null;
    if (pautas.length === p.pautas.length) return p;
    const maior = Math.max(...pautas.map((x) => x.calor)), soma = 1 - pautas.reduce((a, x) => a * (1 - x.calor), 1);
    return { ...p, pautas, n: pautas.length, calor: maior + 0.5 * (soma - maior) };
  }).filter(Boolean).sort((a, b) => b.calor - a.calor);
}

function popupPonto(p) {
  return `<div class="pp-tit">${esc(p.lugar)}</div>
    <div class="pp-sub">${Math.round(p.calor * 100)}° · ${rotuloCalor(p.calor)} · ${p.n} ${p.n === 1 ? "pauta" : "pautas"}${p.aprox ? " · posição aproximada" : ""}</div>
    ${p.pautas.map((x) => `<div class="pp-item"><span class="pon" style="background:${corCalor(x.calor)}"></span><div>
      <div class="t">${esc(x.titulo)}</div>
      <div class="s"><i class="ti ${ORIGENS[x.origem] || "ti-point"}"></i> ${esc(x.origem)} · ${esc(x.fonte || "")} · ${x.idade_dias < 1 ? "hoje" : `há ${Math.round(x.idade_dias)}d`} · ${Math.round(x.calor * 100)}°</div>
      ${x.link ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">abrir <i class="ti ti-external-link"></i></a>` : ""}
      ${x.id_manual ? ` <button class="pp-apagar" data-apagar-pauta="${esc(x.id_manual)}"><i class="ti ti-trash"></i> tirar do mapa</button>` : ""}
    </div></div>`).join("")}`;
}

function renderHotmap() {
  if (!window.L) { $("#hm-mapa").innerHTML = '<p class="vazio" style="padding:1rem">Não carregou o mapa (sem internet para o Leaflet).</p>'; return; }
  if (!hm.mapa) {
    hm.mapa = L.map("hm-mapa", { zoomControl: true, scrollWheelZoom: true }).setView([-15.80, -47.95], 10);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(hm.mapa);
    hm.camada = L.layerGroup().addTo(hm.mapa);
  }
  setTimeout(() => hm.mapa.invalidateSize(), 50);
  if (!hm.dados) { carregarHotmap(); return; }
  const contaOrigem = {};
  (hm.dados.pontos || []).forEach((p) => p.pautas.forEach((x) => (contaOrigem[x.origem] = (contaOrigem[x.origem] || 0) + 1)));
  $("#hm-origem").innerHTML = Object.keys(ORIGENS).map((o) => `<span class="chip ${hm.origem.has(o) ? "on" : ""}" data-hmorigem="${o}"><i class="ti ${ORIGENS[o]}"></i>${o}<span class="n">${contaOrigem[o] || 0}</span></span>`).join("");
  const pontos = pontosFiltrados();
  hm.camada.clearLayers(); hm.marcadores = {};
  pontos.slice().reverse().forEach((p) => {  // os quentes por cima
    const tam = Math.round(18 + 26 * p.calor), cor = corCalor(p.calor);
    const icone = L.divIcon({ className: "", iconSize: [tam, tam], iconAnchor: [tam / 2, tam / 2],
      html: `<div class="hm-pin ${p.calor >= (hm.dados.limiar || 0.7) ? "quente" : ""}" style="width:${tam}px;height:${tam}px;background:${cor};color:${cor}"><span style="color:#fff">${p.n > 1 ? p.n : ""}</span></div>` });
    hm.marcadores[p.lugar] = L.marker([p.lat, p.lon], { icon: icone, riseOnHover: true }).bindPopup(popupPonto(p), { maxWidth: 360 }).addTo(hm.camada);
  });
  $("#hm-ranking").innerHTML = pontos.length ? pontos.map((p) => `<div class="hm-rank" data-hmlugar="${esc(p.lugar)}">
      <div class="hm-temp" style="background:${corCalor(p.calor)}">${Math.round(p.calor * 100)}°</div>
      <div><div class="t">${esc(p.lugar)}</div><div class="s">${esc(p.pautas[0].titulo)}</div>
      <div class="s">${p.n} ${p.n === 1 ? "pauta" : "pautas"} · ${rotuloCalor(p.calor)}</div>
      <div class="hm-barra-calor"><i style="width:${Math.round(p.calor * 100)}%;background:${corCalor(p.calor)}"></i></div></div></div>`).join("")
    : '<p class="vazio">Nenhuma pauta com lugar nesta janela.</p>';
}

function abrirFormPauta() {
  const f = $("#form-pauta"); f.reset(); f.data.value = st.hoje; $("#form-erro").textContent = "";
  $("#int-rot").textContent = "4 · quente"; $("#modal-pauta").hidden = false; f.titulo.focus();
}

// ---------- agenda legislativa ----------
const ag = { r: null, casa: new Set(), pauta: new Set(), prio: new Set(), soNovos: false };
const AG_CASAS = { CLDF: "ti-building-community", "Câmara": "ti-building-bank", Senado: "ti-building-arch", Congresso: "ti-building-monument" };
const AG_PRIO = { Alta: "var(--vermelho)", "Média": "var(--ouro)", Baixa: "var(--cinza)" };
const AG_NOV = { novo: '<span class="ag-nov novo">🆕 novo</span>', mudou: '<span class="ag-nov mudou">✏️ mudou</span>', repetido: "" };

async function carregarAgenda(dia) {
  ag.r = await api(dia ? `/api/agenda/${dia}` : "/api/agenda");
  const d = (ag.r || {}).dados;
  $("#n-agenda").textContent = d ? (d.itens || []).filter((i) => i.prioridade === "Alta" && i.tipo_item !== "sessao").length || "" : "";
  $("#ag-checar").classList.toggle("girando", !!(ag.r.coleta || {}).rodando);
  if (st.aba === "agenda") renderAgenda();
}

function agFiltrados() {
  const d = (ag.r || {}).dados; if (!d) return [];
  return (d.itens || []).filter((i) => (!ag.casa.size || ag.casa.has(i.casa)) && (!ag.pauta.size || i.pautas.some((p) => ag.pauta.has(p)))
    && (!ag.prio.size || ag.prio.has(i.prioridade)) && (!ag.soNovos || i.novidade !== "repetido"));
}

function cardAgenda(i) {
  const link = i.link || i.link_evento;
  return `<article class="ag-item" style="--cor:${AG_PRIO[i.prioridade]}">
    <div class="ag-hora">${esc(i.hora || "--:--")}<small><i class="ti ${AG_CASAS[i.casa] || "ti-building"}"></i> ${esc(i.casa)}</small></div>
    <div class="ag-corpo">
      <div class="ag-tags"><span class="ag-prio">${esc(i.prioridade)}</span>${i.pautas.map((p) => `<span class="ag-pauta">${esc(p)}</span>`).join("")}
        ${i.destaque ? `<span class="ag-dayse">⭐ ${esc(i.motivo_destaque)}</span>` : ""}${AG_NOV[i.novidade] || ""}
        <span class="ag-conf ${i.confirmado ? "sim" : ""}" title="${esc(i.status_pauta || "")}">${i.confirmado ? "✅ pauta publicada" : "⏳ expectativa"}</span></div>
      <div class="ag-tit">${esc(i.proposicao || i.ementa)}</div>
      ${i.proposicao || i.resumo_simples ? `<div class="ag-res">${esc(i.resumo_simples || i.ementa)}</div>` : ""}
      <div class="ag-det"><span><i class="ti ti-map-pin"></i> ${esc(i.evento)}</span>${i.autor ? `<span><i class="ti ti-user"></i> ${esc(i.autor)}</span>` : ""}
        ${i.sinais && i.sinais.length ? `<span><i class="ti ti-bolt"></i> ${esc(i.sinais.join(", "))}</span>` : ""}</div>
      ${i.etapa ? `<details class="ag-etapa"><summary>Etapa da tramitação</summary>${esc(i.etapa)}</details>` : ""}
      ${link ? `<a class="ag-link" href="${esc(link)}" target="_blank" rel="noopener">fonte oficial <i class="ti ti-external-link"></i></a>` : ""}
    </div></article>`;
}

// --- visão de calendário (semana estilo Google Agenda; um dia no celular) ---
const cal = { semana: null, diaMob: null, grupos: {} };
const CAL_COR = { CLDF: "#047B98", "Câmara": "#2F7A3A", Senado: "#0E3B4C", Congresso: "#9A6700", "Várias": "#5B6B76" };
const CAL_H = 64;  // px por hora
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const pad2 = (n) => String(n).padStart(2, "0");
const isoLocal = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const somaDias = (iso, n) => { const d = dt(iso); d.setDate(d.getDate() + n); return isoLocal(d); };
const segundaDe = (iso) => somaDias(iso, -((dt(iso).getDay() + 6) % 7));
const minutos = (h) => { const m = /^(\d{1,2}):(\d{2})/.exec(h || ""); return m ? +m[1] * 60 + +m[2] : null; };
const estreito = () => window.innerWidth < 760;

function agruparAgenda(itens) {
  const g = {};
  itens.forEach((i) => {
    const ev = (i.evento || "").replace(/ \(item \d+ da Ordem do Dia\)/, "");
    const k = [i.casa, i.data, i.hora || "", ev].join("|");
    if (!g[k]) {
      const [tipo, onde] = ev.split(" · ");
      const titulo = i.tipo_item !== "proposicao" && i.casa === "CLDF" ? i.ementa : (onde || tipo);
      g[k] = { k, casa: i.casa, data: i.data, hora: i.hora, titulo, sub: onde ? tipo : "", plenario: i.plenario, link: i.link_evento, itens: [] };
    }
    g[k].itens.push(i);
  });
  const ORD = { Alta: 0, "Média": 1, Baixa: 2 };
  Object.values(g).forEach((x) => {
    x.itens.sort((a, b) => ORD[a.prioridade] - ORD[b.prioridade] || b.destaque - a.destaque);
    x.prio = x.itens[0].prioridade;
    x.destaque = x.itens.some((i) => i.destaque);
    x.novos = x.itens.filter((i) => i.novidade !== "repetido").length;
    x.altas = x.itens.filter((i) => i.prioridade === "Alta").length;
    x.props = x.itens.filter((i) => i.tipo_item === "proposicao").length;
    x.confirmado = x.itens.some((i) => i.confirmado);
    x.ini = minutos(x.hora);
    x.dur = x.plenario ? 180 : 60;  // a fonte não traz o fim: plenário ~3h, comissão ~1h (só para desenhar)
  });
  return g;
}

function blocoAgenda(x, lane, lanes, hIni) {
  const top = ((x.ini - hIni * 60) / 60) * CAL_H, alt = Math.max(30, (x.dur / 60) * CAL_H - 3);
  const n = x.props ? `${x.props} ${x.props === 1 ? "item" : "itens"}${x.altas ? ` · ${x.altas} alta` : ""}` : (x.confirmado ? "" : "pauta não publicada");
  return `<button class="cal-ev ${x.prio === "Alta" ? "alta" : ""} ${x.prio === "Baixa" ? "baixa" : ""} ${x.dur <= 60 ? "curto" : ""}" data-grupo="${esc(x.k)}"
    style="top:${top}px;height:${alt}px;left:calc(${(lane / lanes) * 100}% + 2px);width:calc(${100 / lanes}% - 4px);--c:${CAL_COR[x.casa] || "#5B6B76"}"
    title="${esc(`${x.hora || ""} ${x.casa} · ${x.titulo}${x.sub ? " · " + x.sub : ""}`)}">
    <span class="cal-ev-h">${esc(x.hora || "")} · ${esc(x.casa)}${x.destaque ? " ⭐" : ""}${x.novos ? " 🆕" : ""}</span>
    <b>${esc(x.titulo)}</b>
    ${x.sub ? `<span class="cal-ev-s">${esc(x.sub)}</span>` : ""}
    ${n ? `<span class="cal-ev-n">${n}</span>` : ""}</button>`;
}

const MAX_LANES = 4;
function multiGrupo(gs, titulo) {
  // vários blocos viram um só (abre a lista de reuniões no painel lateral)
  const ORD = { Alta: 0, "Média": 1, Baixa: 2 };
  const x0 = gs.slice().sort((a, b) => a.ini - b.ini)[0];
  const g = { ...x0, k: "multi|" + gs.map((y) => y.k).join("§"), filhos: gs.flatMap((y) => y.filhos || [y]), itens: gs.flatMap((y) => y.itens),
    titulo, sub: gs.map((y) => y.titulo).join(" · "), plenario: gs.some((y) => y.plenario),
    prio: gs.map((y) => y.prio).sort((a, b) => ORD[a] - ORD[b])[0], destaque: gs.some((y) => y.destaque),
    novos: gs.reduce((s, y) => s + y.novos, 0), altas: gs.reduce((s, y) => s + y.altas, 0), props: gs.reduce((s, y) => s + y.props, 0),
    confirmado: gs.some((y) => y.confirmado), dur: Math.max(...gs.map((y) => y.ini + y.dur)) - x0.ini };
  if (new Set(gs.map((y) => y.casa)).size > 1) g.casa = "Várias";
  cal.grupos[g.k] = g;
  return g;
}
const reunioes = (n) => `${n} ${n === 1 ? "reunião" : "reuniões"}`;

function lanesDe(cluster) {
  const lanes = [];
  cluster.forEach((x) => { let l = lanes.findIndex((f) => f <= x.ini); if (l < 0) { l = lanes.length; lanes.push(0); } lanes[l] = x.ini + x.dur; x._lane = l; });
  return lanes.length;
}

function colunaDia(dia, grupos, hIni, hFim) {
  let doDia = grupos.filter((x) => x.data === dia && x.ini != null);
  // 1) mesma casa no mesmo horário = um bloco só
  const mesmoHorario = {};
  doDia.forEach((x) => (mesmoHorario[`${x.casa}|${x.hora}`] = mesmoHorario[`${x.casa}|${x.hora}`] || []).push(x));
  doDia = Object.values(mesmoHorario).map((gs) => (gs.length === 1 ? gs[0] : multiGrupo(gs, reunioes(gs.length))));
  doDia.sort((a, b) => a.ini - b.ini || b.dur - a.dur);
  // 2) blocos que se sobrepõem dividem a largura (como no Google Agenda), no máximo 4 lado a lado
  const html = [];
  let cluster = [], fimCluster = -1;
  const fecha = () => {
    if (!cluster.length) return;
    if (lanesDe(cluster) > MAX_LANES) {  // ainda apertado: junta por casa dentro do trecho
      const porCasa = {};
      cluster.forEach((x) => (porCasa[x.casa] = porCasa[x.casa] || []).push(x));
      cluster = Object.values(porCasa).map((gs) => (gs.length === 1 ? gs[0] : multiGrupo(gs, reunioes(gs.reduce((s, y) => s + (y.filhos || [y]).length, 0))))).sort((a, b) => a.ini - b.ini);
    }
    if (lanesDe(cluster) > MAX_LANES) {  // último recurso: "+N" com o resto
      const fica = cluster.filter((x) => x._lane < MAX_LANES - 1), resto = cluster.filter((x) => x._lane >= MAX_LANES - 1);
      cluster = fica.concat(multiGrupo(resto, `+${resto.length} ${resto.length === 1 ? "bloco" : "blocos"}`)).sort((a, b) => a.ini - b.ini);
    }
    const n = lanesDe(cluster);
    cluster.forEach((x) => html.push(blocoAgenda(x, x._lane, n, hIni)));
    cluster = [];
  };
  doDia.forEach((x) => { if (x.ini >= fimCluster) { fecha(); fimCluster = -1; } cluster.push(x); fimCluster = Math.max(fimCluster, x.ini + x.dur); });
  fecha();
  const agora = new Date(), hoje = isoLocal(agora), m = agora.getHours() * 60 + agora.getMinutes();
  const linha = dia === hoje && m >= hIni * 60 && m <= hFim * 60 ? `<div class="cal-agora" style="top:${((m - hIni * 60) / 60) * CAL_H}px"></div>` : "";
  return `<div class="cal-col ${dia === hoje ? "hoje" : ""} ${[0, 6].includes(dt(dia).getDay()) ? "fds" : ""}" style="height:${(hFim - hIni) * CAL_H}px">${html.join("")}${linha}</div>`;
}

function renderCalendario(itens) {
  const g = agruparAgenda(itens), grupos = Object.values(g);
  cal.grupos = g;
  const hoje = isoLocal(new Date());
  if (!cal.semana) {  // abre na semana do próximo compromisso (no sábado/domingo, já cai na semana seguinte)
    const prox = grupos.map((x) => x.data).filter((d) => d >= hoje).sort()[0];
    cal.semana = segundaDe(prox || hoje);
  }
  let dias = [0, 1, 2, 3, 4, 5, 6].map((n) => somaDias(cal.semana, n));
  // fim de semana só aparece se tiver algo
  dias = dias.filter((d) => ![0, 6].includes(dt(d).getDay()) || grupos.some((x) => x.data === d));
  const ini = dt(dias[0]), fim = dt(dias[dias.length - 1]);
  $("#cal-titulo").textContent = ini.getMonth() === fim.getMonth()
    ? `${ini.getDate()} – ${fim.getDate()} de ${MESES[fim.getMonth()]}. de ${fim.getFullYear()}`
    : `${ini.getDate()} de ${MESES[ini.getMonth()]}. – ${fim.getDate()} de ${MESES[fim.getMonth()]}. de ${fim.getFullYear()}`;
  // celular: um dia por vez
  if (estreito()) {
    if (!cal.diaMob || !dias.includes(cal.diaMob))
      cal.diaMob = dias.find((d) => d >= hoje && grupos.some((x) => x.data === d)) || (dias.includes(hoje) ? hoje : dias[0]);
    $("#cal-dias-mob").innerHTML = dias.map((d) => { const n = grupos.filter((x) => x.data === d).length;
      return `<button class="cal-dmob ${d === cal.diaMob ? "on" : ""} ${d === hoje ? "hoje" : ""}" data-diamob="${d}"><span>${SEM[dt(d).getDay()]}</span><b>${dt(d).getDate()}</b>${n ? `<i>${n}</i>` : ""}</button>`; }).join("");
    dias = [cal.diaMob];
  } else $("#cal-dias-mob").innerHTML = "";
  const doPeriodo = grupos.filter((x) => dias.includes(x.data) && x.ini != null);
  let hIni = 8, hFim = 20;
  doPeriodo.forEach((x) => { hIni = Math.min(hIni, Math.floor(x.ini / 60)); hFim = Math.max(hFim, Math.ceil((x.ini + x.dur) / 60)); });
  hFim = Math.min(24, hFim);
  const semHora = (d) => grupos.filter((x) => x.data === d && x.ini == null);
  const temDiaInteiro = dias.some((d) => semHora(d).length);
  const col = `56px repeat(${dias.length}, minmax(0, 1fr))`;
  const vazioSemana = !grupos.some((x) => dias.includes(x.data));
  $("#cal").innerHTML = `
    <div class="cal-cab" style="grid-template-columns:${col}"><div></div>${dias.map((d) => `<div class="cal-cab-dia ${d === hoje ? "hoje" : ""}"><span>${SEM[dt(d).getDay()]}</span><b>${dt(d).getDate()}</b></div>`).join("")}</div>
    ${temDiaInteiro ? `<div class="cal-inteiro" style="grid-template-columns:${col}"><div class="cal-hr-rot">dia todo</div>${dias.map((d) => `<div>${semHora(d).map((x) => `<button class="cal-chip" data-grupo="${esc(x.k)}" style="--c:${CAL_COR[x.casa]}">${esc(x.casa)} · ${esc(x.titulo)}</button>`).join("")}</div>`).join("")}</div>` : ""}
    <div class="cal-corpo" style="grid-template-columns:${col}">
      <div class="cal-horas">${Array.from({ length: hFim - hIni }, (_, k) => `<div style="height:${CAL_H}px"><span>${pad2(hIni + k)}h</span></div>`).join("")}</div>
      ${dias.map((d) => colunaDia(d, grupos, hIni, hFim)).join("")}
    </div>
    ${vazioSemana ? `<div class="cal-vazio">Nada da agenda filtrada nesta ${estreito() ? "data" : "semana"}. O radar olha os próximos 8 dias.</div>` : ""}`;
}

function abrirGrupo(k) {
  const x = cal.grupos[k]; if (!x) return;
  const d = dt(x.data);
  $("#cal-gaveta-conteudo").innerHTML = `
    <div class="cal-g-cab" style="--c:${CAL_COR[x.casa]}">
      <div class="cal-g-casa"><i class="ti ${AG_CASAS[x.casa] || "ti-building"}"></i> ${esc(x.casa)}${x.plenario ? " · Plenário" : ""}</div>
      <h3>${esc(x.titulo)}</h3>
      <div class="cal-g-quando"><i class="ti ti-clock"></i> ${SEM[d.getDay()]} ${fmtData(x.data)}${x.hora ? ` · ${esc(x.hora)}` : ""}${x.sub && !x.filhos ? ` · ${esc(x.sub)}` : ""}</div>
      ${x.link && !x.filhos ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">página oficial do evento <i class="ti ti-external-link"></i></a>` : ""}
    </div>
    <div class="cal-g-itens">${x.filhos
      ? x.filhos.slice().sort((a, b) => a.ini - b.ini || b.altas - a.altas).map((f) => `
        <div class="cal-g-sub" style="--c:${CAL_COR[f.casa]}"><b>${esc(f.hora || "")} · ${esc(f.casa)} · ${esc(f.titulo)}</b>${f.sub ? `<span>${esc(f.sub)}</span>` : ""}
          ${f.link ? `<a href="${esc(f.link)}" target="_blank" rel="noopener">evento <i class="ti ti-external-link"></i></a>` : ""}</div>
        ${f.itens.map(cardAgenda).join("")}`).join("")
      : x.itens.map(cardAgenda).join("")}</div>`;
  $("#cal-gaveta").hidden = false;
  $("#cal-gaveta .cal-gaveta-caixa").scrollTop = 0;
}
function fecharGaveta() { $("#cal-gaveta").hidden = true; }

function renderAgenda() {
  if (!ag.r) { carregarAgenda(); return; }
  const r = ag.r, d = r.dados;
  $("#ag-dia").innerHTML = (r.dias || []).map((x) => `<option value="${x}" ${x === r.dia ? "selected" : ""}>boletim de ${SEM[dt(x).getDay()]} ${fmtData(x)}</option>`).join("");
  if (!d) { $("#cal").innerHTML = '<p class="vazio">Nenhum boletim ainda. Clique em "Checar agora".</p>'; $("#ag-resumo").innerHTML = ""; return; }
  $("#cal-atual").textContent = `checado ${haQuanto(d.gerado)}`;
  $("#ag-resumo").innerHTML = d.resumo.map((l) => `<li>${esc(l)}</li>`).join("");
  $("#ag-alertas").innerHTML = (d.alertas || []).length ? `<div class="ag-caixa-alerta"><b><i class="ti ti-alarm"></i> Alertas</b>${d.alertas.map((a) => `<div>${esc(a.titulo)} ${a.link ? `<a href="${esc(a.link)}" target="_blank" rel="noopener">fonte</a>` : ""}</div>`).join("")}</div>` : "";
  $("#ag-avisos").innerHTML = (d.avisos || []).map((a) => `<div class="ag-aviso"><i class="ti ti-info-circle"></i> ${esc(a)}</div>`).join("");
  const todos = d.itens || [];
  const conta = (f) => todos.reduce((m, i) => { [].concat(f(i)).forEach((k) => (m[k] = (m[k] || 0) + 1)); return m; }, {});
  const cc = conta((i) => i.casa), cp = conta((i) => i.pautas), cr = conta((i) => i.prioridade);
  $("#ag-casa").innerHTML = Object.keys(AG_CASAS).filter((k) => cc[k]).map((k) => `<span class="chip ${ag.casa.has(k) ? "on" : ""}" data-agcasa="${k}"><i class="ti ${AG_CASAS[k]}"></i>${k}<span class="n">${cc[k]}</span></span>`).join("")
    + `<span class="chip ${ag.soNovos ? "on" : ""}" data-agnovos="1">🆕 só novos e mudanças</span>`;
  $("#ag-pauta").innerHTML = Object.keys(cp).sort((a, b) => (a === "Outras") - (b === "Outras") || cp[b] - cp[a]).map((k) => `<span class="chip ${ag.pauta.has(k) ? "on" : ""}" data-agpauta="${esc(k)}">${esc(k)}<span class="n">${cp[k]}</span></span>`).join("");
  $("#ag-prio").innerHTML = ["Alta", "Média", "Baixa"].filter((k) => cr[k]).map((k) => `<span class="chip ${ag.prio.has(k) ? "on" : ""}" data-agprio="${k}"><span class="pon" style="background:${AG_PRIO[k]}"></span>${k}<span class="n">${cr[k]}</span></span>`).join("");
  renderCalendario(agFiltrados());
  $("#ag-fontes").innerHTML = (d.fontes || []).map((f) => `<div>${f.ok ? "✅" : "❌"} <b>${esc(f.nome)}</b>: ${f.ok ? `${f.itens} itens lidos` : `falhou (${esc(f.erro)})`} · <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.url)}</a></div>`).join("");
}

// ---------- exportar hot points para o WhatsApp ----------
const ex = { itens: [], marcados: new Set() };
const bolaCalor = (c) => (c >= 0.7 ? "🔴" : c >= 0.55 ? "🟠" : c >= 0.4 ? "🟡" : "🔵");

const paraExportar = (it) => ({ id: "radar:" + it._id, calor: null, lugar: (it.local || {}).nome || null, titulo: it.titulo, fonte: it.veiculo,
  link: (it.links || [])[0], extra: 0, quente: true, tom: it.checar_tom, urgencia: it.urgencia, angulo: it.angulo });

async function abrirExportar(soItem) {
  if (soItem && soItem.titulo) { ex.itens = [paraExportar(soItem)]; ex.marcados = new Set([ex.itens[0].id]); return mostrarExportar(); }
  const dados = await api("/api/hotmap?dias=5");  // sempre a janela padrão, independente do filtro do mapa
  const limiar = dados.limiar || 0.7;
  const itens = (dados.pontos || []).filter((p) => p.calor >= 0.4).map((p) => {
    const x = p.pautas[0];
    return { id: "mapa:" + p.lugar, calor: p.calor, lugar: p.lugar, titulo: x.titulo, fonte: x.fonte, link: x.link, extra: p.n - 1, quente: p.calor >= limiar };
  });
  // itens de alta urgência do radar do dia que não têm lugar no mapa (ex.: prazos, cobranças gerais)
  const noMapa = new Set((dados.pontos || []).flatMap((p) => p.pautas.map((x) => x.titulo)));
  itensDoDia().filter((it) => it.urgencia === "Alta" && !noMapa.has(it.titulo)).forEach((it) => itens.push({ ...paraExportar(it), lugar: null }));
  ex.itens = itens.slice(0, 15);
  ex.marcados = new Set(ex.itens.filter((i) => i.quente).map((i) => i.id));
  mostrarExportar();
}

function mostrarExportar() {
  $("#exp-lista").innerHTML = ex.itens.length ? ex.itens.map((i) => `<label class="exp-item">
      <input type="checkbox" data-exp="${esc(i.id)}" ${ex.marcados.has(i.id) ? "checked" : ""}>
      <span class="exp-temp" style="background:${i.calor == null ? "var(--marinho)" : corCalor(i.calor)}">${i.calor == null ? esc(i.urgencia || "Alta") : Math.round(i.calor * 100) + "°"}</span>
      <span><b>${esc(i.lugar || "Sem lugar no mapa")}</b><br><small>${esc(i.titulo)} · ${esc(i.fonte || "")}</small></span></label>`).join("")
    : '<p class="vazio">Nenhuma pauta morna ou quente nos últimos 5 dias.</p>';
  $("#exp-ok").textContent = "";
  montarMensagem();
  $("#modal-exportar").hidden = false;
}

function montarMensagem() {
  const links = $("#exp-links").checked;
  const sel = ex.itens.filter((i) => ex.marcados.has(i.id));
  const h = dt(st.hoje || new Date().toISOString().slice(0, 10));
  const um = ex.itens.length === 1;
  // modelo combinado com o Daniel (05/11): lugar + temperatura, ASSUNTO, ângulo, LINK, pergunta de posicionamento
  const linhas = [um ? `*📌 D.News · Pauta encaminhada (${SEM[h.getDay()]} ${fmtData(st.hoje)})*` : `*🔥 D.News · Hot points de ${SEM[h.getDay()]} ${fmtData(st.hoje)}*`, ""];
  sel.forEach((i, k) => {
    const u = i.urgencia || "Alta";
    const temp = i.calor == null ? `${u === "Alta" ? "🔴" : u === "Média" ? "🟠" : "🟡"} ${u.toLowerCase()} urgência` : `${bolaCalor(i.calor)} ${Math.round(i.calor * 100)}°`;
    linhas.push(`*${k + 1}. ${i.lugar || "Pauta do radar"}* · ${temp}`, "");
    linhas.push(`ASSUNTO: ${i.titulo}`);
    if (sel.length === 1 && i.angulo) linhas.push(`Ângulo sugerido: ${i.angulo}`);
    linhas.push("");
    if (links && i.link) linhas.push(`LINK: ${i.link}`, "");
  });
  if (!sel.length) linhas.push("(marque ao menos uma pauta)", "");
  linhas.push(sel.length > 1 ? "👉 Acham que alguma vale um posicionamento para as redes da Dayse? Respondam com o número da pauta."
    : "👉 Acham que vale um posicionamento para as redes da Dayse?");
  const texto = linhas.join("\n");
  $("#exp-texto").value = texto;
  atualizarLinkWpp();
}
function atualizarLinkWpp() { $("#exp-wpp").href = "https://api.whatsapp.com/send?text=" + encodeURIComponent($("#exp-texto").value); }

async function copiarMensagem() {
  const t = $("#exp-texto");
  try { await navigator.clipboard.writeText(t.value); } catch { t.select(); document.execCommand("copy"); }
  $("#exp-ok").textContent = "Copiado! É só colar no grupo.";
}

function contadores() {
  const quentes = ((hm.dados || {}).pontos || []).filter((p) => p.calor >= ((hm.dados || {}).limiar || 0.7)).length;
  $("#n-hot").textContent = quentes || "";
  $("#n-radar").textContent = abertos(itensDoDia()).length || "";
  $("#n-noticias").textContent = noticias().length || "";
  $("#n-videos").textContent = videos().length || "";
  $("#n-prazos").textContent = eventosComData().filter((e) => { const d = diasAte(e.data); return d >= 0 && d <= 7; }).length || "";
  const c = (st.feeds || {}).coleta || {};
  $("#coleta-info").textContent = c.rodando ? "coletando…" : (st.feeds && st.feeds.atualizado ? `notícias ${haQuanto(st.feeds.atualizado)}` : "");
  $("#btn-coletar").classList.toggle("girando", !!c.rodando);
  if (c.rodando && !st.esperandoColeta) {  // coleta em andamento: recarrega quando terminar
    st.esperandoColeta = setInterval(async () => {
      const f = await api(`/api/feeds/${st.hoje}`);
      if (!f.coleta.rodando) { clearInterval(st.esperandoColeta); st.esperandoColeta = null; await carregarDias(); await carregarDia(); }
    }, 4000);
  }
}

function renderTudo() {
  contadores(); renderGeral();
  ({ hotmap: renderHotmap, trilhas: renderTrilhas, agenda: renderAgenda, radar: renderRadar, noticias: renderNoticias, videos: renderVideos, prazos: renderPrazos, redes: renderRedes, relatorios: renderRelatorio }[st.aba] || (() => {}))();
}

// ---------- carga ----------
async function carregarDias() {
  const r = await api("/api/dias");
  // quem estava olhando "hoje" acompanha a virada do dia (e o radar novo que chega)
  const seguiaHoje = !st.dia || st.dia === st.hoje || st.dia === (st.dias[0] || {}).data;
  st.dias = r.dias; st.hoje = r.hoje;
  if (seguiaHoje) st.dia = (st.dias[0] || {}).data || null;
  $("#sel-dia").innerHTML = st.dias.map((d) => {
    const ex = d.itens ? ` · ${d.itens} no radar${d.alta ? `, ${d.alta} alta` : ""}` : d.tem.feeds ? " · só notícias" : "";
    return `<option value="${d.data}">${SEM[dt(d.data).getDay()]} ${fmtData(d.data)}${d.data === st.hoje ? " (hoje)" : ""}${ex}</option>`;
  }).join("");
  // abre sempre no dia mais recente (o #data do endereço deixava a aba presa num dia antigo)
  if (!st.dia || !st.dias.some((d) => d.data === st.dia)) st.dia = (st.dias[0] || {}).data || null;
  $("#sel-dia").value = st.dia || "";
}
async function carregarDia() {
  const av = $("#aviso");
  if (!st.dia) { av.className = "alert alert-info"; av.textContent = "Nenhum relatório ainda. A coleta de notícias roda ao abrir o painel e o radar às 7h."; return; }
  av.className = "alert d-none";
  history.replaceState(null, "", "#" + st.dia);
  [st.dados, st.estado, st.feeds] = await Promise.all([api(`/api/dia/${st.dia}`), api("/api/estado"), api(`/api/feeds/${st.dia}`)]);
  if (st.f.escopo === "todos") st.todos = await api("/api/itens");
  renderTudo();
  carregarMidias(itensDoDia());
  carregarHotmap();
  carregarTrilhas();
  carregarAgenda();
}

// ---------- eventos ----------
function irPara(aba) {
  st.aba = aba;
  document.querySelectorAll("#abas a").forEach((a) => a.classList.toggle("on", a.dataset.aba === aba));
  document.querySelectorAll("[data-painel]").forEach((p) => (p.hidden = p.dataset.painel !== aba));
  renderTudo(); window.scrollTo({ top: 0, behavior: "smooth" });
}
function mudarDia(delta) { const i = st.dias.findIndex((d) => d.data === st.dia), novo = st.dias[i - delta]; if (novo) { st.dia = novo.data; $("#sel-dia").value = st.dia; carregarDia(); } }
function abrirVideo(id, titulo) {
  $("#modal-player").innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
  $("#modal-titulo").textContent = titulo || ""; $("#modal-video").hidden = false;
}
function fecharVideo() { $("#modal-player").innerHTML = ""; $("#modal-video").hidden = true; }

function ligar() {
  $("#sel-dia").onchange = (e) => { st.dia = e.target.value; carregarDia(); };
  $("#dia-ant").onclick = () => mudarDia(-1);
  $("#dia-prox").onclick = () => mudarDia(1);
  $("#btn-hoje").onclick = () => { if (st.dias.some((d) => d.data === st.hoje)) { st.dia = st.hoje; $("#sel-dia").value = st.dia; carregarDia(); } };
  $("#abas").onclick = (e) => { const a = e.target.closest("[data-aba]"); if (a) irPara(a.dataset.aba); };
  $("#sub-abas").onclick = (e) => { const a = e.target.closest("[data-rel]"); if (a) { st.rel = a.dataset.rel; renderRelatorio(); } };
  $("#f-busca").oninput = (e) => { st.f.busca = e.target.value; renderRadar(); };
  $("#f-status").onchange = (e) => { st.f.status = e.target.value; renderRadar(); };
  $("#f-escopo").onchange = async (e) => { st.f.escopo = e.target.value; if (st.f.escopo === "todos") { st.todos = await api("/api/itens"); carregarMidias(st.todos); } renderRadar(); };
  $("#n-busca").oninput = (e) => { st.n.busca = e.target.value; renderNoticias(); };
  $("#n-ordem").onchange = (e) => { st.n.ordem = e.target.value; renderNoticias(); };
  $("#btn-coletar").onclick = async () => {
    $("#btn-coletar").classList.add("girando"); $("#coleta-info").textContent = "coletando…";
    await api("/api/coletar", { method: "POST" });
    setTimeout(carregarDia, 800);  // o contador vê "rodando" e acompanha até terminar
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { fecharVideo(); fecharGaveta(); $("#modal-pauta").hidden = true; $("#modal-exportar").hidden = true; $("#painel-alertas").hidden = true; } });
  document.addEventListener("pointerdown", liberarSom, { capture: true });
  $("#btn-sino").classList.add("mudo");
  $("#btn-sino").onclick = (e) => { e.stopPropagation(); const p = $("#painel-alertas"); if (p.hidden) renderPainelAlertas(); else p.hidden = true; };
  $("#fa-visto").onclick = async () => { await api("/api/alertas/visto", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); checarAlertas(); };
  $("#fa-mapa").onclick = () => irPara("hotmap");
  $("#hm-dias").onclick = (e) => {
    const a = e.target.closest("[data-d]"); if (!a) return;
    hm.dias = +a.dataset.d; document.querySelectorAll("#hm-dias a").forEach((x) => x.classList.toggle("on", x === a)); carregarHotmap();
  };
  $("#hm-novo").onclick = abrirFormPauta;
  $("#ag-dia").onchange = (e) => carregarAgenda(e.target.value);
  $("#ag-checar").onclick = async () => {
    $("#ag-checar").classList.add("girando");
    await api("/api/agenda/coletar", { method: "POST" });
    const t = setInterval(async () => { const r = await api("/api/agenda"); if (!(r.coleta || {}).rodando) { clearInterval(t); await carregarAgenda(); checarAlertas(); } }, 5000);
  };
  $("#cal-hoje").onclick = () => { cal.semana = null; cal.diaMob = null; renderAgenda(); };
  $("#cal-ant").onclick = () => { cal.semana = somaDias(cal.semana, -7); cal.diaMob = null; renderAgenda(); };
  $("#cal-prox").onclick = () => { cal.semana = somaDias(cal.semana, 7); cal.diaMob = null; renderAgenda(); };
  $("#cal-gaveta").addEventListener("click", (e) => { if (e.target.closest("[data-fechar-gaveta]")) fecharGaveta(); });
  let largAnt = estreito();
  window.addEventListener("resize", () => { if (st.aba === "agenda" && estreito() !== largAnt) { largAnt = estreito(); renderAgenda(); } });
  // sem isso o navegador foca o bloco no mousedown, rola a página e o clique "escapa" do bloco
  $("[data-painel=agenda]").addEventListener("mousedown", (e) => { if (e.target.closest("[data-grupo]")) e.preventDefault(); });
  $("[data-painel=agenda]").addEventListener("click", (e) => {
    const gr = e.target.closest("[data-grupo]"); if (gr) { abrirGrupo(gr.dataset.grupo); return; }
    const dm = e.target.closest("[data-diamob]"); if (dm) { cal.diaMob = dm.dataset.diamob; renderAgenda(); return; }
    const c = e.target.closest("[data-agcasa],[data-agpauta],[data-agprio],[data-agnovos]"); if (!c) return;
    const alterna = (s, v) => (s.has(v) ? s.delete(v) : s.add(v));
    if (c.dataset.agcasa) alterna(ag.casa, c.dataset.agcasa);
    else if (c.dataset.agpauta) alterna(ag.pauta, c.dataset.agpauta);
    else if (c.dataset.agprio) alterna(ag.prio, c.dataset.agprio);
    else ag.soNovos = !ag.soNovos;
    renderAgenda();
  });
  $("#btn-exportar").onclick = () => abrirExportar();
  $("#hm-exportar").onclick = () => abrirExportar();
  $("#exp-lista").onchange = (e) => { const c = e.target.closest("[data-exp]"); if (!c) return; c.checked ? ex.marcados.add(c.dataset.exp) : ex.marcados.delete(c.dataset.exp); montarMensagem(); };
  $("#exp-links").onchange = montarMensagem;
  $("#exp-texto").oninput = atualizarLinkWpp;
  $("#exp-copiar").onclick = copiarMensagem;
  $("#int-range").oninput = (e) => { $("#int-rot").textContent = `${e.target.value} · ${["", "frio", "morno-frio", "morno", "quente", "pegando fogo"][e.target.value]}`; };
  $("#form-pauta").onsubmit = async (e) => {
    e.preventDefault();
    const dados = Object.fromEntries(new FormData(e.target).entries());
    const r = await fetch("/api/hotmap/manual", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dados) });
    const j = await r.json();
    if (!r.ok) { $("#form-erro").textContent = j.erro || "Não deu para salvar."; return; }
    $("#modal-pauta").hidden = true;
    await carregarHotmap();
    const m = hm.marcadores[j.local]; if (m) { hm.mapa.setView(m.getLatLng(), 13); m.openPopup(); }
  };
  document.addEventListener("click", async (e) => {
    const t = e.target;
    const play = t.closest("[data-video]");
    if (play) { e.preventDefault(); e.stopPropagation(); abrirVideo(play.dataset.video, play.dataset.vtitulo); return; }
    if (t.closest("[data-fechar]")) { fecharVideo(); return; }
    if (t.closest("[data-fechar-pauta]")) { $("#modal-pauta").hidden = true; return; }
    if (t.closest("[data-fechar-exportar]")) { $("#modal-exportar").hidden = true; return; }
    if (t.closest("#pa-teste")) { await api("/api/alertas/teste", { method: "POST" }); await checarAlertas(); renderPainelAlertas(); return; }
    if (!t.closest("#painel-alertas") && !$("#painel-alertas").hidden) $("#painel-alertas").hidden = true;
    const trl = t.closest("[data-trilha]");
    if (trl) {
      await abrirTrilha(trl.dataset.trilha);
      if (window.innerWidth <= 1100) $("#tr-detalhe").scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const hmo = t.closest("[data-hmorigem]");
    if (hmo) { const v = hmo.dataset.hmorigem; hm.origem.has(v) ? hm.origem.delete(v) : hm.origem.add(v); renderHotmap(); return; }
    const hml = t.closest("[data-hmlugar]");
    if (hml) { const m = hm.marcadores[hml.dataset.hmlugar]; if (m) { hm.mapa.setView(m.getLatLng(), 13); m.openPopup(); } return; }
    const ap = t.closest("[data-apagar-pauta]");
    if (ap) { if (confirm("Tirar esta pauta do mapa?")) { await api("/api/hotmap/apagar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: ap.dataset.apagarPauta }) }); hm.mapa.closePopup(); carregarHotmap(); } return; }
    const chip = t.closest(".chip[data-urg], .chip[data-tipo], .chip[data-pilar], .chip[data-npilar]");
    if (chip) {
      const [conj, v, fn] = chip.dataset.urg ? [st.f.urg, chip.dataset.urg, renderRadar] : chip.dataset.tipo ? [st.f.tipo, chip.dataset.tipo, renderRadar]
        : chip.dataset.pilar ? [st.f.pilar, chip.dataset.pilar, renderRadar] : [st.n.pilar, chip.dataset.npilar, renderNoticias];
      conj.has(v) ? conj.delete(v) : conj.add(v); fn(); return;
    }
    const b = t.closest("[data-status]");
    if (b) {
      st.estado = await api("/api/estado", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: b.dataset.id, status: b.dataset.status }) }); renderTudo();
      if (b.dataset.status === "encaminhado") abrirExportar(itensDoDia().concat(st.todos || []).find((i) => i._id === b.dataset.id));  // encaminhar = já abre a mensagem
      return;
    }
    const c = t.closest("[data-copiar]");
    if (c) { try { await navigator.clipboard.writeText(c.dataset.copiar); c.innerHTML = '<i class="ti ti-check"></i>'; setTimeout(() => (c.innerHTML = '<i class="ti ti-copy"></i>'), 1200); } catch (err) {} return; }
    const ir = t.closest("[data-ir]");
    if (ir) irPara(ir.dataset.ir);
  });
  let tema = null; try { tema = localStorage.getItem("tema"); } catch (e) {}
  if (tema) document.documentElement.dataset.bsTheme = tema;
  $("#btn-tema").onclick = () => { const n = document.documentElement.dataset.bsTheme === "dark" ? "light" : "dark"; document.documentElement.dataset.bsTheme = n; try { localStorage.setItem("tema", n); } catch (e) {} };
}

async function iniciar() {
  ligar();
  try { await carregarDias(); await carregarDia(); }
  catch (e) { const a = $("#aviso"); a.className = "alert alert-danger"; a.textContent = "Erro ao falar com o servidor local: " + e.message; }
  setInterval(async () => { await carregarDias(); await carregarDia(); }, 5 * 60 * 1000);
  checarAlertas();
  setInterval(checarAlertas, 60 * 1000);  // alarme toca em até 1 min depois que a varredura acha pauta quente
}
iniciar();
