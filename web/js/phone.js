// Phone controller: profile, lobby (host settings), choosing, answering, results.
import { connect } from "./net.js";
import {
  h, fill, fmt, avatar, nameTag, secondsLeft, loadType, snap, modeText,
  OPTION_COLORS, OPTION_LETTERS,
} from "./ui.js";

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
      if (!msg.id && store.get("token")) store.del("token");
    } else if (msg.t === "joined") {
      myId = msg.id;
      store.set("token", msg.token);
      editing = false;
    } else if (msg.t === "state") {
      state = msg.state;
      if (state.me) myId = state.me.id;
      render();
    } else if (msg.t === "error") {
      toast(msg.msg);
    } else if (["kicked", "left", "replaced"].includes(msg.t)) {
      store.del("token");
      myId = null;
      notice = { kicked: "El anfitrión te ha sacado de la partida.", left: "Has salido de la partida.",
        replaced: "Has abierto el juego en otra pestaña o móvil." }[msg.t];
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
    const make = key.startsWith("q:") ? questionScreen : {
      loading: () => ({ el: h("div.center-msg", "Conectando…"), update() {} }),
      profile: profileScreen, lobby: lobbyScreen, choosing: choosingScreen,
      board: boardScreen, tiebreak: tiebreakScreen, finished: finishedScreen,
    }[key];
    screen = make();
    fill(app, screen.el);
    window.scrollTo(0, 0);
  }
  screen.update?.(state);
}

// ----- header ------------------------------------------------------------------------------
function header(s, extra) {
  const me = s.me;
  const rank = s.ranking.indexOf(me.id) + 1;
  return h("header.bar", { style: { "--c": me.color } },
    avatar(me, 44),
    h("div.bar-who", nameTag(me), h("small", s.phase === "lobby" ? (me.host ? "👑 Anfitrión" : "En el lobby") : `#${rank} · ${fmt(me.points)} pts`)),
    extra || null,
    soundButton(s));
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

  const full = state && !state.me && state.players.length >= state.maxPlayers;
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
          stepper("Categorías para elegir cada turno", st.categoriesPerTurn, 0, 12, 1, (v) => send({ categoriesPerTurn: v }), (v) => v === 0 ? "Todas" : v));
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
  return {
    el,
    update(s) {
      const mine = s.chooserId === s.me.id;
      const next = `${mine}:${s.offered.join(",")}:${s.chooserId}`;
      setTimer(() => [s.deadline - (s.chooserId ? s.chooseTime : 1.5), s.deadline]);
      if (next === sig) return;
      sig = next;
      const chooser = playerById(s.chooserId);
      const timebar = h("div.timebar", { dataset: { timebar: "" } }, h("i"));
      if (mine) {
        fill(el, header(s), h("h1.title", "¡Te toca elegir!"), timebar,
          h("div.cat-grid", s.offered.map((id) => {
            const c = catById(id);
            return c && h("button.cat-btn", { type: "button", style: { "--cc": c.color }, onclick: () => net.send({ t: "choose", category: id }) },
              h("span.cat-icon", c.icon), h("span", c.name));
          }), h("button.cat-btn.random", { type: "button", onclick: () => net.send({ t: "choose", category: "__random__" }) },
            h("span.cat-icon", "🎲"), h("span", "Al azar"))),
          h("p.hint.center", "Quedan ", h("b", { dataset: { timenum: "" } }), " s; si no, se elige al azar"), hostEnd(s));
      } else {
        fill(el, header(s), h("div.center-msg",
          chooser ? avatar(chooser, 96) : null,
          h("p", chooser ? h("span", nameTag(chooser), " está eligiendo categoría…") : "Eligiendo categoría al azar…"),
          timebar), hostEnd(s));
      }
    },
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
  const timebar = h("div.timebar", { dataset: { timebar: "" } }, h("i"));
  const qnum = h("span.q-num", { dataset: { timenum: "" } });
  let head = header(s0, qnum);
  const endSlot = h("div.end-slot"); // host: save and leave the match from any moment
  const el = h("div.screen.question", { style: { "--cc": q.category.color } },
    head,
    h("p.q-cat", q.category.icon, " ", q.category.name, q.tiebreak ? " · Desempate" : ""),
    prompt, q.image ? h("img.q-image", { src: q.image, alt: "" }) : null, timebar, result, canvas, status, endSlot);
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
    if (r.exempt) return h("p.res.res-none", "Esta pregunta no te cuenta");
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
    if (s.phase === "reading") {
      setTimer(() => [s.question.openAt - s.question.read, s.question.openAt]);
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
    } else {
      ensureModule();
      if (mod && s.myAnswer && !locked) {
        locked = true;
        mod.lock(s.myAnswer.display);
      }
      fill(status, s.myAnswer && s.phase === "answering" ? h("p.sent", "✓ Respuesta enviada") : null);
    }
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
        h("p.big", steps ? `Avanzas ${steps} ${steps === 1 ? "casilla" : "casillas"}` : "Esta vez no avanzas"),
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
