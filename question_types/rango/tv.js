// TV side of the double-slider question: the correct range and each player's range as a bar.
const CRITERIA = {
  solapar: (q) => `Vale si tu rango se solapa al menos un ${q.data.minOverlap} % con el correcto`,
  contener: (q, fmt) => `Vale si tu rango contiene el correcto` + (q.data.maxWidth ? ` (ancho máx. ${fmt(q.data.maxWidth, q.data.unit)})` : ""),
  coincidir: () => "Vale si aciertas los dos extremos",
};

export function renderTV(canvas, q, ctx) {
  const { h, fmt, avatar } = ctx;
  const { min, max, unit, criterion } = q.data;
  const pct = (v) => ((v - min) / (max - min)) * 100;
  const track = h("div.qt-sl-track");
  const marks = h("div.qt-rg-marks");
  for (let i = 0; i <= 4; i++) marks.append(h("span", fmt(min + ((max - min) * i) / 4)));
  const rows = h("div.qt-rg-rows");
  canvas.append(h("div.qt-sl", h("p.qt-sl-hint", CRITERIA[criterion](q, fmt), unit ? ` · ${unit}` : ""), rows, track, marks));

  return {
    reveal(reveal, players) {
      const s = reveal.solution;
      track.append(h("i.qt-sl-band", { style: { left: pct(s.low) + "%", width: Math.max(0.6, pct(s.high) - pct(s.low)) + "%" } }));
      rows.append(h("p.qt-rg-solution", s.text));
      for (const [pid, [low, high]] of Object.entries(reveal.answers)) {
        const player = players.find((p) => p.id === pid);
        const res = reveal.results[pid];
        if (!player) continue;
        rows.append(h("div.qt-rg-row", { style: { "--c": player.color } },
          avatar(player, 40),
          h("div.qt-rg-lane", h("i", { class: res?.correct ? "is-good" : "", style: { left: pct(low) + "%", width: Math.max(0.6, pct(high) - pct(low)) + "%" } })),
          h("small", `${fmt(low)} – ${fmt(high)}`)));
      }
    },
    destroy() {},
  };
}
