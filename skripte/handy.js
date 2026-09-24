/* ============================================================================
   WoazeWeather -- Handy-Ansicht
   Wird von skripte/bauen.py NUR in docs/handy-app.html eingebaut, nie in die
   normale Seite (docs/app.html). Zwei Aufgaben:

   1. Zoom mit zwei Fingern (Pinch) in den Diagrammen.
      - Station heute / Station Verlauf: die Zeitachse wird gezoomt. Die Achsen
        beschriften sich neu, die Hoehenachse passt sich dem sichtbaren Ausschnitt
        an. Ein Finger zieht den Ausschnitt, Doppeltippen oder der Knopf
        "Ganzer Zeitraum" setzt zurueck. Dazu ruft die Seite window.WW_ZOOM.anwenden
        auf (die Verbindung setzt bauen.py in diagramm() ein).
      - Alle anderen Diagramme (48 Std., Vorhersage, Analyse): das Diagramm wird
        beim Pinch breiter und laesst sich im Rahmen seitlich wischen.
   2. Den kleinen Dienst (handy-sw.js) anmelden, damit Chrome "App installieren"
      anbietet.
   ============================================================================ */
(() => {
"use strict";

const HOEHE_PLUS = 30;                 // Station-Diagramme sind in der App etwas hoeher
const PLOT_L = 44, PLOT_R = 12;        // Raender in diagramm() (Wetterstation-Block der Vorlage)
const ZOOM_MAX_FAKTOR = 40;            // staerkstes Zoomen: ein Vierzigstel des Zeitraums
const $ = (s, w = document) => w.querySelector(s);

/* ---------- Ortszeit (Europe/Berlin) ---------- */
const teileFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", year: "numeric", month: "2-digit",
  day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short" });
const WT = { Mon: "Mo", Tue: "Di", Wed: "Mi", Thu: "Do", Fri: "Fr", Sat: "Sa", Sun: "So" };
const MON_K = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
function ort(ts) {
  const p = {}; for (const x of teileFmt.formatToParts(new Date(ts * 1000))) p[x.type] = x.value;
  return { j: +p.year, m: +p.month, t: +p.day, h: +p.hour, min: +p.minute, wt: WT[p.weekday] };
}
// Ortszeit minus UTC in Sekunden (auf die Minute genau)
const versatz = ts => { const o = ort(ts); return Date.UTC(o.j, o.m - 1, o.t, o.h, o.min) / 1000 - Math.floor(ts / 60) * 60; };
const zwei = n => String(n).padStart(2, "0");
// Unixzeit von 00:00 Ortszeit des Kalendertags j-m-t (m, t duerfen ueberlaufen)
function ortsMitternacht(j, m, t) {
  const utc = Date.UTC(j, m - 1, t) / 1000;
  let ts = utc - 3600;
  for (let i = 0; i < 3; i++) { const o = ort(ts); ts -= (Date.UTC(o.j, o.m - 1, o.t, o.h, o.min) / 1000 - utc); }
  return ts;
}

/* ---------- Beschriftung der Zeitachse im gezoomten Zustand ---------- */
const STD = 3600, TAG = 86400;
function ticksFuer(x0, x1) {
  const spanne = x1 - x0;
  const langeText = spanne > 30 * STD;               // "Mo 14:00" braucht mehr Platz als "14:00"
  const ziel = langeText ? 5 : 7;
  const rand = spanne * 0.03;
  const beschriften = ts => {
    const o = ort(ts);
    // Mitternacht mitten im Bild zeigt den Tag; am Rand bleibt es bei der Uhrzeit
    if (o.h === 0 && o.min === 0 && ts - x0 > rand && x1 - ts > rand) return `${o.wt} ${o.t}.${o.m}.`;
    return `${zwei(o.h)}:${zwei(o.min)}`;
  };
  for (const s of [5 * 60, 10 * 60, 15 * 60, 30 * 60, STD, 2 * STD, 3 * STD, 6 * STD, 12 * STD]) {
    if (spanne / s > ziel) continue;
    const t = [];
    const v0 = versatz(x0);
    for (let w = Math.ceil((x0 + v0) / s) * s; ; w += s) {   // Schritte in Ortszeit zaehlen
      const naeherung = w - v0;
      const ts = w - versatz(naeherung);
      if (ts > x1) break;
      if (ts >= x0) t.push([ts, beschriften(ts)]);
    }
    return t;
  }
  const o0 = ort(x0);
  if (spanne <= 70 * TAG) {                              // Tage
    const regeln = { 1: () => true, 2: d => d % 2 === 1, 5: d => [1, 5, 10, 15, 20, 25].includes(d), 10: d => [1, 10, 20].includes(d) };
    for (const s of [1, 2, 5, 10]) {
      const t = [];
      for (let i = 0; i <= Math.ceil(spanne / TAG) + 1; i++) {
        const ts = ortsMitternacht(o0.j, o0.m, o0.t + i);
        if (ts < x0 || ts > x1) continue;
        const o = ort(ts);
        if (regeln[s](o.t)) t.push([ts, s === 1 || s === 2 ? `${o.wt} ${o.t}.${o.m}.` : `${o.t}.${o.m}.`]);
      }
      if (t.length <= ziel) return t;
    }
  }
  for (const s of [1, 2, 3, 6]) {                        // Monate
    const t = [];
    for (let i = 0; i <= 13; i++) {
      const ts = ortsMitternacht(o0.j, o0.m + i, 1);
      if (ts < x0 || ts > x1) continue;
      const o = ort(ts);
      if ((o.m - 1) % s === 0) t.push([ts, MON_K[o.m - 1]]);
    }
    if (t.length <= ziel) return t;
  }
  return [];
}

/* ---------- Daten auf einen Zeitausschnitt zuschneiden ---------- */
const mischen = (p, n, ts, felder) => {                  // linear zwischen zwei Punkten
  const f = (ts - p.ts) / (n.ts - p.ts), r = { ts };
  for (const k of felder) r[k] = p[k] + (n[k] - p[k]) * f;
  return r;
};
function reiheKuerzen(punkte, a, b, luecke, felder) {
  const p = punkte.filter(q => felder.every(k => q[k] != null)).sort((m, n) => m.ts - n.ts);
  const aus = [];
  for (let i = 0; i < p.length; i++) {
    const q = p[i], n = p[i + 1];
    if (q.ts >= a && q.ts <= b) aus.push(q);
    if (n && n.ts - q.ts <= luecke) {                    // Strecke zwischen q und n: am Rand sauber abschneiden
      if (q.ts < a && n.ts > a) aus.push(mischen(q, n, a, felder));
      if (q.ts < b && n.ts > b) aus.push(mischen(q, n, b, felder));
    }
  }
  return aus.sort((m, n) => m.ts - n.ts);
}
const balkenKuerzen = (liste, a, b) => liste
  .filter(k => k.bis > a && k.von < b)
  .map(k => ({ ...k, von: Math.max(k.von, a), bis: Math.min(k.bis, b) }));

function ausschnitt(o, z) {
  const { a, b } = z;
  const linien = (o.linien || []).map(l => ({ ...l, punkte: reiheKuerzen(l.punkte, a, b, l.lueckeS || o.lueckeS || 0, ["v"]) }));
  const band = o.band ? reiheKuerzen(o.band, a, b, o.lueckeS || 0, ["min", "max"]) : o.band;
  const balken = o.balken ? balkenKuerzen(o.balken, a, b) : o.balken;
  const marken = o.marken ? balkenKuerzen(o.marken, a, b) : o.marken;
  const ys = [];
  for (const l of linien) for (const p of l.punkte) ys.push(p.v);
  for (const k of balken || []) ys.push(k.v);
  for (const k of marken || []) ys.push(k.v);
  for (const p of band || []) ys.push(p.min, p.max);
  const yWerte = ys.some(v => v != null && isFinite(v)) ? ys : o.yWerte;   // ohne Daten im Ausschnitt: Skala behalten
  return { ...o, x0: a, x1: b, xTicks: ticksFuer(a, b), linien, band, balken, marken, yWerte,
    tooltips: (o.tooltips || []).filter(t => t.ts >= a && t.ts <= b) };
}

/* ---------- Zoom-Zustand der Wetterstation-Diagramme ---------- */
// Je Reiter (heute, verlauf) ein Ausschnitt; beide Diagramme des Reiters teilen ihn.
const zoom = { heute: null, verlauf: null };
const gruppeVon = ziel => /Heute/.test(ziel) ? "heute" : /Verlauf/.test(ziel) ? "verlauf" : null;
const gezoomt = z => !!z && (z.a > z.b0 || z.b < z.b1);
const minSpanne = z => (z.b1 - z.b0) / ZOOM_MAX_FAKTOR;

function knopfAktualisieren(g) {
  const k = $(`#seite-station-${g} .ww-zurueck`);
  if (k) k.hidden = !gezoomt(zoom[g]);
  if (gezoomt(zoom[g])) { try { localStorage.setItem("ww-zoom-benutzt", "1"); } catch (e) { /* egal */ } hinweisAus(); }
}
function hinweisAus() { document.querySelectorAll(".ww-hinweis").forEach(h => { h.hidden = true; }); }

// Zu viele oder zu lange Beschriftungen ueberlappen sich auf dem schmalen Bildschirm:
// dann bleibt nur jede zweite (dritte ...) stehen, die Gitterlinie aber bleibt.
function verduennen(ticks, iw) {
  if (!ticks || !ticks.length) return ticks;
  const zeichen = Math.max(...ticks.map(t => String(t[1]).length));
  const k = Math.max(1, Math.ceil((zeichen * 7 + 10) * ticks.length / iw));
  return k === 1 ? ticks : ticks.map((t, i) => i % k === 0 ? t : [t[0], ""]);
}

window.WW_ZOOM = {
  /** Wird von diagramm() der Vorlage vor dem Zeichnen aufgerufen. */
  anwenden(ziel, o) {
    o = { ...o, hoehe: (o.hoehe || 220) + HOEHE_PLUS };
    const g = gruppeVon(ziel);
    if (!g) return o;
    let z = zoom[g];
    if (!z || z.b0 !== o.x0 || z.b1 !== o.x1) z = zoom[g] = { b0: o.x0, b1: o.x1, a: o.x0, b: o.x1 };   // neuer Zeitraum: Zoom weg
    knopfAktualisieren(g);
    const r = gezoomt(z) ? ausschnitt(o, z) : o;
    const box = $(ziel), iw = Math.max(320, Math.round((box ? box.clientWidth : 390) - 20)) - PLOT_L - PLOT_R;
    return { ...r, xTicks: verduennen(r.xTicks, iw) };
  },
};

let neuGeplant = false;
function neuZeichnen() {
  if (neuGeplant) return;
  neuGeplant = true;
  requestAnimationFrame(() => { neuGeplant = false; if (window.WW_NEU) window.WW_NEU(); });
}
function fensterSetzen(g, a, b) {
  const z = zoom[g]; if (!z) return;
  const span = Math.min(z.b1 - z.b0, Math.max(minSpanne(z), b - a));
  const na = Math.max(z.b0, Math.min(a, z.b1 - span));
  z.a = na; z.b = na + span;
  neuZeichnen();
}
function zoomZuruecksetzen(g) {
  const z = zoom[g]; if (!z) return;
  z.a = z.b0; z.b = z.b1;
  neuZeichnen();
}

/* ---------- Gesten auf den Station-Diagrammen ---------- */
function stationGesten(box, g) {
  const zeiger = new Map();
  let pinch = null, ziehen = null, letzterTipp = null;
  const geometrie = () => {
    const svg = box.querySelector("svg"); if (!svg) return null;
    const r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
    if (!vb || !vb.width) return null;
    const f = r.width / vb.width;
    return { links: r.left + PLOT_L * f, breite: (vb.width - PLOT_L - PLOT_R) * f };
  };
  const tipVerstecken = () => { const t = $("#tip"); if (t) t.style.opacity = "0"; };
  const halten = id => { try { box.setPointerCapture(id); } catch (e) { /* Zeiger schon weg */ } };

  box.addEventListener("pointerdown", e => {
    if (e.pointerType === "mouse") return;
    zeiger.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: e.timeStamp });
    const z = zoom[g], geo = geometrie();
    if (zeiger.size === 2 && z && geo) {
      const [p, q] = [...zeiger.values()];
      const mitte = (p.x + q.x) / 2;
      pinch = { d0: Math.max(10, Math.hypot(p.x - q.x, p.y - q.y)), a0: z.a, b0: z.b,
                tF: z.a + (mitte - geo.links) / geo.breite * (z.b - z.a), geo };
      ziehen = null;
      for (const id of zeiger.keys()) halten(id);
      tipVerstecken();
    }
  });
  box.addEventListener("pointermove", e => {
    const p = zeiger.get(e.pointerId); if (!p) return;
    p.x = e.clientX; p.y = e.clientY;
    const z = zoom[g];
    if (pinch && zeiger.size >= 2 && z) {
      const [m, n] = [...zeiger.values()];
      const d = Math.max(10, Math.hypot(m.x - n.x, m.y - n.y));
      const spanne = (pinch.b0 - pinch.a0) * pinch.d0 / d;                  // Finger auseinander: kleinerer Ausschnitt
      const mitte = (m.x + n.x) / 2;
      const anteil = (mitte - pinch.geo.links) / pinch.geo.breite;
      fensterSetzen(g, pinch.tF - anteil * spanne, pinch.tF - anteil * spanne + spanne);
      e.preventDefault();
      return;
    }
    if (zeiger.size === 1 && gezoomt(z)) {
      const dx = p.x - p.x0, dy = p.y - p.y0;
      if (!ziehen && Math.abs(dx) > 8 && Math.abs(dx) > 1.3 * Math.abs(dy)) {   // waagrechtes Ziehen: Ausschnitt schieben
        const geo = geometrie();
        if (geo) { ziehen = { a0: z.a, b0: z.b, geo, x0: p.x }; halten(e.pointerId); tipVerstecken(); }
      }
      if (ziehen) {
        const dt = -(p.x - ziehen.x0) / ziehen.geo.breite * (ziehen.b0 - ziehen.a0);
        fensterSetzen(g, ziehen.a0 + dt, ziehen.b0 + dt);
        e.preventDefault();
      }
    }
  });
  const ende = e => {
    const p = zeiger.get(e.pointerId);
    zeiger.delete(e.pointerId);
    const warPinch = !!pinch;
    if (zeiger.size < 2) pinch = null;
    if (zeiger.size === 0) ziehen = null;
    // Bleibt nach dem Pinch ein Finger liegen, zaehlt seine Bewegung erst ab jetzt
    if (warPinch && !pinch) for (const q of zeiger.values()) { q.x0 = q.x; q.y0 = q.y; q.t0 = -1e9; }
    if (!p || e.type === "pointercancel" || warPinch) return;
    // Doppeltippen (zwei kurze Tipps am selben Fleck) setzt den Zeitraum zurueck
    const kurz = e.timeStamp - p.t0 < 300 && Math.hypot(p.x - p.x0, p.y - p.y0) < 10;
    if (!kurz) return;
    if (letzterTipp && e.timeStamp - letzterTipp.t < 350 && Math.hypot(p.x - letzterTipp.x, p.y - letzterTipp.y) < 40) {
      letzterTipp = null;
      if (gezoomt(zoom[g])) zoomZuruecksetzen(g);
    } else letzterTipp = { t: e.timeStamp, x: p.x, y: p.y };
  };
  box.addEventListener("pointerup", ende);
  box.addEventListener("pointercancel", ende);
  // Zwei Finger duerfen die Seite nicht verschieben oder ziehen: nur das Diagramm reagiert.
  box.addEventListener("touchmove", e => { if (e.touches.length >= 2 && e.cancelable) e.preventDefault(); }, { passive: false });
}

/* ---------- Andere Diagramme: beim Pinch breiter werden ---------- */
function wachsenGesten(box) {
  const ZMAX = 4;
  const zeiger = new Map();
  let faktor = 1, basis = 0, pinch = null, letzterTipp = null;
  const svgHolen = () => box.querySelector("svg");
  const anwenden = () => {
    const s = svgHolen(); if (!s) return;
    if (!basis) basis = s.getBoundingClientRect().width;
    const breite = Math.round(basis * faktor) + "px";
    if (faktor === 1) { s.style.removeProperty("width"); s.style.removeProperty("min-width"); }
    else { s.style.width = breite; s.style.minWidth = breite; }
  };
  const zuruecksetzen = () => { faktor = 1; anwenden(); basis = 0; box.scrollLeft = 0; };
  // Wird das Diagramm neu gezeichnet (anderes Modell, Drehen des Handys), faengt der Zoom von vorn an.
  const neu = () => {
    if (faktor === 1) { basis = 0; return; }
    faktor = 1; anwenden(); basis = 0;
  };
  new MutationObserver(neu).observe(box, { childList: true });
  const s0 = svgHolen();
  if (s0) new MutationObserver(neu).observe(s0, { attributes: true, attributeFilter: ["viewBox"] });
  let letzteBreite = innerWidth;
  addEventListener("resize", () => { if (innerWidth !== letzteBreite) { letzteBreite = innerWidth; neu(); } });

  box.addEventListener("pointerdown", e => {
    if (e.pointerType === "mouse") return;
    zeiger.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: e.timeStamp });
    if (zeiger.size === 2) {
      const s = svgHolen(); if (!s) return;
      if (!basis) basis = s.getBoundingClientRect().width / faktor;
      const [p, q] = [...zeiger.values()], r = s.getBoundingClientRect();
      const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
      pinch = { d0: Math.max(10, Math.hypot(p.x - q.x, p.y - q.y)), k0: faktor,
                fx: (mx - r.left) / r.width, fy: (my - r.top) / r.height };
      for (const id of zeiger.keys()) { try { box.setPointerCapture(id); } catch (err) { /* egal */ } }
      const t = $("#tip"); if (t) t.style.opacity = "0";
    }
  });
  box.addEventListener("pointermove", e => {
    const p = zeiger.get(e.pointerId); if (!p) return;
    p.x = e.clientX; p.y = e.clientY;
    if (!pinch || zeiger.size < 2) return;
    const [m, n] = [...zeiger.values()];
    faktor = Math.max(1, Math.min(ZMAX, pinch.k0 * Math.hypot(m.x - n.x, m.y - n.y) / pinch.d0));
    anwenden();
    // Die Stelle unter den Fingern bleibt unter den Fingern
    const s = svgHolen(); if (!s) return;
    const r = s.getBoundingClientRect(), mx = (m.x + n.x) / 2, my = (m.y + n.y) / 2;
    box.scrollLeft += (r.left + pinch.fx * r.width) - mx;
    const dy = (r.top + pinch.fy * r.height) - my;
    if (Math.abs(dy) > 0.5) window.scrollBy(0, dy);
    e.preventDefault();
  });
  const ende = e => {
    const p = zeiger.get(e.pointerId);
    zeiger.delete(e.pointerId);
    const warPinch = !!pinch;
    if (zeiger.size < 2) pinch = null;
    if (!p || e.type === "pointercancel" || warPinch) return;
    const kurz = e.timeStamp - p.t0 < 300 && Math.hypot(p.x - p.x0, p.y - p.y0) < 10;
    if (!kurz) return;
    if (letzterTipp && e.timeStamp - letzterTipp.t < 350 && Math.hypot(p.x - letzterTipp.x, p.y - letzterTipp.y) < 40) {
      letzterTipp = null;
      if (faktor > 1) zuruecksetzen();
    } else letzterTipp = { t: e.timeStamp, x: p.x, y: p.y };
  };
  box.addEventListener("pointerup", ende);
  box.addEventListener("pointercancel", ende);
  box.addEventListener("touchmove", e => { if (e.touches.length >= 2 && e.cancelable) e.preventDefault(); }, { passive: false });
}

/* ---------- Aufbau nach dem Laden ---------- */
function aufbauen() {
  // Rueckstellknopf und Hinweis je Wetterstation-Reiter
  for (const g of ["heute", "verlauf"]) {
    const seite = $(`#seite-station-${g}`); if (!seite) continue;
    const titel = $(".diagrammtitel", seite);          // Zeile "Temperatur" ueber dem ersten Diagramm
    if (titel) {
      const k = document.createElement("button");
      k.type = "button"; k.className = "ww-zurueck"; k.hidden = true; k.textContent = "Ganzer Zeitraum";
      k.addEventListener("click", () => zoomZuruecksetzen(g));
      titel.appendChild(k);
    }
    const regen = $(g === "heute" ? "#st-plotHeuteRegen" : "#st-plotVerlaufRegen");
    let schonBenutzt = false;
    try { schonBenutzt = localStorage.getItem("ww-zoom-benutzt") === "1"; } catch (e) { /* egal */ }
    if (regen) {
      const h = document.createElement("p");
      h.className = "ww-hinweis"; h.hidden = schonBenutzt;
      h.textContent = "Mit zwei Fingern ins Diagramm zoomen, doppeltippen zum Zurücksetzen.";
      regen.insertAdjacentElement("afterend", h);
    }
    for (const id of g === "heute" ? ["#st-plotHeuteTemp", "#st-plotHeuteRegen"] : ["#st-plotVerlaufTemp", "#st-plotVerlaufRegen"]) {
      const box = $(id); if (box) stationGesten(box, g);
    }
  }
  // Die Mittelfrist besitzt bereits eine lesbare feste Breite und natives Scrollen.
  // Der generische Pinch-Reset wuerde diese Breite wieder entfernen.
  const andere = ["#plot-wetter48", "#seite-vorhersage-analyse .plot", "#seite-analyse .plot"];
  for (const sel of andere) document.querySelectorAll(sel).forEach(wachsenGesten);
  // Adresse ohne Zeitstempel zeigen (wie bei der normalen Seite): Neuladen und Anheften bleiben sauber.
  try { history.replaceState(null, "", "handy.html" + location.hash); } catch (e) { /* z. B. file:// */ }
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", aufbauen);
else aufbauen();

/* ---------- Kleiner Dienst: damit Chrome "App installieren" anbietet ---------- */
if ("serviceWorker" in navigator && location.protocol !== "file:") {
  addEventListener("load", () => {
    navigator.serviceWorker.register("handy-sw.js", { scope: "./handy" }).catch(() => { /* ohne Dienst laeuft alles weiter */ });
  });
}
})();
