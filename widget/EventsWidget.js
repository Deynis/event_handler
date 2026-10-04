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
// ============================================================

// >>> À MODIFIER : URL de ton fichier JSON publié par GitHub Pages
const JSON_URL = "https://Deynis.github.io/event_handler/data/events.json";

const REFRESH_MINUTES = 15;   // iOS reste libre de rafraîchir plus tard
const GRACE_MINUTES = 10;     // une séance commencée depuis < 10 min reste affichée
const CACHE_FILE = "events-cache.json";

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

// ---------- Sélection et regroupement ----------

function selectEvents(data, filterParam, now) {
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
      if (filters.length === 0) return true;
      return filters.some(function (f) {
        return norm(e.lieu) === f || norm(e.ville) === f || norm(e.categorie) === f;
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

function addRow(w, group, family, showLieu) {
  const e = group.event;
  const row = w.addStack();
  row.centerAlignContent();
  row.spacing = 5;

  const color = colorFor(e.categorie);

  if (family === "small") {
    // Petit format : première heure + titre
    const t = row.addText(group.times[0]);
    t.font = Font.boldSystemFont(11);
    t.textColor = color;
    const title = row.addText(e.titre);
    title.font = Font.systemFont(11);
    title.lineLimit = 1;
    title.minimumScaleFactor = 0.8;
  } else {
    const title = row.addText(e.titre);
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

  if (!result.data) {
    const t = w.addText("Données indisponibles");
    t.font = Font.boldSystemFont(13);
    const s = w.addText("Pas de connexion et aucun cache local.");
    s.font = Font.systemFont(11);
    s.textColor = Color.gray();
    return w;
  }

  const events = selectEvents(result.data, filterParam, now);
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
        addRow(w, day.groups[j], family, showLieu);
        budget -= 1;
      }
    }
    if (events[0].url) w.url = events[0].url;
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

// ---------- Point d'entrée ----------

const family = config.widgetFamily || "medium";   // en app : aperçu moyen
const param = args.widgetParameter || "";
const result = await loadData();
const widget = buildWidget(result, param, family === "extraLarge" ? "large" : family);

if (config.runsInWidget) {
  Script.setWidget(widget);
} else if (family === "small") {
  await widget.presentSmall();
} else if (family === "large") {
  await widget.presentLarge();
} else {
  await widget.presentMedium();
}
Script.complete();
