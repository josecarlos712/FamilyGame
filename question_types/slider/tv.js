// TV side of the slider question: a big scale; at reveal, the answer and everyone's guess.
export function renderTV(canvas, q, ctx) {
  const { h, fmt, avatar } = ctx;
  const { min, max, unit } = q.data;
  const pct = (v) => ((v - min) / (max - min)) * 100;
  const track = h("div.qt-sl-track");
  const marks = h("div.qt-sl-marks");
  for (let i = 0; i <= 4; i++) marks.append(h("span", fmt(min + ((max - min) * i) / 4)));
  const pins = h("div.qt-sl-pins");
  canvas.append(h("div.qt-sl", h("p.qt-sl-hint", "Elegid el número en el móvil", unit ? ` (${unit})` : ""), pins, track, marks));

  return {
    reveal(reveal, players) {
      const s = reveal.solution;
      track.append(
        h("i.qt-sl-band", { style: { left: pct(s.low) + "%", width: Math.max(0.6, pct(s.high) - pct(s.low)) + "%" } }),
        h("i.qt-sl-answer", { style: { left: pct(s.value) + "%" } }, h("b", s.text)));
      const entries = Object.entries(reveal.answers).sort((a, b) => a[1] - b[1]);
      entries.forEach(([pid, value], i) => {
        const player = players.find((p) => p.id === pid);
        if (!player) return;
        pins.append(h("div.qt-sl-pin", { style: { left: pct(value) + "%", "--row": i % 3, "--c": player.color } },
          avatar(player, 52), h("small", fmt(value))));
      });
    },
    destroy() {},
  };
}
