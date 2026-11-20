// Shared helpers for the TV and phone shells and for question-type modules.

/** Create an element: h("div.card#id", {onclick, style:{}, dataset:{}}, ...children). Text is never parsed as HTML. */
export function h(tag, attrs, ...children) {
  const [, name = "div", rest = ""] = tag.match(/^([a-z0-9-]*)(.*)$/i);
  const el = document.createElement(name || "div");
  for (const part of rest.match(/[.#][^.#]+/g) || []) {
    if (part[0] === ".") el.classList.add(part.slice(1));
    else el.id = part.slice(1);
  }
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "style" && typeof v === "object") {
      for (const [prop, val] of Object.entries(v)) {
        if (prop.startsWith("--")) el.style.setProperty(prop, val);
        else el.style[prop] = val;
      }
    }
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className += " " + v;
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/** Replace all children of el. */
export function fill(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

/** Spanish number format: 1.234,5 */
export function fmt(value, unit = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  const text = Number(value).toLocaleString("es-ES", { maximumFractionDigits: 2 });
  return unit ? `${text} ${unit}` : text;
}

/** Round to the slider step, avoiding float noise. */
export function snap(value, min, step) {
  const n = Math.round((value - min) / step);
  const decimals = (String(step).split(".")[1] || "").length;
  return Number((min + n * step).toFixed(decimals));
}

/** Avatar element: icon or photo inside a ring of the player's colour. */
export function avatar(player, size = 64) {
  const el = h("span.avatar", { style: { "--c": player.color, "--size": size + "px" }, title: player.name });
  const a = player.avatar || {};
  if (a.kind === "photo" && a.url) el.append(h("img", { src: a.url, alt: "" }));
  else if (a.kind === "photo" && a.data) el.append(h("img", { src: a.data, alt: "" }));
  else el.append(h("img", { src: `/static/icons/${a.value || "gato"}.svg`, alt: "" }));
  if (player.connected === false) el.classList.add("is-off");
  return el;
}

/** Player name coloured with their palette colour. */
export function nameTag(player) {
  return h("span.name", { style: { color: player.color } }, player.name);
}

// ----- server clock -------------------------------------------------------------

let offset = 0;
export function syncClock(serverNow) {
  offset = serverNow - Date.now() / 1000;
}
export function serverNow() {
  return Date.now() / 1000 + offset;
}
export function secondsLeft(deadline) {
  return deadline ? Math.max(0, deadline - serverNow()) : 0;
}

// ----- dynamic question types --------------------------------------------------------

const modules = new Map();
const styles = new Set();

/** Load /qtypes/<type>/<side>.js (and style.css once). side = "tv" | "phone". */
export async function loadType(type, side, info) {
  if (info?.[type]?.css && !styles.has(type)) {
    styles.add(type);
    document.head.append(h("link", { rel: "stylesheet", href: `/qtypes/${type}/style.css` }));
  }
  const key = `${type}/${side}`;
  if (!modules.has(key)) modules.set(key, import(`/qtypes/${type}/${side}.js`));
  return modules.get(key);
}

const scripts = new Map();
/** Load an external script once (used by the map type for Google Maps). */
export function loadScript(src, timeoutMs = 8000) {
  if (!scripts.has(src)) {
    scripts.set(src, new Promise((resolve, reject) => {
      const s = h("script", { src, async: true });
      const timer = setTimeout(() => reject(new Error("timeout")), timeoutMs);
      s.onload = () => { clearTimeout(timer); resolve(); };
      s.onerror = () => { clearTimeout(timer); scripts.delete(src); reject(new Error("load error")); };
      document.head.append(s);
    }));
  }
  return scripts.get(src);
}

/** Colours and letters used for answer options (shared by TV and phones). */
export const OPTION_COLORS = ["#ff6b6b", "#4dabf7", "#ffd43b", "#51cf66", "#e599f7", "#ffa94d", "#3bc9db", "#ced4da"];
export const OPTION_LETTERS = "ABCDEFGH";

export const SPACE_LABEL = { start: "Salida", normal: "", event: "Evento", duel: "Duelo", star: "Estrella" };
export const SPACE_GLYPH = { start: "⚑", normal: "", event: "🎲", duel: "⚔️", star: "★" };

export function modeText(settings) {
  if (settings.mode === "rounds") return `${settings.rounds} ${settings.rounds === 1 ? "ronda" : "rondas"}`;
  if (settings.mode === "categories") return `Cerrar ${settings.categoriesToClose} categorías`;
  return `A ${fmt(settings.targetPoints)} puntos`;
}
