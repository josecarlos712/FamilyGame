// Shared TV screen: lobby, board, questions, tie-break and podium.
import { connect } from "./net.js";
import {
  h, fill, fmt, avatar, nameTag, secondsLeft, serverNow, loadType, snap, modeText,
  OPTION_COLORS, OPTION_LETTERS,
} from "./ui.js";
import { BoardView, CENTER, STAGE_W, STAGE_H } from "./board.js";

const stage = document.getElementById("stage");
const toasts = h("div.toasts");
document.body.append(toasts);
let info = { types: {}, icons: [] };
let state = null;
let screen = null;
let screenKey = "";
let lastLogId = null;

// ----- scaling: the stage is always 1920x1080, scaled to the TV ------------------------
function fit() {
  const s = Math.min(innerWidth / STAGE_W, innerHeight / STAGE_H);
  stage.style.transform = `translate(${(innerWidth - STAGE_W * s) / 2}px, ${(innerHeight - STAGE_H * s) / 2}px) scale(${s})`;
}
addEventListener("resize", fit);
fit();

connect("/ws/tv", {
  onStatus: (ok) => document.getElementById("offline").hidden = ok,
  onMessage(msg) {
    if (msg.t === "welcome") info = msg;
    if (msg.t === "state") render(msg.state);
  },
});

function playerById(id) { return state?.players.find((p) => p.id === id); }
function catById(id) { return state?.categories.find((c) => c.id === id); }

function keyFor(s) {
  if (s.phase === "lobby") return "lobby";
  if (s.phase === "finished") return "finished";
  if (s.phase === "tiebreak") return "tiebreak:" + s.tiebreakPlayers.join(",");
  if (["reading", "answering", "reveal"].includes(s.phase)) return "q:" + s.question.key + ":" + s.question.number + ":" + s.question.tiebreak;
  return "board";
}

function render(s) {
  state = s;
  const key = keyFor(s);
  if (key !== screenKey) {
    screen?.destroy?.();
    screenKey = key;
    const make = { lobby: lobbyScreen, finished: finishedScreen, board: boardScreen }[key.split(":")[0]]
      || (key.startsWith("q:") ? questionScreen : tiebreakScreen);
    screen = make();
    fill(stage, screen.el);
  }
  screen.update(s);
  showToasts(s.log);
}

// ----- toasts -----------------------------------------------------------------------
function showToasts(log) {
  if (lastLogId === null) { lastLogId = log.at(-1)?.id ?? 0; return; }
  for (const entry of log) {
    if (entry.id <= lastLogId) continue;
    lastLogId = entry.id;
    if (["choose", "event"].includes(entry.kind)) continue; // already shown on screen
    const p = entry.player && playerById(entry.player);
    const t = h(`div.toast.k-${entry.kind}`, p ? avatar(p, 40) : null, h("span", entry.text));
    toasts.append(t);
    setTimeout(() => t.classList.add("is-out"), 4200);
    setTimeout(() => t.remove(), 4700);
  }
}

// ----- timers (one rAF loop for the whole page) --------------------------------------------
const timers = new Set();
function timer(barEl, numEl, getRange) {
  const t = { barEl, numEl, getRange };
  timers.add(t);
  return () => timers.delete(t);
}
(function loop() {
  for (const t of timers) {
    const range = t.getRange();
    if (!range) continue;
    const [start, end] = range;
    const left = secondsLeft(end);
    const frac = Math.max(0, Math.min(1, left / Math.max(0.1, end - start)));
    if (t.barEl) {
      t.barEl.firstChild.style.transform = `scaleX(${frac})`;
      t.barEl.classList.toggle("is-low", left < 4);
    }
    if (t.numEl) t.numEl.textContent = Math.ceil(left);
  }
  requestAnimationFrame(loop);
})();

// ----- lobby ------------------------------------------------------------------------
function lobbyScreen() {
  const seats = h("div.seats");
  const issues = h("div.issues");
  const cats = h("div.lobby-cats");
  const mode = h("span.chip.mode-chip");
  const el = h("div.lobby",
    h("div.lobby-brand",
      h("div.logo", h("span.logo-dice", "🎲"), h("span", "Family", h("b", "Game"))),
      h("p.lobby-tag", "Todos responden a la vez desde su móvil")),
    h("div.join-card",
      h("img.qr", { src: "/qr.svg", alt: "Código QR para entrar" }),
      h("div", h("p.join-title", "Escanea para jugar"), h("p.join-url", info.joinUrl || location.origin), mode)),
    seats, cats, issues);

  return {
    el,
    update(s) {
      fill(seats, Array.from({ length: s.maxPlayers }, (_, i) => {
        const p = s.players[i];
        if (!p) return h("div.seat.is-empty", h("span.seat-ring"), h("span.seat-name", "Libre"));
        return h("div.seat", { style: { "--c": p.color } },
          avatar(p, 132), h("span.seat-name", nameTag(p)),
          p.host ? h("span.seat-badge", "👑 Anfitrión") : null,
          !p.connected ? h("span.seat-badge.is-off", "Desconectado") : null);
      }));
      mode.textContent = modeText(s.settings);
      const enabled = s.categories.filter((c) => c.enabled);
      const total = enabled.reduce((n, c) => n + c.count, 0);
      fill(cats,
        h("p.cats-title", `${enabled.length} categorías · ${total} preguntas`),
        h("div.cat-strip", enabled.map((c) => h("span.cat-chip", { style: { "--cc": c.color } }, c.icon, " ", c.name, h("small", c.count)))));
      const problems = [];
      for (const err of info.typeErrors || []) problems.push(["⚠️", err]);
      for (const c of s.categories) {
        if (c.errorCount) problems.push(["📄", `${c.file}: ${c.errorCount} ${c.errorCount === 1 ? "error" : "errores"} — ${c.errors[0]}`]);
        else if (!c.playable && c.unavailable) problems.push(["📵", `${c.icon} ${c.name}: no disponible (${c.unavailableReasons.join(", ")})`]);
        else if (c.unavailable) problems.push(["📵", `${c.icon} ${c.name}: ${c.unavailable} preguntas no disponibles (${c.unavailableReasons.join(", ")})`]);
      }
      issues.hidden = !problems.length;
      fill(issues, problems.slice(0, 5).map(([icon, text]) => h("p", h("span", icon), " ", text)),
        problems.length > 5 ? h("p.more", `y ${problems.length - 5} avisos más`) : null);
    },
  };
}

// ----- ranking (used on the board and on the podium) ---------------------------------------
function rankRows(s, { compact = false } = {}) {
  const order = s.ranking.map(playerById).filter(Boolean);
  return order.map((p, i) => {
    const badges = [];
    if (p.onStar) badges.push(h("span.badge.b-star", { title: "En una estrella" }, "★"));
    if (p.double) badges.push(h("span.badge.b-double", "x2"));
    if (!p.connected) badges.push(h("span.badge.b-off", "off"));
    const closed = s.settings.mode === "categories" || p.closed.length
      ? h("span.closed", p.closed.map((cid) => { const c = catById(cid); return h("span.closed-dot", { style: { "--cc": c?.color || "#888" }, title: c?.name }, c?.icon || "•"); }))
      : null;
    return h("div.rank-row", { style: { "--c": p.color }, class: s.chooserId === p.id ? "is-chooser" : "" },
      h("span.rank-pos", i + 1), avatar(p, compact ? 48 : 56),
      h("span.rank-name", nameTag(p), badges, closed),
      h("span.rank-pts", fmt(p.points)));
  });
}

// ----- board ----------------------------------------------------------------------------
function boardScreen() {
  let board = null;
  let boardSig = "";
  let animatedFor = null;
  const rank = h("div.rank");
  const panel = h("div.panel");
  const round = h("p.round-info");
  const center = h("div.center", { style: { left: CENTER.left + "px", top: CENTER.top + "px", width: CENTER.width + "px", height: CENTER.height + "px" } },
    h("div.center-left", round, rank), panel);
  const el = h("div.boardview");

  function roundText(s) {
    const r = s.round;
    return r.rounds ? `Ronda ${r.round} de ${r.rounds}` : `Ronda ${r.round} · ${modeText(s.settings)}`;
  }

  return {
    el,
    update(s) {
      const sig = s.board.join(",");
      if (sig !== boardSig) {
        boardSig = sig;
        board = new BoardView(s.board);
        fill(el, board.el, center);
      }
      round.textContent = roundText(s);
      fill(rank, rankRows(s, { compact: s.players.length > 5 }));
      if (s.phase === "choosing") {
        if (!board.animating) board.layout(s.players);
        const chooser = playerById(s.chooserId);
        const num = h("span.big-timer");
        const bar = h("div.timebar", h("i"));
        fill(panel,
          chooser
            ? h("div.choose-head", avatar(chooser, 96), h("div", h("p.kicker", "Elige categoría"), h("p.choose-name", nameTag(chooser))), num)
            : h("div.choose-head", h("p.choose-name", "Categoría al azar…"), num),
          bar,
          h("div.offer", s.offered.map((id) => { const c = catById(id); return c && h("span.cat-chip.big", { style: { "--cc": c.color } }, c.icon, " ", c.name); })));
        timers.clear();
        timer(bar, num, () => [s.deadline - (chooser ? s.chooseTime : 1.5), s.deadline]);
      } else if (s.phase === "board") {
        const qn = s.round.question;
        if (animatedFor !== qn) {
          animatedFor = qn;
          timers.clear();
          const list = h("div.moves");
          fill(panel, h("p.kicker", "¡A mover fichas!"), list);
          if (!s.moves.length) list.append(h("p.move-none", "Nadie avanza esta vez"));
          board.play(s.moves, () => state.players, (m) => {
            const p = playerById(m.player);
            if (!p || (!m.texts.length && m.jump)) return;
            const text = m.texts.length ? m.texts.join(" · ") : `Avanza ${m.path.length} ${m.path.length === 1 ? "casilla" : "casillas"}`;
            list.append(h("div.move", { style: { "--c": p.color } }, avatar(p, 48), h("span", nameTag(p), " ", text)));
          });
        }
      }
    },
    destroy() { timers.clear(); },
  };
}

// ----- question -------------------------------------------------------------------------
function questionScreen() {
  let mod = null;
  let loading = false;
  let revealed = false;
  const s0 = state;
  const q = s0.question;
  const cat = q.category;
  const num = h("span.q-timer");
  const bar = h("div.timebar.q-bar", h("i"));
  const canvas = h("div.q-canvas");
  const side = h("aside.q-side");
  const explain = h("p.q-explain");
  const prompt = h("h1.q-prompt", q.prompt);
  const meta = h("span.q-meta", q.tiebreak ? "⚡ Desempate" : `Pregunta ${q.number}` + (s0.round.rounds ? ` · Ronda ${s0.round.round}/${s0.round.rounds}` : ""));
  const pts = h("span.q-points", q.tiebreak ? "" : `${q.points} pts`);
  const main = h("main.q-main", prompt, q.image ? h("img.q-image", { src: q.image, alt: "" }) : null, canvas, explain);
  const el = h("div.qscreen", { style: { "--cc": cat.color } },
    h("header.q-head", h("span.cat-chip.big", { style: { "--cc": cat.color } }, cat.icon, " ", cat.name), meta, pts, num),
    bar, main, side);

  async function ensureModule(s) {
    if (mod || loading) return;
    loading = true;
    try {
      const m = await loadType(q.type, "tv", info.types);
      mod = m.renderTV(canvas, state.question, ctx());
    } catch (err) {
      console.error(err);
      canvas.append(h("p.q-error", "No se pudo cargar este tipo de pregunta en la tele"));
      mod = { reveal() {}, destroy() {} };
    }
    loading = false;
    update(state);
  }

  function ctx() {
    return { h, fmt, snap, avatar, OPTION_COLORS, OPTION_LETTERS, mapsKey: info.mapsKey, players: state.players };
  }

  function sideRows(s) {
    const res = s.reveal?.results || {};
    const ids = s.question.tiebreak ? s.tiebreakPlayers : s.ranking;
    return ids.map(playerById).filter(Boolean).map((p) => {
      let status;
      const r = res[p.id];
      if (r) {
        if (r.exempt) status = h("span.st.st-skip", "—");
        else if (r.correct) status = h("span.st.st-good", q.tiebreak ? "✓" : `+${r.points + Math.max(0, r.bonus)}`);
        else status = h("span.st.st-bad", r.answered ? "✗" : "⏱");
      } else if (!p.participant) status = h("span.st.st-skip", "espera");
      else if (p.exempt) status = h("span.st.st-skip", "sin mapa");
      else if (p.answered) status = h("span.st.st-done", "✓");
      else status = h("span.st.st-wait", h("i"), h("i"), h("i"));
      const marks = [];
      if (s.question.starPlayers.includes(p.id)) marks.push(h("span.badge.b-star", "★"));
      if (s.question.duels.some((d) => d.includes(p.id))) marks.push(h("span.badge.b-duel", "⚔"));
      if (p.double && !s.question.tiebreak) marks.push(h("span.badge.b-double", "x2"));
      return h("div.side-row", { style: { "--c": p.color }, class: r?.correct ? "is-good" : r ? "is-bad" : p.answered ? "is-done" : "" },
        avatar(p, 58), h("span.side-name", nameTag(p), marks), status);
    });
  }

  function update(s) {
    if (!s.question) return;
    el.classList.toggle("is-reading", s.phase === "reading");
    el.classList.toggle("is-reveal", s.phase === "reveal");
    fill(side, h("p.side-title", s.phase === "reveal" ? "Resultados" : "Respuestas"), sideRows(s));
    timers.clear();
    if (s.phase === "reading") timer(bar, num, () => [s.question.openAt - s.question.read, s.question.openAt]);
    if (s.phase === "answering") timer(bar, num, () => [s.question.openAt, s.question.deadline]);
    if (s.phase === "reveal") { num.textContent = ""; bar.firstChild.style.transform = "scaleX(0)"; }
    if (s.phase !== "reading") ensureModule(s);
    if (s.phase === "reveal" && mod && !revealed && s.reveal) {
      revealed = true;
      mod.reveal(s.reveal, s.players);
      if (s.reveal.explanation) explain.textContent = "💡 " + s.reveal.explanation;
    }
  }

  return { el, update, destroy() { timers.clear(); mod?.destroy?.(); } };
}

// ----- tie-break intro -------------------------------------------------------------------
function tiebreakScreen() {
  const faces = h("div.tb-faces");
  const el = h("div.tiebreak", h("p.kicker", "Hay empate"), h("h1.tb-title", "¡Desempate!"), faces,
    h("p.tb-rule", "Muerte súbita: gana quien acierte antes, o quien más se acerque"));
  return {
    el,
    update(s) {
      fill(faces, s.tiebreakPlayers.map(playerById).filter(Boolean).map((p) =>
        h("div.tb-face", avatar(p, 150), nameTag(p), h("small", `${fmt(p.points)} pts`))));
    },
  };
}

// ----- podium ---------------------------------------------------------------------------
function finishedScreen() {
  const el = h("div.finished");
  return {
    el,
    update(s) {
      const ranked = s.ranking.map(playerById).filter(Boolean);
      const winners = s.winners.map(playerById).filter(Boolean);
      const podium = [ranked[1], ranked[0], ranked[2]];
      const heights = [300, 400, 220];
      fill(el,
        h("p.kicker", "Fin de la partida"),
        h("h1.win-title", winners.length > 1 ? "¡Victoria compartida!" : "¡Tenemos ganador!"),
        h("div.podium", podium.map((p, i) => p ? h("div.step", { style: { "--c": p.color, "--hgt": heights[i] + "px" }, class: s.winners.includes(p.id) ? "is-winner" : "" },
          s.winners.includes(p.id) ? h("span.crown", "👑") : null,
          avatar(p, i === 1 ? 170 : 130), h("span.step-name", nameTag(p)),
          h("div.step-block", h("b", [2, 1, 3][i]), h("span", `${fmt(p.points)} pts`), h("small", `${p.correct}/${p.asked} aciertos`)))
          : h("div.step.is-empty"))),
        ranked.length > 3 ? h("div.rest", ranked.slice(3).map((p, i) => h("span.rest-item", `${i + 4}.`, avatar(p, 44), nameTag(p), h("small", fmt(p.points))))) : null,
        h("p.finish-hint", "El anfitrión puede volver al lobby desde su móvil"));
    },
  };
}
