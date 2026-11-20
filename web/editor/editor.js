// Question editor: paste text, review it with the game's validator, append it to a category.
import { h, fill, fmt } from "/static/js/ui.js";

const $ = (id) => document.getElementById(id);
const DRAFT_KEY = "familygame.editor.draft";
const NEW = "__nueva__";

const state = { categories: [], types: [], type: "test", items: [], timer: 0, seq: 0, busy: false };

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private mode or blocked storage: the draft just is not kept */ }
  return null;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? { method: "GET" } : {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `respuesta ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `error ${res.status}`);
  return data;
}

// ----- state from the server -----------------------------------------------------------

function applyState(data) {
  state.categories = data.categories;
  state.types = data.types;
  if (!state.types.some((t) => t.id === state.type)) state.type = state.types[0]?.id || "test";
  renderCategories();
  renderTypes();
  renderStats();
  if (data.errors?.length) notice("bad", "Problemas al cargar: " + data.errors.join(" · "));
}

function renderStats() {
  const total = state.categories.reduce((n, c) => n + c.count, 0);
  $("stats").textContent = `${state.categories.length} categorías · ${fmt(total)} preguntas en el juego`;
}

function renderCategories() {
  const select = $("category");
  const previous = select.value || store("familygame.editor.category");
  fill(select,
    state.categories.map((c) => h("option", { value: c.file }, `${c.icon}  ${c.name} — ${fmt(c.count)}`)),
    h("option", { value: NEW }, "＋ Categoría nueva…"),
  );
  if ([...select.options].some((o) => o.value === previous)) select.value = previous;
  syncNewCategory();
}

function renderTypes() {
  fill($("types"), state.types.map((t) => h("button", {
    type: "button",
    role: "radio",
    "aria-checked": String(t.id === state.type),
    title: t.needsInternet ? "Necesita internet y clave de Google Maps al jugar" : "",
    onclick: () => { state.type = t.id; store("familygame.editor.type", t.id); renderTypes(); scheduleReview(0); },
  }, t.name)));
  const type = currentType();
  $("help-name").textContent = type?.name || "";
  $("help-text").textContent = type?.help || "";
}

const currentType = () => state.types.find((t) => t.id === state.type);
const isNew = () => $("category").value === NEW;

function syncNewCategory() {
  const open = isNew();
  $("new-cat").hidden = !open;
  $("toggle-new").setAttribute("aria-expanded", String(open));
  $("toggle-new").textContent = open ? "Elegir existente" : "Nueva categoría";
  renderSummary();
}

function targetName() {
  if (isNew()) return $("new-name").value.trim() || "la categoría nueva";
  const cat = state.categories.find((c) => c.file === $("category").value);
  return cat ? cat.name : "";
}

// ----- review ------------------------------------------------------------------------------

function scheduleReview(delay = 450) {
  clearTimeout(state.timer);
  state.timer = setTimeout(review, delay);
}

async function review() {
  const text = $("text").value;
  store(DRAFT_KEY, text);
  updateLineCount();
  const seq = ++state.seq;
  if (!text.trim()) {
    state.items = [];
    renderCards();
    return;
  }
  try {
    const data = await api("/api/revisar", { text, tipo: state.type });
    if (seq !== state.seq) return;
    state.items = data.items;
    renderCards();
  } catch (err) {
    if (seq === state.seq) notice("bad", err.message);
  }
}

function updateLineCount() {
  const lines = $("text").value ? $("text").value.split("\n").length : 0;
  $("line-count").textContent = lines ? `· ${lines} líneas` : "";
}

function renderSummary() {
  const good = state.items.filter((i) => i.ok).length;
  const bad = state.items.length - good;
  const button = $("add");
  if (!state.items.length) {
    $("summary").textContent = "Pega preguntas a la izquierda.";
  } else {
    const parts = [`${good} ${good === 1 ? "válida" : "válidas"}`];
    if (bad) parts.push(`${bad} con errores (no se añaden)`);
    $("summary").textContent = parts.join(" · ");
  }
  button.disabled = state.busy || !good || (isNew() && !$("new-name").value.trim());
  button.textContent = good ? `Añadir ${good} a ${targetName()}` : "Añadir";
}

function renderCards() {
  renderSummary();
  if (!state.items.length) {
    fill($("cards"), h("li.empty", "Aquí verás cada pregunta tal como quedará, con sus errores."));
    return;
  }
  fill($("cards"), state.items.map(card));
}

function card(item) {
  const warn = item.ok && item.warnings.length;
  const cls = item.ok ? (warn ? "card is-warn" : "card") : "card is-bad";
  return h("li", { class: cls, title: "Clic para ir a sus líneas", onclick: (e) => { if (!e.target.closest("details")) selectLines(item.line, item.end); } },
    h("div.card-head",
      h("span.line", item.line === item.end ? `L${item.line}` : `L${item.line}–${item.end}`),
      h("span.chip", item.typeName),
      h("span.state", item.ok ? "Lista" : "Con errores"),
    ),
    h("p.prompt", item.prompt || "(sin enunciado)"),
    details(item.raw),
    item.errors.length ? h("ul.msgs.bad", item.errors.map((m) => h("li", m))) : null,
    item.warnings.length ? h("ul.msgs.warn", item.warnings.map((m) => h("li", m))) : null,
    item.toml ? h("details.toml", h("summary", "Ver cómo queda en el archivo"), h("pre", item.toml)) : null,
  );
}

const SKIP = new Set(["tipo", "enunciado", "opciones", "correcta", "explicacion"]);
const LABELS = {
  min: "mín", max: "máx", paso: "paso", unidad: "unidad", respuesta: "respuesta", tolerancia: "± ",
  tolerancia_pct: "± %", inicio: "inicio", criterio: "criterio", solape_min: "solape mín %",
  ancho_max: "ancho máx", margen: "margen", radio: "radio", zona: "zona", vista: "vista",
  tiempo: "tiempo", lectura: "lectura", dificultad: "dificultad", puntos: "puntos", barajar: "barajar",
  imagen: "imagen", id: "id",
};

function show(key, value, raw) {
  if (key === "radio") return value >= 1000 ? fmt(value / 1000, "km") : fmt(value, "m");
  if (key === "zona") return `${value.length} puntos`;
  if (key === "tiempo" || key === "lectura") return fmt(value, "s");
  if (key === "barajar") return value ? "sí" : "no";
  if (Array.isArray(value)) return value.map((v) => fmt(v, raw.unidad || "")).join(" – ");
  if (value && typeof value === "object") {
    return [value.lat, value.lng].join(", ") + (value.zoom ? ` · zoom ${value.zoom}` : "");
  }
  if (typeof value === "number") return fmt(value, ["respuesta", "min", "max", "inicio", "tolerancia"].includes(key) ? raw.unidad || "" : "");
  return String(value);
}

function details(raw) {
  if (!raw || !Object.keys(raw).length) return null;
  const options = Array.isArray(raw.opciones) ? raw.opciones : [];
  const correct = typeof raw.correcta === "number" ? raw.correcta - 1
    : options.findIndex((o) => o.toLowerCase() === String(raw.correcta ?? "").trim().toLowerCase());
  const facts = Object.entries(raw).filter(([k]) => !SKIP.has(k) && k !== "unidad");
  return [
    options.length ? h("ul.opts", options.map((o, i) => h("li", { class: i === correct ? "ok" : "" }, i === correct ? `✓ ${o}` : o))) : null,
    facts.length ? h("dl.facts", facts.map(([k, v]) => h("div", h("dt", LABELS[k] || k), h("dd", show(k, v, raw))))) : null,
    raw.explicacion ? h("p.explain", raw.explicacion) : null,
  ];
}

function selectLines(first, last) {
  const area = $("text");
  const lines = area.value.split("\n");
  let start = 0;
  for (let i = 0; i < first - 1; i++) start += lines[i].length + 1;
  let end = start;
  for (let i = first - 1; i < last; i++) end += (lines[i]?.length ?? 0) + 1;
  area.focus();
  area.setSelectionRange(start, Math.max(start, end - 1));
  const lineHeight = parseFloat(getComputedStyle(area).lineHeight) || 22;
  area.scrollTop = Math.max(0, (first - 3) * lineHeight);
}

// ----- add -----------------------------------------------------------------------------------

async function add() {
  const text = $("text").value;
  const body = { text, tipo: state.type };
  if (isNew()) {
    body.nueva = { nombre: $("new-name").value.trim(), icono: $("new-icon").value.trim(), color: $("new-color").value };
  } else {
    body.archivo = $("category").value;
  }
  state.busy = true;
  renderSummary();
  try {
    const data = await api("/api/anadir", body);
    state.categories = data.categories;
    renderCategories();
    $("category").value = data.file;
    store("familygame.editor.category", data.file);
    syncNewCategory();
    renderStats();
    $("text").value = data.remaining;
    const left = data.items.length - data.added;
    notice("good",
      `${data.added} ${data.added === 1 ? "pregunta añadida" : "preguntas añadidas"} a ${data.file} (ahora tiene ${fmt(data.total)}).` +
      (left ? ` Se han quedado en el texto las ${left} con errores.` : "") +
      " En el juego, pulsa «Recargar preguntas» en el lobby.");
  } catch (err) {
    notice("bad", err.message);
  } finally {
    state.busy = false;
    review();
  }
}

function notice(kind, text) {
  const el = $("notice");
  el.className = `notice ${kind}`;
  el.textContent = text;
  el.hidden = false;
}

// ----- guide -----------------------------------------------------------------------------

function fullGuide() {
  const common = [
    "FORMATO DEL EDITOR DE PREGUNTAS DE FAMILYGAME",
    "Un bloque por pregunta, separados por una línea en blanco. La primera línea es el enunciado.",
    "Campos comunes (opcionales): tiempo: 15 · lectura: 2 · dificultad: 1, 2 o 3 · explicacion: dato curioso · imagen: img/x.jpg",
    "«tipo: <mecánica>» dentro de un bloque cambia su mecánica; un bloque que solo tiene «tipo: …» la cambia para los siguientes.",
    "Las líneas que empiezan por # son comentarios.",
  ].join("\n");
  const parts = state.types.map((t) => `== ${t.name} (tipo: ${t.id}) ==\n${t.help}\n\nEjemplo:\n${t.example}`);
  return [common, ...parts].join("\n\n");
}

async function copyGuide() {
  try {
    await navigator.clipboard.writeText(fullGuide());
    notice("good", "Guía de formato copiada al portapapeles.");
  } catch {
    notice("bad", "No se pudo copiar: el navegador no deja usar el portapapeles.");
  }
}

function insertExample() {
  const type = currentType();
  if (!type) return;
  const area = $("text");
  const prefix = area.value.trim() ? area.value.replace(/\s*$/, "") + "\n\n" : "";
  area.value = prefix + type.example + "\n";
  scheduleReview(0);
}

// ----- start -------------------------------------------------------------------------------

async function boot() {
  state.type = store("familygame.editor.type") || "test";
  $("text").value = store(DRAFT_KEY) || "";
  $("help").open = !$("text").value.trim();
  $("text").addEventListener("input", () => scheduleReview());
  $("text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); scheduleReview(0); }
  });
  $("category").addEventListener("change", () => {
    if (!isNew()) store("familygame.editor.category", $("category").value);
    syncNewCategory();
  });
  $("toggle-new").addEventListener("click", () => {
    const select = $("category");
    select.value = isNew() ? (state.categories[0]?.file || NEW) : NEW;
    syncNewCategory();
    if (isNew()) $("new-name").focus();
  });
  $("new-name").addEventListener("input", renderSummary);
  $("add").addEventListener("click", add);
  $("insert-example").addEventListener("click", insertExample);
  $("copy-guide").addEventListener("click", copyGuide);
  $("reload").addEventListener("click", async () => {
    try {
      applyState(await api("/api/recargar", {}));
      notice("good", "Tipos y categorías leídos de nuevo del disco.");
      scheduleReview(0);
    } catch (err) { notice("bad", err.message); }
  });
  try {
    applyState(await api("/api/estado"));
  } catch (err) {
    notice("bad", "No se pudo hablar con el editor: " + err.message);
  }
  renderCards();
  scheduleReview(0);
}

boot();
