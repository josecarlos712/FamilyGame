// Category-choice mechanics (wheel, coin, rival, own pick): shared by the TV and the phones.
// Animations are driven by the server clock relative to choice.spinAt / choice.revealUntil, so a
// screen that connects mid-spin shows the right moment, and they are keyed by spinAt so the
// re-renders that come with every state never restart them.
import { h, fill, nameTag, serverNow } from "./ui.js";

const SVG = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...kids);
  return el;
};

export const MECHANICS = {
  ruleta: { icon: "🎡", name: "Ruleta" },
  moneda: { icon: "💰", name: "Cara o cruz" },
  rival: { icon: "😈", name: "Amigo de tus enemigos" },
  eleccion: { icon: "🃏", name: "Elección propia" },
};

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const easeOut = (p, k = 4) => 1 - Math.pow(1 - p, k);
const easeInOut = (p) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
const clamp01 = (x) => Math.max(0, Math.min(1, x));

/** Choice object from the state; older servers without `choice` fall back to a plain pick. */
export function choiceOf(s) {
  return s.choice || {
    mechanic: "eleccion", chooserId: s.chooserId, actorId: s.chooserId, offered: s.offered,
    introUntil: 0, spinAt: null, revealUntil: null, result: null, outcome: null, stats: null,
  };
}

/** Intro banner: icon, title and one-line rule. `playerById` resolves names. */
export function introBanner(choice, playerById) {
  const m = MECHANICS[choice.mechanic] || MECHANICS.eleccion;
  const actor = playerById(choice.actorId);
  const chooser = playerById(choice.chooserId);
  const rule = {
    ruleta: ["La suerte decide"],
    moneda: ["Cara: tu mejor categoría · Cruz: tu peor"],
    rival: [actor ? nameTag(actor) : "Un rival", " elige por ", chooser ? nameTag(chooser) : "ti"],
    eleccion: ["Elige una de tres"],
  }[choice.mechanic] || [""];
  return h("div.mech-intro", h("span.mech-icon", m.icon), h("p.mech-title", m.name), h("p.mech-rule", ...rule));
}

function resultBanner(cat) {
  return h("div.choice-result", { style: { "--cc": cat.color } }, h("span.cr-icon", cat.icon), h("span.cr-name", cat.name));
}

// ----- wheel ---------------------------------------------------------------------------------
function buildWheel(offered, catById) {
  const n = offered.length;
  const a = 360 / n;
  const pt = (deg, r) => {
    const t = (deg * Math.PI) / 180;
    return [(r * Math.sin(t)).toFixed(3), (-r * Math.cos(t)).toFixed(3)];
  };
  const group = svg("g");
  offered.forEach((id, i) => {
    const c = catById(id) || { color: "#888", icon: "?" };
    let slice;
    if (n === 1) slice = svg("circle", { r: 96 });
    else {
      const [x1, y1] = pt(i * a, 96);
      const [x2, y2] = pt((i + 1) * a, 96);
      slice = svg("path", { d: `M0 0 L${x1} ${y1} A96 96 0 ${a > 180 ? 1 : 0} 1 ${x2} ${y2} Z` });
    }
    slice.setAttribute("fill", c.color);
    slice.setAttribute("class", "wheel-slice");
    slice.dataset.id = id;
    const [tx, ty] = pt((i + 0.5) * a, n > 8 ? 74 : 66);
    const label = svg("text", {
      x: tx, y: ty, "text-anchor": "middle", "dominant-baseline": "central",
      "font-size": n > 10 ? 11 : n > 6 ? 15 : 22, transform: `rotate(${(i + 0.5) * a} ${tx} ${ty})`,
    });
    label.textContent = c.icon;
    group.append(slice, label);
  });
  const root = svg("svg", { viewBox: "-104 -112 208 216", class: "wheel-svg" },
    svg("circle", { r: 101, class: "wheel-rim" }), group,
    svg("circle", { r: 9, class: "wheel-hub" }),
    svg("path", { d: "M-9 -110 L9 -110 L0 -90 Z", class: "wheel-pointer" }));
  return { root, group };
}

// ----- coin ----------------------------------------------------------------------------------
function buildCoin(offered, catById, stats) {
  const face = (id, label, key, cls) => {
    const c = catById(id) || { icon: "?", name: "", color: "#888" };
    const pct = stats?.[key] ?? null;
    return h(`div.coin-face.${cls}`,
      h("span.cf-label", label), h("span.cf-icon", c.icon), h("span.cf-name", c.name),
      pct === null ? null : h("span.cf-stat", `${Math.round(pct * 100)}% de acierto`));
  };
  const coin = h("div.coin", face(offered[0], "Cara · tu mejor", "cara", "front"), face(offered[1], "Cruz · tu peor", "cruz", "back"));
  const toss = h("div.coin-toss", coin);
  return { root: h("div.coin-wrap", toss), toss, coin };
}

/**
 * Stage for one choosing phase. Shows the intro banner until introUntil, then the mechanic.
 * opts: { catById, playerById, size: "big"|"small", play(name) (TV only),
 *         onSpin() (phone of the actor: makes ruleta/moneda tappable),
 *         body(choice) -> element for rival/eleccion }
 * Returns { el, update(choice), destroy() }.
 */
export function choiceStage(opts) {
  const intro = h("div.choice-intro");
  const body = h("div.choice-body");
  const el = h(`div.choice-stage.is-${opts.size || "big"}`, intro, body);
  let cur = null;
  let introSig = "";
  let bodySig = "";
  let dead = false;
  let tapped = false;
  let anim = null; // { tick(now) } for the current wheel/coin

  function buildBody(c) {
    anim = null;
    const cats = opts.catById;
    if (c.mechanic === "ruleta") {
      const { root, group } = buildWheel(c.offered, cats);
      const n = c.offered.length;
      const a = 360 / n;
      let rot = 0;
      let lastIdx = -1;
      let landed = false;
      const res = h("div.choice-slot");
      const hint = h("p.choice-hint", "Toca para girar");
      hint.hidden = !opts.onSpin;
      anim = {
        tick(now) {
          let r;
          if (c.spinAt && c.revealUntil) {
            const idx = Math.max(0, c.offered.indexOf(c.result));
            const finalR = 360 * 6 + (360 - (idx + 0.5) * a);
            const p = reduced() ? 1 : clamp01((now - c.spinAt) / (c.revealUntil - c.spinAt));
            r = finalR * easeOut(p, 3.2);
            hint.hidden = true;
            if (p >= 1 && !landed) {
              landed = true;
              root.classList.add("is-landed");
              for (const s of group.querySelectorAll(".wheel-slice")) s.classList.toggle("is-win", s.dataset.id === c.result);
              const cat = cats(c.result);
              if (cat) fill(res, resultBanner(cat));
            }
            const slot = Math.floor((((-r % 360) + 360) % 360) / a);
            if (p < 1 && slot !== lastIdx && lastIdx !== -1) opts.play?.("ruleta");
            lastIdx = slot;
          } else r = 4 * Math.sin(now * 1.4); // idle wobble
          if (r !== rot) { rot = r; group.setAttribute("transform", `rotate(${r.toFixed(2)})`); }
        },
      };
      fill(body, root, hint, res);
      if (opts.onSpin) root.classList.add("is-tappable");
    } else if (c.mechanic === "moneda") {
      const { root, toss, coin } = buildCoin(c.offered, cats, c.stats);
      const res = h("div.choice-slot");
      const hint = h("p.choice-hint", "Toca para lanzar");
      hint.hidden = !opts.onSpin;
      let sounded = false;
      let landed = false;
      anim = {
        tick(now) {
          if (c.spinAt && c.revealUntil) {
            hint.hidden = true;
            const total = c.revealUntil - c.spinAt;
            const flight = Math.min(2.6, total * 0.65);
            const t = reduced() ? total : now - c.spinAt;
            if (!sounded && t < 0.5) { sounded = true; opts.play?.("moneda"); }
            const finalX = 360 * 7 + (c.outcome === "cruz" ? 180 : 0);
            let x; let y = 0; let scale = 1;
            if (t < flight) {
              const p = clamp01(t / flight);
              x = finalX * easeOut(p, 2);
              y = -4 * p * (1 - p) * 150;
              scale = 1 + 0.35 * Math.sin(Math.PI * p);
            } else {
              x = finalX;
              scale = 1 + 0.55 * easeInOut(clamp01((t - flight) / Math.max(0.1, total - flight)));
            }
            coin.style.transform = `rotateX(${x.toFixed(1)}deg)`;
            toss.style.transform = `translateY(${y.toFixed(1)}px) scale(${scale.toFixed(3)})`;
            if (t >= total && !landed) {
              landed = true;
              root.classList.add("is-landed", c.outcome === "cruz" ? "won-cruz" : "won-cara");
              const cat = cats(c.result);
              if (cat) fill(res, resultBanner(cat));
            }
          } else {
            coin.style.transform = `rotateX(${(10 * Math.sin(now * 1.6)).toFixed(1)}deg)`;
            toss.style.transform = `translateY(${(6 * Math.sin(now * 2)).toFixed(1)}px)`;
          }
        },
      };
      fill(body, root, hint, res);
      if (opts.onSpin) root.classList.add("is-tappable");
    } else {
      fill(body, opts.body ? opts.body(c) : null);
      // spec for rival / eleccion: highlight the picked category once there is a result
      if (c.result) for (const b of body.querySelectorAll("[data-cat]")) b.classList.toggle("is-picked", b.dataset.cat === c.result);
    }
  }

  const tap = () => {
    if (!opts.onSpin || tapped || !cur || cur.spinAt || serverNow() < cur.introUntil) return;
    if (cur.mechanic !== "ruleta" && cur.mechanic !== "moneda") return;
    tapped = true;
    el.classList.add("is-tapped");
    opts.onSpin();
  };
  body.addEventListener("click", tap);

  function frame() {
    if (dead || (!el.isConnected && el._seen)) return;
    if (el.isConnected) el._seen = true;
    if (cur) {
      const now = serverNow();
      const introOn = now < cur.introUntil;
      intro.hidden = !introOn;
      body.hidden = introOn;
      if (!introOn) anim?.tick(now);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  return {
    el,
    update(c) {
      cur = c;
      const isig = `${c.mechanic}:${c.introUntil}:${c.chooserId}:${c.actorId}`;
      if (isig !== introSig) { introSig = isig; fill(intro, introBanner(c, opts.playerById)); }
      const bsig = `${isig}:${c.offered.join(",")}:${c.spinAt}:${c.result}:${c.outcome}`;
      if (bsig !== bodySig) { bodySig = bsig; if (!c.spinAt) tapped = false; el.classList.toggle("is-tapped", tapped); buildBody(c); }
    },
    destroy() { dead = true; },
  };
}
