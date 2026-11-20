// Phone controller: profile, lobby (host settings), choosing, answering, results.
import { connect } from "./net.js";
import {
  h, fill, fmt, avatar, nameTag, secondsLeft, freezeClock, loadType, snap, modeText,
  OPTION_COLORS, OPTION_LETTERS,
} from "./ui.js";
import { choiceStage, choiceOf, MECHANICS } from "./choice.js";

const app = document.getElementById("app");
const toastBox = document.getElementById("toast");
const store = {
  get(k, d = null) { try { const v = localStorage.getItem("fg." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("fg." + k, JSON.stringify(v)); } catch { /* storage full or blocked */ } },
  del(k) { try { localStorage.removeItem("fg." + k); } catch { /* ignore */ } },
};

let info = { icons: [], types: {} };
let state = null;
let myId = null;
let editing = false;
let notice = "";
let gate = null; // screens shown before the profile: claim a seat, kicked, opened in another tab
let showPlayers = false; // the players panel is open
let screen = null;
let screenKey = "";

const net = connect("/ws/phone", {
  onStatus(ok) {
    document.getElementById("offline").hidden = ok;
    if (ok) net.send({ t: "hello", token: store.get("token") });
  },
  onMessage(msg) {
    if (msg.t === "welcome") {
      info = msg;
      myId = msg.id;
      if (msg.id) gate = null;
      else if (msg.kicked) gate = { kind: "kicked" }; // keep the token: the host may readmit
      else {
        if (store.get("token")) store.del("token");
        // someone who left from this same phone/address may take their seat back
        gate = msg.claimable?.length ? { kind: "claim", list: msg.claimable } : null;
      }
    } else if (msg.t === "joined") {
      myId = msg.id;
      store.set("token", msg.token);
      editing = false;
      gate = null;
    } else if (msg.t === "state") {
      state = msg.state;
      if (state.me) { myId = state.me.id; gate = null; }
      render();
    } else if (msg.t === "error") {
      toast(msg.msg);
    } else if (msg.t === "kicked") {
      myId = null;
      gate = { kind: "kicked" };
      render(true);
    } else if (msg.t === "replaced") { // the same player opened the game in another tab
      myId = null;
      gate = { kind: "replaced" };
      render(true);
    } else if (msg.t === "left") {
      store.del("token");
      myId = null;
      notice = "Has salido de la partida. Si vuelves desde este móvil, podrás retomar tus puntos.";
      render(true);
    }
  },
});

function toast(text) {
  const t = h("div.toast-msg", text);
  toastBox.append(t);
  setTimeout(() => t.remove(), 3500);
}

const playerById = (id) => state?.players.find((p) => p.id === id);
const catById = (id) => state?.categories.find((c) => c.id === id);

// ----- countdown loop --------------------------------------------------------------------
const timers = new Set();
(function loop() {
  for (const t of timers) {
    const [start, end] = t();
    const left = secondsLeft(end);
    const frac = Math.max(0, Math.min(1, left / Math.max(0.1, end - start)));
    document.querySelectorAll("[data-timebar] > i").forEach((i) => i.style.transform = `scaleX(${frac})`);
    document.querySelectorAll("[data-timebar]").forEach((b) => b.classList.toggle("is-low", left < 4));
    document.querySelectorAll("[data-timenum]").forEach((n) => n.textContent = Math.ceil(left));
  }
  requestAnimationFrame(loop);
})();
function setTimer(fn) { timers.clear(); if (fn) timers.add(fn); }

// ----- routing ---------------------------------------------------------------------------
function keyFor() {
  if (!state) return "loading";
  if (gate && (!state.me || ["replaced", "kicked"].includes(gate.kind))) return "gate:" + gate.kind;
  if (!state.me || editing) return "profile";
  const s = state;
  if (["reading", "answering", "reveal"].includes(s.phase) && s.question) return `q:${s.question.key}:${s.question.number}:${s.question.tiebreak}`;
  return s.phase;
}

function render(force = false) {
  const key = keyFor();
  if (force || key !== screenKey) {
    screen?.destroy?.();
    screenKey = key;
    setTimer(null);
    const make = key.startsWith("q:") ? questionScreen : key.startsWith("gate:") ? gateScreen : {
      loading: () => ({ el: h("div.center-msg", "Conectando…"), update() {} }),
      profile: profileScreen, lobby: lobbyScreen, choosing: choosingScreen,
      board: boardScreen, tiebreak: tiebreakScreen, finished: finishedScreen,
    }[key];
    screen = make();
    fill(app, screen.el);
    window.scrollTo(0, 0);
  }
  screen.update?.(state);
  freezeClock(state?.paused ? state.pausedAt : null);
  if (state?.me) updateOverlay(state);
  else { showPlayers = false; overlay.hidden = true; }
}

// ----- gates: claim a seat, kicked, opened in another tab ------------------------------------------
function gateScreen() {
  const g = gate;
  const again = () => net.send({ t: "hello", token: store.get("token") });
  const newPlayer = () => { gate = null; render(true); };
  let body;
  if (g.kind === "claim") {
    body = [
      h("h1.title", "¿Ya estabas jugando?"),
      h("p.hint.center", "Hemos reconocido este móvil. Si eres uno de estos, recuperas tus puntos y tu sitio:"),
      ...g.list.map((c) => h("button.btn.primary.block", { type: "button", onclick: () => net.send({ t: "claim", player: c.id }) },
        avatar(c, 36), ` Soy ${c.name} · ${fmt(c.points)} pts`)),
      h("button.btn.ghost.block", { type: "button", onclick: newPlayer }, "No, soy nuevo"),
    ];
  } else if (g.kind === "kicked") {
    body = [
      h("h1.title", "Te han sacado de la partida"),
      h("p.hint.center", "Puede que haya sido por un problema técnico. Pide al anfitrión que te readmita y pulsa «Reintentar»: recuperarás tus puntos."),
      h("button.btn.primary.block", { type: "button", onclick: again }, "Reintentar"),
      h("button.btn.ghost.block", { type: "button", onclick: () => { store.del("token"); newPlayer(); } }, "Entrar como jugador nuevo"),
    ];
  } else {
    body = [
      h("h1.title", "Juego abierto en otra pestaña"),
      h("p.hint.center", "Este jugador se ha abierto en otra pestaña o ventana de este móvil, y solo puede estar en una a la vez."),
      h("button.btn.primary.block", { type: "button", onclick: () => { gate = null; again(); } }, "Usar esta pestaña"),
    ];
  }
  return { el: h("div.screen.gate", body), update() {} };
}

// ----- presence: heartbeat + visibility so the match pauses if this phone goes away ------------------
function sendPresence() {
  if (myId) net.sendLive({ t: "ping", visible: !document.hidden });
}
setInterval(sendPresence, 4000);
document.addEventListener("visibilitychange", sendPresence);

// ----- pause overlay (everyone) and players panel -------------------------------------------------------
const overlay = h("div.overlay", { hidden: true });
document.body.append(overlay);

function canResume(s) {
  return s.me?.host || (s.pausedReason === "manual" && s.pausedBy === s.me?.id);
}

function updateOverlay(s) {
  const panel = showPlayers && s.me ? playersPanel(s) : null;
  const paused = !!(s.paused && s.me);
  overlay.hidden = !(panel || paused);
  if (panel) { fill(overlay, panel); return; }
  if (!paused) { fill(overlay); return; }
  const by = s.players.find((p) => p.id === s.pausedBy);
  const afk = s.afk.map((id) => s.players.find((p) => p.id === id)?.name).filter(Boolean);
  fill(overlay, h("div.pause-card",
    h("p.pause-icon", "⏸"),
    h("h1.title", "Partida en pausa"),
    h("p.hint.center", s.pausedReason === "afk"
      ? `${afk.length ? afk.join(", ") : "Alguien"} no responde (móvil bloqueado, pestaña oculta o sin conexión).`
      : `${by ? by.name : "Alguien"} ha pausado la partida.`),
    canResume(s)
      ? h("button.btn.primary.block", { type: "button", onclick: () => net.send({ t: "unpause" }) }, "▶ Reanudar")
      : h("p.waiting", s.pausedReason === "afk" ? "Esperando al anfitrión…" : "Esperando a quien la pausó o al anfitrión…"),
    h("button.btn.ghost.block", { type: "button", onclick: () => { showPlayers = true; updateOverlay(state); } }, "👥 Jugadores")));
}

function playersPanel(s) {
  const me = s.me;
  const inMatch = !["lobby", "finished"].includes(s.phase);
  const send = (t, extra = {}) => net.send({ t, ...extra });
  const rows = s.players.map((p) => h("div.prow", avatar(p, 40), nameTag(p),
    p.host ? h("span.tag", "👑") : null,
    !p.connected ? h("span.tag.off", "desconectado") : null,
    s.afk.includes(p.id) && p.connected ? h("span.tag.off", "ausente") : null,
    inMatch ? h("small.muted", `${fmt(p.points)} pts`) : null,
    me.host && p.id !== me.id ? h("span.prow-actions",
      p.connected ? h("button.btn.ghost.mini", { type: "button", title: "Dar el mando", onclick: () => {
        if (confirm(`¿Dar el mando de anfitrión a ${p.name}?`)) send("host", { player: p.id });
      } }, "Mando") : null,
      h("button.btn.danger.mini", { type: "button", onclick: () => {
        if (confirm(`¿Sacar a ${p.name} de la partida? Podrás readmitirlo después.`)) send("kick", { player: p.id });
      } }, "Echar")) : null));
  const awayRow = (a) => {
    const sel = h("select", s.players.filter((p) => p.id !== me.id).map((p) => h("option", { value: p.id }, p.name)));
    return h("div.away-row",
      h("div.prow", avatar(a, 40), h("span", a.name),
        h("small.muted", `${fmt(a.points)} pts · ${a.reason === "kicked" ? "echado" : "salió"}`),
        h("span.prow-actions",
          h("button.btn.ghost.mini", { type: "button", onclick: () => send("readmit", { player: a.id }) }, "Readmitir"),
          h("button.btn.danger.mini", { type: "button", onclick: () => {
            if (confirm(`¿Liberar la plaza de ${a.name}? Pierde sus puntos.`)) send("forget", { player: a.id });
          } }, "Liberar"))),
      inMatch && s.players.length > 1 ? h("div.assign",
        h("small.muted", "¿Es alguien que acaba de entrar con otro móvil?"),
        h("span", sel, h("button.btn.ghost.mini", { type: "button", onclick: () => send("assign", { new: sel.value, player: a.id }) }, "Es él"))) : null);
  };
  const away = s.away?.length && me.host ? h("div.card",
    h("p.card-title", "Fuera de la partida"),
    h("p.hint", "Conservan sus puntos y su plaza. Quien se fue por su cuenta vuelve solo desde su móvil."),
    s.away.map(awayRow)) : null;
  const st = s.settings;
  const late = me.host ? h("div.card",
    h("p.card-title", "Quien entre con la partida empezada"),
    h("div.seg",
      ...[["zero", "0 puntos"], ["average", "La media"], ["fixed", "Fijo"]].map(([mode, label]) =>
        h("button.seg-btn", { type: "button", class: st.lateJoin === mode ? "is-on" : "", onclick: () => send("settings", { changes: { lateJoin: mode } }) }, label))),
    st.lateJoin === "fixed" ? stepper("Puntos de inicio", st.latePoints, 0, 5000, 50, (v) => send("settings", { changes: { latePoints: v } })) : null) : null;
  return h("div.panel",
    h("div.panel-head", h("h1.title", "Jugadores"),
      h("button.btn.ghost.mini", { type: "button", onclick: () => { showPlayers = false; updateOverlay(state); } }, "✕ Cerrar")),
    h("div.card", h("div.plist", rows)),
    away, late,
    h("button.btn.danger.block", { type: "button", onclick: () => {
      if (confirm(inMatch ? "¿Salir de la partida? Si vuelves desde este móvil, recuperarás tus puntos." : "¿Salir de la partida?")) {
        showPlayers = false;
        send("leave");
      }
    } }, "Salir de la partida"));
}

// ----- header ------------------------------------------------------------------------------
function header(s, extra) {
  const me = s.me;
  const rank = s.ranking.indexOf(me.id) + 1;
  return h("header.bar", { style: { "--c": me.color } },
    avatar(me, 44),
    h("div.bar-who", nameTag(me), h("small", s.phase === "lobby" ? (me.host ? "👑 Anfitrión" : "En el lobby") : `#${rank} · ${fmt(me.points)} pts`)),
    extra || null,
    pauseButton(s),
    h("button.btn.ghost.mini", { type: "button", "aria-label": "Jugadores", onclick: () => { showPlayers = true; updateOverlay(state); } }, "👥"),
    soundButton(s));
}

function pauseButton(s) {
  if (["lobby", "finished"].includes(s.phase) || s.paused) return null;
  return h("button.btn.ghost.mini", { type: "button", "aria-label": "Pausar la partida", onclick: () => net.send({ t: "pause" }) }, "⏸");
}

// The host mutes or unmutes the music on the TV from any screen.
function soundButton(s) {
  if (!s.me.host) return null;
  const on = s.settings.music && s.settings.volume > 0;
  return h("button.btn.ghost.mini.sound-btn", {
    type: "button", "aria-label": on ? "Silenciar la música de la tele" : "Activar la música de la tele",
    onclick: () => net.send({ t: "settings", changes: { music: !on, ...(!on && s.settings.volume === 0 ? { volume: 70 } : {}) } }),
  }, on ? "🔊" : "🔇");
}

function hostBar(s, label = "Continuar ▸") {
  if (!s.me?.host) return null;
  return h("div.host-bar", h("button.btn.ghost.block", { type: "button", onclick: () => net.send({ t: "next" }) }, label));
}

function hostEnd(s) {
  if (!s.me?.host) return null;
  return h("div.end-bar",
    h("button.btn.ghost.small-end", { type: "button", onclick: () => {
      if (confirm("¿Guardar la partida y volver al menú? Podréis continuarla más tarde.")) net.send({ t: "save" });
    } }, "💾 Guardar y volver al menú"),
    h("button.btn.danger.small-end", { type: "button", onclick: () => {
      if (confirm("¿Terminar la partida y volver al lobby? Se pierden los puntos.")) net.send({ t: "lobby" });
    } }, "Terminar sin guardar"));
}

// ----- profile -----------------------------------------------------------------------------
async function resizePhoto(file) {
  const bitmap = await createImageBitmap(file).catch(() => null);
  let src = bitmap;
  if (!src) {
    src = await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = URL.createObjectURL(file);
    });
  }
  const size = 256;
  const w = src.width, hgt = src.height, side = Math.min(w, hgt);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  canvas.getContext("2d").drawImage(src, (w - side) / 2, (hgt - side) / 2, side, side, 0, 0, size, size);
  return canvas.toDataURL("image/jpeg", 0.82);
}

function profileScreen() {
  const saved = store.get("profile", {});
  const me = state?.me;
  const draft = {
    name: me?.name || saved.name || "",
    color: me?.color || saved.color || null,
    avatar: saved.avatar || { kind: "icon", value: info.icons[Math.floor(Math.random() * info.icons.length)] || "gato" },
  };
  if (me?.avatar?.kind === "icon") draft.avatar = me.avatar;

  const preview = h("div.preview");
  const nameInput = h("input.name-input", { type: "text", maxlength: 16, placeholder: "Tu nombre", value: draft.name, autocomplete: "nickname", "aria-label": "Nombre" });
  const icons = h("div.icon-grid");
  const colors = h("div.color-grid");
  const fileInput = h("input", { type: "file", accept: "image/*", hidden: true });
  const submit = h("button.btn.primary.block.big", { type: "button" }, me ? "Guardar cambios" : "Entrar en la partida");

  function drawPreview() {
    const p = { name: draft.name || "Tu nombre", color: draft.color || "#6b7080", avatar: draft.avatar };
    fill(preview, avatar(p, 112), h("span.preview-name", { style: { color: p.color } }, p.name));
  }
  function drawIcons() {
    fill(icons,
      h("button.icon-btn.photo-btn", { type: "button", class: draft.avatar.kind === "photo" ? "is-on" : "", "aria-label": "Subir foto", onclick: () => fileInput.click() },
        draft.avatar.kind === "photo" ? h("img", { src: draft.avatar.data, alt: "" }) : h("span", "📷")),
      info.icons.map((name) => h("button.icon-btn", {
        type: "button", "aria-label": name, class: draft.avatar.kind === "icon" && draft.avatar.value === name ? "is-on" : "",
        onclick: () => { draft.avatar = { kind: "icon", value: name }; drawIcons(); drawPreview(); },
      }, h("img", { src: `/static/icons/${name}.svg`, alt: "" }))));
  }
  function drawColors() {
    const taken = new Set(state?.takenColors || []);
    if (draft.color && taken.has(draft.color)) draft.color = null;
    fill(colors, (state?.palette || []).map(({ color, name }) => h("button.color-btn", {
      type: "button", "aria-label": name, disabled: taken.has(color), title: taken.has(color) ? `${name} (cogido)` : name,
      class: draft.color === color ? "is-on" : "", style: { "--c": color },
      onclick: () => { draft.color = color; drawColors(); drawPreview(); },
    })));
  }
  nameInput.addEventListener("input", () => { draft.name = nameInput.value; drawPreview(); });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      draft.avatar = { kind: "photo", data: await resizePhoto(file) };
      drawIcons();
      drawPreview();
    } catch {
      toast("No se pudo leer esa foto");
    }
  });
  submit.addEventListener("click", () => {
    if (!draft.name.trim()) return toast("Escribe tu nombre");
    if (!draft.color) return toast("Elige un color");
    store.set("profile", draft);
    const payload = { name: draft.name, color: draft.color, avatar: draft.avatar };
    if (me) {
      net.send({ t: "profile", ...payload });
      editing = false;
      render(true);
    } else net.send({ t: "join", ...payload });
  });

  const full = state && !state.me && state.players.length + (state.away?.length || 0) >= state.maxPlayers;
  const el = h("div.screen.profile",
    notice ? h("p.notice", notice) : null,
    h("h1.title", me ? "Tu perfil" : "¿Quién eres?"),
    preview,
    h("label.field", h("span", "Nombre"), nameInput),
    h("div.field", h("span", "Icono o foto"), icons, fileInput,
      h("small.hint", "La foto se guarda solo en tu móvil y se envía únicamente a esta partida.")),
    h("div.field", h("span", "Tu color"), colors),
    full ? h("p.notice", "La partida está llena (máximo 6 jugadores).") : null,
    submit,
    me ? h("button.btn.ghost.block", { type: "button", onclick: () => { editing = false; render(true); } }, "Cancelar") : null);
  drawPreview(); drawIcons(); drawColors();
  notice = "";
  return { el, update() { drawColors(); drawPreview(); } };
}

// ----- lobby ---------------------------------------------------------------------------------
function stepper(label, value, min, max, step, onChange, format = fmt) {
  return h("div.stepper", h("span.stepper-label", label),
    h("button.btn.step-btn", { type: "button", "aria-label": "Menos", disabled: value <= min, onclick: () => onChange(Math.max(min, value - step)) }, "−"),
    h("output.stepper-value", format(value)),
    h("button.btn.step-btn", { type: "button", "aria-label": "Más", disabled: value >= max, onclick: () => onChange(Math.min(max, value + step)) }, "+"));
}

function lobbyScreen() {
  const el = h("div.screen.lobby");
  const send = (changes) => net.send({ t: "settings", changes });
  return {
    el,
    update(s) {
      const me = s.me;
      const st = s.settings;
      const host = playerById(s.hostId);
      const players = h("div.card",
        h("p.card-title", `Jugadores ${s.players.length}/${s.maxPlayers}`),
        h("div.plist", s.players.map((p) => h("div.prow", avatar(p, 40), nameTag(p),
          p.host ? h("span.tag", "👑") : null, !p.connected ? h("span.tag.off", "desconectado") : null,
          me.host && p.id !== me.id ? h("button.kick", { type: "button", "aria-label": `Sacar a ${p.name}`, onclick: () => {
            if (confirm(`¿Sacar a ${p.name} de la partida?`)) net.send({ t: "kick", player: p.id });
          } }, "✕") : null))));
      const enabled = s.categories.filter((c) => c.enabled);
      let settings;
      if (me.host) {
        const modeBtn = (mode, label) => h("button.seg-btn", { type: "button", class: st.mode === mode ? "is-on" : "", onclick: () => send({ mode }) }, label);
        const modeRow = {
          points: stepper("Puntos para ganar", st.targetPoints, 250, 10000, 250, (v) => send({ targetPoints: v })),
          rounds: stepper("Rondas (cada uno elige una vez)", st.rounds, 1, 15, 1, (v) => send({ rounds: v })),
          categories: h("div",
            stepper("Categorías a cerrar", st.categoriesToClose, 1, Math.max(1, enabled.length), 1, (v) => send({ categoriesToClose: v })),
            stepper("Aciertos para cerrar una", st.hitsToClose, 1, 8, 1, (v) => send({ hitsToClose: v }))),
        }[st.mode];
        settings = h("div.card",
          h("p.card-title", "Cómo se gana"),
          h("div.seg", modeBtn("points", "Puntos"), modeBtn("rounds", "Rondas"), modeBtn("categories", "Categorías")),
          modeRow,
          h("p.hint", st.mode === "categories"
            ? "Una categoría se cierra con esos aciertos o acertando desde una casilla ★."
            : "Cerrar una categoría (aciertos o casilla ★) da +100 puntos."),
          h("p.card-title", "Mecánicas"),
          h("div.mech-row", Object.entries(MECHANICS).map(([id, m]) => h("button.mech-chip", {
            type: "button", class: (st.mechanics || []).includes(id) ? "is-on" : "", onclick: () => send({ toggleMechanic: id }),
          }, h("span", m.icon), h("span", m.name)))));
      }
      const sv = s.saved;
      const savedCard = sv ? h("div.card.saved-card",
        h("p.card-title", "💾 Partida guardada"),
        h("p.hint", `${sv.players.join(", ")} · ronda ${sv.round} · ${modeText({ ...st, mode: sv.mode })}`),
        me.host ? h("button.btn.primary.block", { type: "button", onclick: () => net.send({ t: "resume" }) }, "▶ Continuar partida guardada") : h("p.waiting", "El anfitrión puede continuarla"),
        me.host ? h("button.btn.danger.block", { type: "button", onclick: () => {
          if (confirm("¿Descartar la partida guardada? No se puede recuperar.")) net.send({ t: "discard" });
        } }, "Descartar partida guardada") : null) : null;
      const sendSound = (changes) => net.send({ t: "settings", changes });
      const soundCard = me.host ? h("div.card",
        h("p.card-title", "Sonido de la tele"),
        h("label.crow", h("input", { type: "checkbox", checked: st.music, onchange: (e) => sendSound({ music: e.target.checked }) }),
          h("span.cicon", "🎵"), h("span.cname", "Música de fondo")),
        h("label.crow", h("input", { type: "checkbox", checked: st.sfx, onchange: (e) => sendSound({ sfx: e.target.checked }) }),
          h("span.cicon", "🔔"), h("span.cname", "Efectos de sonido")),
        stepper("Volumen", st.volume, 0, 100, 10, (v) => sendSound({ volume: v }), (v) => `${v}%`)) : null;
      const cats = h("div.card",
        h("p.card-title", `Categorías (${enabled.length} activas)`),
        h("div.clist", s.categories.map((c) => {
          const reason = c.errorCount && !c.playable ? `archivo con errores` : !c.playable ? (c.unavailableReasons[0] || "sin preguntas") : "";
          const row = h("label.crow", { class: !c.playable ? "is-bad" : "" },
            h("input", { type: "checkbox", checked: c.enabled, disabled: !me.host || !c.playable,
              onchange: () => send({ toggleCategory: c.id }) }),
            h("span.cicon", c.icon),
            h("span.cname", c.name, h("small", reason || `${c.count} preguntas` + (c.errorCount ? ` · ${c.errorCount} con errores` : ""))));
          return row;
        })),
        me.host ? h("button.btn.ghost.block", { type: "button", onclick: () => net.send({ t: "reload" }) }, "↻ Recargar preguntas") : null);
      const actions = me.host
        ? h("button.btn.primary.block.big", { type: "button", disabled: !enabled.length, onclick: () => net.send({ t: "start" }) }, "Empezar partida")
        : h("p.waiting", `Esperando a que ${host ? host.name : "el anfitrión"} empiece… · ${modeText(st)}`);
      fill(el,
        header(s, h("button.btn.ghost.mini", { type: "button", onclick: () => { editing = true; render(true); } }, "Editar")),
        savedCard, actions, players, settings || null, soundCard, cats,
        h("button.btn.danger.block", { type: "button", onclick: () => { if (confirm("¿Salir de la partida?")) net.send({ t: "leave" }); } }, "Salir de la partida"));
    },
  };
}

// ----- choosing -------------------------------------------------------------------------------
function choosingScreen() {
  const el = h("div.screen.choosing");
  let sig = "";
  let stage = null;
  return {
    el,
    update(s) {
      const c = choiceOf(s);
      const me = s.me.id;
      const acting = c.actorId === me;
      const next = `${c.mechanic}:${c.introUntil}:${c.chooserId}:${c.actorId}`;
      setTimer(() => [s.deadline - (s.chooserId ? s.chooseTime : 1.5), s.deadline]);
      if (next !== sig) {
        sig = next;
        stage?.destroy();
        const chooser = playerById(c.chooserId);
        const actor = playerById(c.actorId);
        const title = {
          ruleta: acting ? "¡Gira la ruleta!" : null,
          moneda: acting ? "¡Lanza la moneda!" : null,
          rival: acting ? ["Elige la categoría para ", chooser ? nameTag(chooser) : "ti", " 😈"] : null,
          eleccion: acting ? "Elige una de tres" : null,
        }[c.mechanic];
        const waiting = c.mechanic === "rival" && c.chooserId === me
          ? h("p.waiting", actor ? nameTag(actor) : "Alguien", " está eligiendo por ti…")
          : c.mechanic === "rival" && !acting
            ? h("p.waiting", actor ? nameTag(actor) : "Alguien", " está eligiendo por ", chooser ? nameTag(chooser) : "…")
            : !acting && (c.mechanic === "eleccion")
              ? h("p.waiting", chooser ? nameTag(chooser) : "Alguien", " está eligiendo categoría…") : null;
        stage = choiceStage({
          size: acting && (c.mechanic === "ruleta" || c.mechanic === "moneda") ? "big" : "small",
          catById, playerById,
          onSpin: acting && (c.mechanic === "ruleta" || c.mechanic === "moneda") ? () => net.send({ t: "spin" }) : null,
          body: (ch) => acting
            ? h("div.cat-grid", ch.offered.map((id) => {
              const cat = catById(id);
              return cat && h("button.cat-btn", { type: "button", dataset: { cat: id }, style: { "--cc": cat.color },
                disabled: !!ch.result, onclick: () => net.send({ t: "choose", category: id }) },
              h("span.cat-icon", cat.icon), h("span", cat.name));
            }))
            : h("div.cat-grid.is-view", ch.offered.map((id) => {
              const cat = catById(id);
              return cat && h("div.cat-btn", { dataset: { cat: id }, style: { "--cc": cat.color } }, h("span.cat-icon", cat.icon), h("span", cat.name));
            })),
        });
        const timebar = h("div.timebar", { dataset: { timebar: "" } }, h("i"));
        fill(el, header(s), title ? h("h1.title", title) : null, timebar, stage.el, waiting,
          h("p.hint.center", "Quedan ", h("b", { dataset: { timenum: "" } }), " s; si no, se actúa al azar"), hostEnd(s));
      }
      stage.update(c);
    },
    destroy() { stage?.destroy(); },
  };
}

// ----- question ---------------------------------------------------------------------------------
function questionScreen() {
  const s0 = state;
  const q = s0.question;
  const canvas = h("div.q-canvas");
  const status = h("div.q-status");
  const result = h("div.q-result");
  const prompt = h("h1.q-prompt", q.prompt);
  const hint = h("p.q-about"); // questions about a player: whose answer counts
  const timebar = h("div.timebar", { dataset: { timebar: "" } }, h("i"));
  const qnum = h("span.q-num", { dataset: { timenum: "" } });
  let head = header(s0, qnum);
  const endSlot = h("div.end-slot"); // host: save and leave the match from any moment
  const el = h("div.screen.question", { style: { "--cc": q.category.color } },
    head,
    h("p.q-cat", q.category.icon, " ", q.category.name, q.tiebreak ? " · Desempate" : ""),
    prompt, hint, q.image ? h("img.q-image", { src: q.image, alt: "" }) : null, timebar, result, canvas, status, endSlot);
  let mod = null;
  let loading = false;
  let locked = false;
  let revealed = false;

  async function ensureModule() {
    if (mod || loading) return;
    loading = true;
    try {
      const m = await loadType(q.type, "phone", info.types);
      mod = m.renderPhone(canvas, state.question, {
        h, fmt, snap, avatar, OPTION_COLORS, OPTION_LETTERS, me: state.me, mapsKey: info.mapsKey,
        submit: (value) => net.send({ t: "answer", value }),
        unavailable: (reason) => net.send({ t: "unavailable", reason }),
      });
    } catch (err) {
      console.error(err);
      canvas.replaceChildren(h("p.notice", "Este móvil no puede mostrar este tipo de pregunta. No te cuenta."));
      net.send({ t: "unavailable", reason: "módulo" });
      mod = { lock() {}, reveal() {}, destroy() {} };
    }
    loading = false;
    update(state);
  }

  function resultBanner(s) {
    const r = s.reveal?.results?.[s.me.id];
    if (!r) return h("p.res.res-none", s.participant ? "Sin respuesta" : "No participabas en esta pregunta");
    const subject = s.reveal.subject ? playerById(s.reveal.subject) : null;
    if (s.reveal.void && s.reveal.subject !== s.me.id) {
      return h("p.res.res-none", "Pregunta anulada: ", subject ? nameTag(subject) : "el jugador", " no eligió");
    }
    if (r.exempt) return h("p.res.res-none", "Esta pregunta no te cuenta");
    if (s.reveal.subject === s.me.id) { // the question was about me: points for each friend who knew me
      const total = r.points + r.bonus;
      return h("div", h(total >= 0 ? "p.res.res-good" : "p.res.res-bad", `${total >= 0 ? "+" : "−"}${Math.abs(total)} puntos`),
        r.detail ? h("p.res-detail", r.detail) : null,
        r.closed ? h("p.res-extra.star", `★ ¡Cierras ${r.closed}! +100`) : null,
        r.doubled ? h("p.res-extra", "x2 ¡Puntos dobles!") : null,
        r.duel ? h("p.res-extra", r.duel) : null);
    }
    const lines = [];
    if (r.closed) lines.push(h("p.res-extra.star", `★ ¡Cierras ${r.closed}! +100`));
    if (r.doubled) lines.push(h("p.res-extra", "x2 ¡Puntos dobles!"));
    if (r.duel) lines.push(h("p.res-extra", r.duel));
    if (r.detail) lines.push(h("p.res-detail", r.detail));
    return h("div", r.correct
      ? h("p.res.res-good", q.tiebreak ? "✓ ¡Correcto!" : `✓ ¡Correcto! +${r.points}`, r.fastest && !q.tiebreak ? h("small", " ⚡ el más rápido") : null)
      : h("p.res.res-bad", r.answered ? "✗ Fallaste" : "⏱ Se acabó el tiempo"), lines);
  }

  function update(s) {
    if (!s.question) return;
    const newHead = header(s, qnum);
    head.replaceWith(newHead);
    head = newHead;
    fill(endSlot, q.tiebreak ? null : hostEnd(s));
    el.classList.toggle("is-reading", s.phase === "reading");
    const subject = s.question.subject ? playerById(s.question.subject) : null;
    const isSubject = s.question.subject === s.me.id;
    if (s.phase === "reading") {
      setTimer(() => [s.question.openAt - s.question.read, s.question.openAt]);
      if (subject) fill(hint, isSubject ? "🎯 Pregunta sobre ti" : h("span", "🎯 Pregunta sobre ", nameTag(subject)));
      fill(status, h("p.hint.center", "¡Atento! Ya casi…"));
      return;
    }
    if (s.phase === "answering") setTimer(() => [s.question.openAt, s.question.deadline]);
    if (s.phase === "reveal") { setTimer(null); timebar.hidden = true; qnum.textContent = ""; }
    if (!s.participant) {
      canvas.hidden = true;
      fill(status, h("p.notice", q.tiebreak ? "Desempate: mira la tele" : "Te unes en la siguiente pregunta"));
    } else if (s.exempt && s.phase === "answering") {
      fill(status, h("p.notice", "Esta pregunta no te cuenta"));
    } else if (subject && !isSubject && s.phase === "answering" && s.question.stage === "subject") {
      canvas.hidden = true; // the subject picks first; the options open for me afterwards
      fill(status, h("p.notice", "⏳ ", nameTag(subject), " está eligiendo en secreto…"));
    } else {
      canvas.hidden = false;
      ensureModule();
      if (mod && s.myAnswer && !locked) {
        locked = true;
        mod.lock(s.myAnswer.display);
      }
      let sent = null;
      if (s.myAnswer && s.phase === "answering") {
        sent = h("p.sent", isSubject ? "🔒 Elegido. Ahora adivinan los demás" : "✓ Respuesta enviada");
      }
      fill(status, sent);
    }
    if (subject && s.phase !== "reveal") {
      fill(hint, isSubject
        ? (s.question.stage === "subject" ? "🎯 Pregunta sobre ti: elige lo que de verdad prefieres" : "🎯 Pregunta sobre ti")
        : h("span", "🎯 ¿Qué habrá elegido ", nameTag(subject), "?"));
    } else fill(hint);
    if (s.phase === "reveal" && s.reveal) {
      if (mod && !revealed) { revealed = true; mod.reveal(s.reveal, s.reveal.results?.[s.me.id]); }
      fill(result, resultBanner(s), s.reveal.explanation ? h("p.explain", "💡 ", s.reveal.explanation) : null, hostBar(s));
    }
  }
  return { el, update, destroy() { mod?.destroy?.(); } };
}

// ----- board ----------------------------------------------------------------------------------
function boardScreen() {
  const el = h("div.screen.board");
  return {
    el,
    update(s) {
      const texts = s.myMoves.flatMap((m) => m.texts);
      const steps = s.myMoves[0]?.path.length || 0;
      const spaceName = { star: "una estrella ★", event: "un evento 🎲", duel: "un duelo ⚔️", start: "la salida", normal: "una casilla normal" }[s.mySpace] || "";
      fill(el, header(s), h("div.center-msg",
        h("p.big", steps ? `${s.myMoves[0].back ? "Retrocedes" : "Avanzas"} ${steps} ${steps === 1 ? "casilla" : "casillas"}` : "Esta vez no avanzas"),
        steps ? h("p", `Caes en ${spaceName}`) : null,
        texts.map((t) => h("p.res-extra", t)),
        h("p.hint", "Mira la tele 📺")), hostBar(s), hostEnd(s));
    },
  };
}

// ----- tie-break ---------------------------------------------------------------------------------
function tiebreakScreen() {
  const el = h("div.screen");
  return {
    el,
    update(s) {
      const inIt = s.tiebreakPlayers.includes(s.me.id);
      const names = s.tiebreakPlayers.map(playerById).filter(Boolean);
      fill(el, header(s), h("div.center-msg",
        h("p.big", inIt ? "¡Desempate!" : "Desempate"),
        h("p", inIt ? "Prepárate: gana quien acierte antes o se acerque más." : "Entre ", names.map((p, i) => [i ? " y " : "", nameTag(p)]))),
        hostBar(s, "Empezar ya ▸"));
    },
  };
}

// ----- finished ----------------------------------------------------------------------------------
function finishedScreen() {
  const el = h("div.screen.finished");
  return {
    el,
    update(s) {
      const pos = s.ranking.indexOf(s.me.id) + 1;
      const won = s.winners.includes(s.me.id);
      const winners = s.winners.map(playerById).filter(Boolean);
      fill(el, header(s), h("div.center-msg",
        h("p.big", won ? "🏆 ¡Has ganado!" : `Quedas ${pos}º`),
        !won && winners.length ? h("p", "Gana ", winners.map((p, i) => [i ? " y " : "", nameTag(p)])) : null,
        h("p.hint", `${s.me.correct} aciertos de ${s.me.asked} preguntas · ${fmt(s.me.points)} puntos`)),
        s.me.host
          ? h("button.btn.primary.block.big", { type: "button", onclick: () => net.send({ t: "lobby" }) }, "Volver al lobby")
          : h("p.waiting", "El anfitrión decidirá si echáis otra"));
    },
  };
}
