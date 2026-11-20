// Party circuit on the TV: 28 tiles around a 10 x 6 rectangle, tokens that walk along it.
import { h, avatar, SPACE_GLYPH, SPACE_LABEL } from "./ui.js";

export const STAGE_W = 1920;
export const STAGE_H = 1080;
const COLS = 10, ROWS = 6, TW = 172, TH = 160, GAP = 8;
const X0 = (STAGE_W - (COLS * TW + (COLS - 1) * GAP)) / 2;
const Y0 = (STAGE_H - (ROWS * TH + (ROWS - 1) * GAP)) / 2;
export const CENTER = {
  left: X0 + TW + GAP * 2, top: Y0 + TH + GAP * 2,
  width: (COLS - 2) * TW + (COLS - 3) * GAP - GAP * 2,
  height: (ROWS - 2) * TH + (ROWS - 3) * GAP - GAP * 2,
};

/** Grid cell (col,row) of space i, clockwise from the top-left corner. */
function cell(i, n) {
  const top = COLS, right = ROWS - 1, bottom = COLS - 1;
  if (n !== 28) {
    // generic fallback: spread on the perimeter proportionally
    i = Math.round((i / n) * 28);
  }
  if (i < top) return [i, 0];
  if (i < top + right) return [COLS - 1, i - top + 1];
  if (i < top + right + bottom) return [COLS - 2 - (i - top - right), ROWS - 1];
  return [0, ROWS - 2 - (i - top - right - bottom)];
}

export function tileXY(i, n) {
  const [c, r] = cell(i, n);
  return { x: X0 + c * (TW + GAP), y: Y0 + r * (TH + GAP) };
}

const SLOT = [[10, 10], [62, 10], [114, 10], [10, 84], [62, 84], [114, 84]];

export class BoardView {
  constructor(spaces) {
    this.spaces = spaces;
    this.el = h("div.board");
    this.tokens = new Map();
    this.shown = new Map();
    this.animating = false;
    spaces.forEach((type, i) => {
      const { x, y } = tileXY(i, spaces.length);
      this.el.append(h(`div.tile.t-${type}`, { style: { left: x + "px", top: y + "px", width: TW + "px", height: TH + "px" } },
        h("span.tile-glyph", SPACE_GLYPH[type] || ""),
        h("span.tile-label", SPACE_LABEL[type] || "")));
    });
    this.tokenLayer = h("div.tokens");
    this.el.append(this.tokenLayer);
  }

  /** Place tokens at ``positions`` (pid -> index), stacking players who share a tile. */
  layout(players) {
    const byTile = new Map();
    for (const p of players) {
      const pos = this.shown.has(p.id) ? this.shown.get(p.id) : p.position;
      if (!byTile.has(pos)) byTile.set(pos, []);
      byTile.get(pos).push(p);
    }
    const alive = new Set(players.map((p) => p.id));
    for (const [pid, el] of this.tokens) if (!alive.has(pid)) { el.remove(); this.tokens.delete(pid); }
    for (const [pos, group] of byTile) {
      const { x, y } = tileXY(pos, this.spaces.length);
      group.forEach((p, k) => {
        let tok = this.tokens.get(p.id);
        if (!tok) {
          tok = h("div.token");
          this.tokens.set(p.id, tok);
          this.tokenLayer.append(tok);
        }
        tok.replaceChildren(avatar(p, 50));
        tok.classList.toggle("is-off", !p.connected);
        const [dx, dy] = SLOT[k % SLOT.length];
        tok.style.transform = `translate(${x + dx}px, ${y + dy}px)`;
      });
    }
  }

  /** Walk tokens along the server's moves; calls onText(move) as each one lands. */
  async play(moves, players, onText) {
    if (this.animating) return;
    this.animating = true;
    for (const m of moves) if (!this.shown.has(m.player)) this.shown.set(m.player, m.from);
    const seen = new Set();
    const first = [], rest = [];
    for (const m of moves) (seen.has(m.player) ? rest : first).push(m), seen.add(m.player);
    const walk = async (m) => {
      for (const pos of m.path) {
        this.shown.set(m.player, pos);
        this.layout(players());
        this.tokens.get(m.player)?.classList.add("is-hop");
        await sleep(m.jump ? 500 : 300);
        this.tokens.get(m.player)?.classList.remove("is-hop");
      }
      onText(m);
    };
    await Promise.all(first.map(walk));
    for (const m of rest) await walk(m);
    this.shown.clear();
    this.layout(players());
    this.animating = false;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
