// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: red; icon-glyph: film;

// ============================================================
//  Widget « Prochains événements culturels » (Scriptable)
//  Lit data/events.json hébergé sur GitHub Pages.
//
//  Paramètre du widget (facultatif) : filtre séparé par des virgules
//  sur le lieu, la ville ou la catégorie. Exemples :
//    La Scala            -> uniquement La Scala
//    Metz                -> uniquement les événements à Metz
//    concert,spectacle   -> uniquement ces catégories
//    (vide)              -> tout afficher
//
//  Un tap sur le widget ouvre dans Scriptable la liste complète des
//  événements à venir : défilement, filtres (lieu, catégorie, période)
//  et recherche. Lancé depuis l'app (bouton lecture), le script ouvre
//  aussi cette liste. Aperçu du widget depuis l'app : ajouter à l'URL
//  de lancement ?apercu=small|medium|large (utile pour tester).
// ============================================================

// >>> À MODIFIER : URL de ton fichier JSON publié par GitHub Pages
const JSON_URL = "https://Deynis.github.io/event_handler/data/events.json";

// Mise à jour automatique : le script se remplace par la version publiée sur GitHub Pages.
const SCRIPT_URL = "https://Deynis.github.io/event_handler/widget/EventsWidget.js";
const UPDATE_HOURS = 24;      // au plus une vérification par jour
const UPDATE_STAMP = "events-widget-update.txt";

const REFRESH_MINUTES = 15;   // iOS reste libre de rafraîchir plus tard
const GRACE_MINUTES = 10;     // une séance commencée depuis < 10 min reste affichée
const CACHE_FILE = "events-cache.json";
const PREFS_FILE = "events-prefs.json";   // films masqués et favoris (sur l'iPhone)

const CATEGORY_COLORS = {
  cinema: "#E5484D",
  concert: "#3E63DD",
  spectacle: "#8E4EC6",
  expo: "#30A46C",
  festival: "#F76B15",
};
const DEFAULT_COLOR = "#8B8D98";

const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

// Nombre de lignes disponibles (en-têtes de jour inclus) selon la taille
const LINE_BUDGET = { small: 6, medium: 6, large: 15 };

// ---------- Utilitaires ----------

function norm(s) {
  return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

function pad(n) {
  return n < 10 ? "0" + n : String(n);
}

function fmtTime(d) {
  return pad(d.getHours()) + "h" + pad(d.getMinutes());
}

function dayKey(d) {
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
}

function dayLabel(d, now) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((target - today) / 86400000);
  if (diff === 0) return "Aujourd'hui";
  if (diff === 1) return "Demain";
  return JOURS[d.getDay()] + " " + d.getDate() + " " + MOIS[d.getMonth()];
}

function colorFor(cat) {
  return new Color(CATEGORY_COLORS[cat] || DEFAULT_COLOR);
}

// ---------- Données (réseau + cache local) ----------

async function loadData() {
  const fm = FileManager.local();
  const path = fm.joinPath(fm.documentsDirectory(), CACHE_FILE);
  try {
    const req = new Request(JSON_URL + "?t=" + Date.now());
    req.timeoutInterval = 10;
    const data = await req.loadJSON();
    if (!data || !Array.isArray(data.events)) throw new Error("Format JSON inattendu");
    fm.writeString(path, JSON.stringify(data));
    return { data: data, offline: false };
  } catch (e) {
    if (fm.fileExists(path)) {
      try {
        return { data: JSON.parse(fm.readString(path)), offline: true };
      } catch (e2) { /* cache illisible */ }
    }
    return { data: null, offline: true };
  }
}

// ---------- Masqués et favoris ----------

// Un choix vaut pour toutes les séances d'un même titre dans un même lieu (le film entier).
function eventKey(e) {
  return norm(e.lieu) + "|" + norm(e.titre);
}

function prefsPath() {
  const fm = FileManager.local();
  return fm.joinPath(fm.documentsDirectory(), PREFS_FILE);
}

function loadPrefs() {
  try {
    const fm = FileManager.local();
    if (fm.fileExists(prefsPath())) {
      const p = JSON.parse(fm.readString(prefsPath()));
      return { hidden: p.hidden || {}, favorites: p.favorites || {} };
    }
  } catch (e) { /* fichier illisible : on repart de zéro */ }
  return { hidden: {}, favorites: {} };
}

function savePrefs(prefs) {
  FileManager.local().writeString(prefsPath(), JSON.stringify(prefs));
}

// ---------- Sélection et regroupement ----------

// Filtre : termes séparés par des virgules. « favoris » garde les favoris ; sinon un terme
// vaut pour la ville, la catégorie, ou le nom du lieu (complet ou mots entiers).
// Les films masqués sont écartés, sauf si includeHidden.
function selectEvents(data, filterParam, now, prefs, includeHidden) {
  prefs = prefs || { hidden: {}, favorites: {} };
  const filters = String(filterParam || "").split(",").map(norm).filter(Boolean);
  const minStart = now.getTime() - GRACE_MINUTES * 60000;
  return data.events
    .map(function (e) {
      const start = new Date(e.debut);
      // Fin : celle du JSON si elle existe, sinon fin de journée pour un événement
      // « jour entier », sinon le début lui-même.
      let end = e.fin ? new Date(e.fin) : start;
      if (e.jour_entier && !e.fin) end = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 23, 59, 59);
      return Object.assign({}, e, { _d: start, _end: end });
    })
    .filter(function (e) {
      if (isNaN(e._d.getTime())) return false;
      // Période ou jour entier : visible jusqu'à sa fin. Séance : jusqu'à 10 min après le début.
      return (e.jour_entier || e.fin) ? e._end.getTime() >= now.getTime() : e._d.getTime() >= minStart;
    })
    .filter(function (e) {
      return includeHidden || !prefs.hidden[eventKey(e)];
    })
    .filter(function (e) {
      if (filters.length === 0) return true;
      // Lieu : nom complet ou mots entiers du nom (« Philharmonie » -> « Philharmonie Luxembourg »).
      const lieu = " " + norm(e.lieu) + " ";
      return filters.some(function (f) {
        if (f === "favoris") return !!prefs.favorites[eventKey(e)];
        return lieu.indexOf(" " + f + " ") >= 0 || norm(e.ville) === f || norm(e.categorie) === f;
      });
    })
    .sort(function (a, b) { return a._d - b._d; });
}

// Texte à droite de la ligne : heure, « -> 15 nov. » pour une période, « journée » sinon.
function timeLabel(e) {
  if (!e.jour_entier) return fmtTime(e._d);
  if (dayKey(e._end) !== dayKey(e._d)) return "→ " + e._end.getDate() + " " + MOIS[e._end.getMonth()];
  return "journée";
}

// Regroupe par jour puis par (lieu + titre) : un film = une ligne avec toutes ses heures.
// Une période déjà commencée (ex. une exposition) est affichée sous « Aujourd'hui ».
function groupByDay(events, now) {
  const days = [];
  const dayIndex = {};
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  events.forEach(function (e) {
    const shownDate = (e.jour_entier && e._d < startOfToday) ? now : e._d;
    const k = dayKey(shownDate);
    if (!(k in dayIndex)) {
      dayIndex[k] = days.length;
      days.push({ date: shownDate, groups: [], index: {} });
    }
    const day = days[dayIndex[k]];
    const gk = e.lieu + "|" + e.titre;
    if (!(gk in day.index)) {
      day.index[gk] = day.groups.length;
      day.groups.push({ event: e, times: [] });
    }
    day.groups[day.index[gk]].times.push(timeLabel(e));
  });
  return days;
}

// ---------- Construction du widget ----------

function addRow(w, group, family, showLieu, prefs) {
  const e = group.event;
  const row = w.addStack();
  row.centerAlignContent();
  row.spacing = 5;

  const color = colorFor(e.categorie);
  const titre = (prefs.favorites[eventKey(e)] ? "★ " : "") + e.titre;

  if (family === "small") {
    // Petit format : première heure + titre
    const t = row.addText(group.times[0]);
    t.font = Font.boldSystemFont(11);
    t.textColor = color;
    const title = row.addText(titre);
    title.font = Font.systemFont(11);
    title.lineLimit = 1;
    title.minimumScaleFactor = 0.8;
  } else {
    const title = row.addText(titre);
    title.font = Font.systemFont(12);
    title.lineLimit = 1;
    if (showLieu) {
      const lieu = row.addText(e.lieu);
      lieu.font = Font.systemFont(9);
      lieu.textColor = Color.gray();
      lieu.lineLimit = 1;
    }
    row.addSpacer();
    const times = row.addText(group.times.join(" "));
    times.font = Font.boldSystemFont(11);
    times.textColor = color;
    times.lineLimit = 1;
  }
}

function buildWidget(result, filterParam, family) {
  const w = new ListWidget();
  const now = new Date();
  w.backgroundColor = Color.dynamic(new Color("#FFFFFF"), new Color("#1C1C1E"));
  w.setPadding(10, 12, 10, 12);
  w.refreshAfterDate = new Date(now.getTime() + REFRESH_MINUTES * 60000);
  // Un tap sur le widget ouvre la liste complète (scrollable, filtrable) dans Scriptable.
  w.url = listUrl(filterParam);

  if (!result.data) {
    const t = w.addText("Données indisponibles");
    t.font = Font.boldSystemFont(13);
    const s = w.addText("Pas de connexion et aucun cache local.");
    s.font = Font.systemFont(11);
    s.textColor = Color.gray();
    return w;
  }

  const prefs = loadPrefs();
  const events = selectEvents(result.data, filterParam, now, prefs);
  const days = groupByDay(events, now);

  if (days.length === 0) {
    const t = w.addText("Aucun événement à venir");
    t.font = Font.boldSystemFont(13);
    if (filterParam) {
      const s = w.addText("Filtre : " + filterParam);
      s.font = Font.systemFont(11);
      s.textColor = Color.gray();
    }
  } else {
    const lieux = {};
    events.forEach(function (e) { lieux[e.lieu] = true; });
    const showLieu = Object.keys(lieux).length > 1 && family !== "small";

    let budget = LINE_BUDGET[family] || LINE_BUDGET.medium;
    let first = true;
    for (let i = 0; i < days.length; i++) {
      const day = days[i];
      if (budget < 2) break; // pas la place pour un en-tête + une ligne
      if (!first) w.addSpacer(3);
      first = false;

      const h = w.addText(dayLabel(day.date, now).toUpperCase());
      h.font = Font.semiboldSystemFont(9);
      h.textColor = Color.gray();
      budget -= 1;

      for (let j = 0; j < day.groups.length && budget > 0; j++) {
        addRow(w, day.groups[j], family, showLieu, prefs);
        budget -= 1;
      }
    }
  }

  w.addSpacer();

  // Pied de page : état de la connexion / date de mise à jour
  if (family !== "small" || result.offline) {
    let label = "";
    if (result.offline) {
      label = "Hors ligne";
      if (result.data.updated_at) label += " - données du " + fmtDateTime(new Date(result.data.updated_at));
    } else if (result.data.updated_at) {
      label = "Mis à jour " + fmtDateTime(new Date(result.data.updated_at));
    }
    if (label) {
      const f = w.addText(label);
      f.font = Font.systemFont(8);
      f.textColor = result.offline ? new Color("#F76B15") : Color.gray();
      f.lineLimit = 1;
    }
  }
  return w;
}

function fmtDateTime(d) {
  if (isNaN(d.getTime())) return "?";
  return d.getDate() + " " + MOIS[d.getMonth()] + " " + fmtTime(d);
}

// ---------- Liste complète (ouverte par un tap sur le widget) ----------

function listUrl(filterParam) {
  return "scriptable:///run?scriptName=" + encodeURIComponent(Script.name()) +
    "&filtre=" + encodeURIComponent(filterParam || "");
}

const CATEGORY_LABELS = { cinema: "Cinéma", concert: "Concert", spectacle: "Spectacle", expo: "Exposition", festival: "Festival" };

// La liste est une page web (WebView) : c'est le seul moyen de gérer les swipes.
// Swipe à gauche : masquer le film ; à droite : favori ★. La page envoie chaque geste
// au script (navigation widget:// interceptée par shouldAllowRequest), qui l'enregistre.

function listItems(data, prefs, now) {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return selectEvents(data, "", now, prefs, true).map(function (e) {
    const shown = (e.jour_entier && e._d < startOfToday) ? now : e._d;
    return {
      key: eventKey(e),
      titre: e.titre,
      lieu: e.lieu,
      ville: e.ville,
      cat: e.categorie,
      color: CATEGORY_COLORS[e.categorie] || DEFAULT_COLOR,
      sub: [e.lieu, e.version, e.note].filter(Boolean).join(" · "),
      url: e.url || "",
      day: dayKey(shown),
      dayLabel: dayLabel(shown, now).toUpperCase(),
      time: timeLabel(e),
      start: e._d.getTime(),
    };
  });
}

function listHtml(result, prefs, initialFilter) {
  const now = new Date();
  const stamp = result.data.updated_at ? fmtDateTime(new Date(result.data.updated_at)) : "?";
  const payload = {
    items: listItems(result.data, prefs, now),
    prefs: prefs,
    filter: initialFilter || "",
    catLabels: CATEGORY_LABELS,
    todayStart: new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime(),
    foot: (result.offline ? "Hors ligne - données du " : "Mis à jour ") + stamp,
    offline: result.offline,
  };
  // « < » échappé : un titre contenant </script> ne peut pas casser la page.
  const json = JSON.stringify(payload).replace(/</g, "\\u003c");
  return LIST_PAGE.replace("__DATA__", function () { return json; });
}

const LIST_PAGE = `<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root { --bg:#F2F2F7; --card:#FFFFFF; --text:#000000; --muted:#8E8E93; --sep:#E5E5EA; --hide:#E5484D; --fav:#F5A623; }
@media (prefers-color-scheme: dark) { :root { --bg:#000000; --card:#1C1C1E; --text:#FFFFFF; --sep:#38383A; } }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { margin:0; background:var(--bg); color:var(--text); font:15px -apple-system, system-ui, sans-serif; padding-bottom:calc(80px + env(safe-area-inset-bottom)); }
header { position:sticky; top:0; z-index:2; background:var(--bg); padding:calc(10px + env(safe-area-inset-top)) 12px 8px; border-bottom:1px solid var(--sep); }
.controls { display:flex; gap:8px; margin-bottom:8px; }
select, input { font:inherit; color:var(--text); background:var(--card); border:1px solid var(--sep); border-radius:10px; padding:8px 10px; min-width:0; flex:1; -webkit-appearance:none; appearance:none; }
input { width:100%; }
.hint { font-size:11px; color:var(--muted); margin-top:6px; text-align:center; }
h2 { font-size:12px; font-weight:600; color:var(--muted); margin:18px 16px 6px; letter-spacing:.03em; }
.row { position:relative; overflow:hidden; border-bottom:1px solid var(--sep); }
.row.gone { transition:max-height .25s, opacity .25s; max-height:0 !important; opacity:0; }
.bg { position:absolute; inset:0; display:flex; align-items:center; padding:0 20px; font-weight:600; color:#FFFFFF; }
.content { position:relative; background:var(--card); display:flex; align-items:center; gap:10px; padding:10px 16px; min-height:58px; transition:transform .2s; }
.content.dragging { transition:none; }
.text { flex:1; min-width:0; }
.title, .sub { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sub { font-size:12px; color:var(--muted); margin-top:2px; }
.times { font-weight:700; font-size:13px; text-align:right; max-width:42%; }
.star { color:var(--fav); }
.empty, .foot { color:var(--muted); text-align:center; padding:32px 16px; }
.foot { font-size:11px; padding:16px; }
.foot.offline { color:#F76B15; }
.toast { position:fixed; left:12px; right:12px; bottom:calc(16px + env(safe-area-inset-bottom)); background:#333333; color:#FFFFFF; border-radius:12px; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; gap:12px; transform:translateY(200%); transition:transform .25s; z-index:5; }
.toast.show { transform:none; }
.toast span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.toast button { background:none; border:0; color:#FFD60A; font:inherit; font-weight:600; padding:0; }
</style></head><body>
<header>
  <div class="controls"><select id="filter"></select>
    <select id="period"><option value="0">Toutes dates</option><option value="1">Aujourd'hui</option><option value="7">7 jours</option></select></div>
  <input id="q" type="search" placeholder="Rechercher (titre, lieu, note...)">
  <div class="hint" id="hint"></div>
</header>
<main id="list"></main>
<div class="foot" id="foot"></div>
<div class="toast" id="toast"><span id="toastText"></span><button id="undo">Annuler</button></div>
<script>
var DATA = __DATA__;
var items = DATA.items, prefs = DATA.prefs;
var THRESHOLD = 80;

// Messages vers Scriptable : une navigation vers widget://msg?d=... que le script
// intercepte (shouldAllowRequest) et annule. Espacées pour qu'aucune n'en annule une autre.
var queue = [], flushing = false;
function send(msg) {
  queue.push("widget://msg?d=" + encodeURIComponent(JSON.stringify(msg)));
  if (!flushing) flush();
}
function flush() {
  if (!queue.length) { flushing = false; return; }
  flushing = true;
  location.href = queue.shift();
  setTimeout(flush, 80);
}

function norm(s) { return String(s || "").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase().trim(); }
function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

var sel = document.getElementById("filter"), per = document.getElementById("period"), qi = document.getElementById("q");

function matches(it, filter) {
  if (filter === "__hidden") return !!prefs.hidden[it.key];
  if (prefs.hidden[it.key]) return false;
  var terms = filter.split(",").map(norm).filter(Boolean);
  if (!terms.length) return true;
  var lieu = " " + norm(it.lieu) + " ";
  return terms.some(function (f) {
    if (f === "favoris") return !!prefs.favorites[it.key];
    return lieu.indexOf(" " + f + " ") >= 0 || norm(it.ville) === f || norm(it.cat) === f;
  });
}

function buildFilter() {
  var current = sel.options.length ? sel.value : DATA.filter;
  var lieux = [], cats = [], hiddenKeys = {};
  items.forEach(function (it) {
    if (lieux.indexOf(it.lieu) < 0) lieux.push(it.lieu);
    if (cats.indexOf(it.cat) < 0) cats.push(it.cat);
    if (prefs.hidden[it.key]) hiddenKeys[it.key] = true;
  });
  var opts = [["", "Tous les lieux"], ["favoris", "★ Favoris"]]
    .concat(lieux.map(function (l) { return [l, l]; }))
    .concat(cats.map(function (c) { return [c, DATA.catLabels[c] || c]; }))
    .concat([["__hidden", "Masqués (" + Object.keys(hiddenKeys).length + ")"]]);
  // Le filtre du widget (« Kinepolis », « concert,spectacle »...) reste toujours proposé.
  [DATA.filter, current].forEach(function (f) {
    if (f && !opts.some(function (o) { return o[0] === f; })) opts.splice(1, 0, [f, f]);
  });
  sel.textContent = "";
  opts.forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; sel.appendChild(op); });
  sel.value = current;
}

function render() {
  buildFilter();
  var filter = sel.value, period = Number(per.value), q = norm(qi.value);
  var limit = period ? DATA.todayStart + period * 86400000 : Infinity;
  var hiddenView = filter === "__hidden";
  document.getElementById("hint").textContent = hiddenView
    ? "Glisser un film pour le réafficher" : "← glisser pour masquer · glisser pour ★ favori →";

  // Regroupement par jour puis par film (un film = une ligne avec toutes ses heures).
  var days = [], dayIndex = {};
  items.forEach(function (it) {
    if (!matches(it, filter) || it.start >= limit) return;
    if (q && norm(it.titre + " " + it.sub).indexOf(q) < 0) return;
    if (!(it.day in dayIndex)) { dayIndex[it.day] = days.length; days.push({ label: it.dayLabel, groups: [], index: {} }); }
    var day = days[dayIndex[it.day]];
    if (!(it.key in day.index)) { day.index[it.key] = day.groups.length; day.groups.push({ it: it, times: [] }); }
    day.groups[day.index[it.key]].times.push(it.time);
  });

  var list = document.getElementById("list");
  list.textContent = "";
  if (!days.length) list.appendChild(el("div", "empty", hiddenView ? "Aucun film masqué." : "Aucun événement ne correspond."));
  days.forEach(function (day) {
    list.appendChild(el("h2", null, day.label));
    day.groups.forEach(function (g) { list.appendChild(makeRow(g, hiddenView)); });
  });
}

function makeRow(g, hiddenView) {
  var it = g.it;
  var row = el("div", "row"), bg = el("div", "bg"), content = el("div", "content");
  var text = el("div", "text"), title = el("div", "title");
  if (prefs.favorites[it.key]) title.appendChild(el("span", "star", "★ "));
  title.appendChild(document.createTextNode(it.titre));
  text.appendChild(title);
  text.appendChild(el("div", "sub", it.sub));
  var times = el("div", "times", g.times.join("  "));
  times.style.color = it.color;
  content.appendChild(text);
  content.appendChild(times);
  row.appendChild(bg);
  row.appendChild(content);

  var x0 = 0, y0 = 0, dx = 0, mode = null;
  function paint() {
    var fav = !!prefs.favorites[it.key];
    if (hiddenView) { bg.style.background = "#30A46C"; bg.textContent = "Réafficher"; }
    else if (dx > 0) { bg.style.background = "var(--fav)"; bg.textContent = fav ? "☆ Retirer des favoris" : "★ Favori"; }
    else { bg.style.background = "var(--hide)"; bg.textContent = "Masquer"; }
    bg.style.justifyContent = dx > 0 ? "flex-start" : "flex-end";
    bg.style.opacity = Math.min(1, Math.abs(dx) / THRESHOLD);
  }
  function snap() { content.style.transform = ""; }
  function collapse(then) {
    row.style.maxHeight = row.offsetHeight + "px";
    content.style.transform = "translateX(" + (dx > 0 ? "" : "-") + "100%)";
    void row.offsetHeight;
    row.classList.add("gone");
    setTimeout(then, 260);
  }

  content.addEventListener("touchstart", function (e) {
    var t = e.touches[0]; x0 = t.clientX; y0 = t.clientY; dx = 0; mode = null;
  }, { passive: true });
  content.addEventListener("touchmove", function (e) {
    var t = e.touches[0], mx = t.clientX - x0, my = t.clientY - y0;
    if (!mode) {
      if (Math.abs(mx) > 10 && Math.abs(mx) > Math.abs(my)) mode = "h";
      else if (Math.abs(my) > 10) mode = "v";
    }
    if (mode !== "h") return;
    e.preventDefault();
    dx = mx;
    content.classList.add("dragging");
    content.style.transform = "translateX(" + dx + "px)";
    paint();
  }, { passive: false });
  content.addEventListener("touchend", function () {
    content.classList.remove("dragging");
    if (mode !== "h") return;
    mode = "done";
    if (Math.abs(dx) < THRESHOLD) { snap(); return; }
    if (hiddenView) {
      delete prefs.hidden[it.key]; send({ type: "unhide", key: it.key });
      collapse(render);
      toast("« " + it.titre + " » réaffiché", function () { prefs.hidden[it.key] = true; send({ type: "hide", key: it.key }); render(); });
    } else if (dx < 0) {
      prefs.hidden[it.key] = true; send({ type: "hide", key: it.key });
      collapse(render);
      toast("« " + it.titre + " » masqué", function () { delete prefs.hidden[it.key]; send({ type: "unhide", key: it.key }); render(); });
    } else {
      var fav = !prefs.favorites[it.key];
      if (fav) prefs.favorites[it.key] = true; else delete prefs.favorites[it.key];
      send({ type: fav ? "fav" : "unfav", key: it.key });
      snap();
      setTimeout(render, 220);
    }
  });
  content.addEventListener("click", function () {
    if (mode === "done") { mode = null; return; } // fin d'un swipe, pas un tap
    if (it.url) send({ type: "open", url: it.url });
  });
  return row;
}

var toastTimer = null, undoAction = null;
function toast(text, undo) {
  document.getElementById("toastText").textContent = text;
  undoAction = undo;
  document.getElementById("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { document.getElementById("toast").classList.remove("show"); undoAction = null; }, 4000);
}
document.getElementById("undo").addEventListener("click", function () {
  document.getElementById("toast").classList.remove("show");
  if (undoAction) { var u = undoAction; undoAction = null; u(); }
});

var foot = document.getElementById("foot");
foot.textContent = DATA.foot;
if (DATA.offline) foot.classList.add("offline");
sel.addEventListener("change", render);
per.addEventListener("change", render);
qi.addEventListener("input", render);
render();
</script></body></html>`;

function handleListMessage(msg, prefs) {
  if (msg.type === "open") { Safari.openInApp(msg.url, false); return; }
  if (msg.type === "hide") prefs.hidden[msg.key] = true;
  else if (msg.type === "unhide") delete prefs.hidden[msg.key];
  else if (msg.type === "fav") prefs.favorites[msg.key] = true;
  else if (msg.type === "unfav") delete prefs.favorites[msg.key];
  else return;
  savePrefs(prefs);
}

async function showList(initialFilter) {
  const result = await loadData();
  if (!result.data) {
    const a = new Alert();
    a.title = "Données indisponibles";
    a.message = "Pas de connexion et aucun cache local.";
    a.addAction("OK");
    await a.presentAlert();
    return;
  }
  const prefs = loadPrefs();
  const wv = new WebView();
  // Ne jamais laisser un evaluateJavaScript en attente : il bloque l'affichage de la page.
  wv.shouldAllowRequest = function (req) {
    const url = String(req.url || "");
    if (url.indexOf("widget://msg") !== 0) return true;
    try {
      const d = url.match(/[?&]d=([^&]*)/);
      if (d) handleListMessage(JSON.parse(decodeURIComponent(d[1])), prefs);
    } catch (e) { /* message illisible : ignoré */ }
    return false;
  };
  await wv.loadHTML(listHtml(result, prefs, initialFilter));
  await wv.present(true);
}

// ---------- Mise à jour du script ----------

// Télécharge la version publiée et réécrit ce fichier si elle a changé : la nouvelle
// version s'applique au lancement suivant. Au moindre doute (réseau, réponse
// inattendue), on ne touche à rien.
async function selfUpdate() {
  try {
    const local = FileManager.local();
    const stamp = local.joinPath(local.documentsDirectory(), UPDATE_STAMP);
    if (local.fileExists(stamp) && Date.now() - Number(local.readString(stamp)) < UPDATE_HOURS * 3600000) return;

    const req = new Request(SCRIPT_URL + "?t=" + Date.now());
    req.timeoutInterval = 10;
    const code = await req.loadString();
    if (req.response.statusCode !== 200) return;
    if (code.indexOf("Widget « Prochains événements culturels »") < 0 || code.indexOf("Script.complete()") < 0) return;
    local.writeString(stamp, String(Date.now()));

    // Le script vit dans iCloud Drive/Scriptable si iCloud est activé, sinon en local.
    let fm = local;
    try {
      const icloud = FileManager.iCloud();
      if (module.filename.indexOf(icloud.documentsDirectory()) === 0) fm = icloud;
    } catch (e) { /* iCloud désactivé */ }
    if (fm.readString(module.filename) !== code) fm.writeString(module.filename, code);
  } catch (e) { /* on réessaiera au prochain lancement */ }
}

// ---------- Point d'entrée ----------

const param = args.widgetParameter || "";
const query = args.queryParameters || {};

if (config.runsInWidget) {
  const family = config.widgetFamily || "medium";
  const widget = buildWidget(await loadData(), param, family === "extraLarge" ? "large" : family);
  Script.setWidget(widget);
} else if (query.apercu) {
  // Aperçu du widget depuis l'app : ?apercu=small|medium|large
  const widget = buildWidget(await loadData(), query.filtre || "", query.apercu);
  if (query.apercu === "small") await widget.presentSmall();
  else if (query.apercu === "large") await widget.presentLarge();
  else await widget.presentMedium();
} else {
  // Tap sur le widget, ou bouton lecture dans Scriptable : liste complète
  await showList(query.filtre || "");
}
await selfUpdate();
Script.complete();
