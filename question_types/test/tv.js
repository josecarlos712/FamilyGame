// TV side of the multiple-choice question.
export function renderTV(canvas, q, ctx) {
  const { h, avatar, OPTION_COLORS, OPTION_LETTERS } = ctx;
  const options = q.data.options;
  const cells = options.map((text, i) =>
    h("div.qt-test-opt", { style: { "--oc": OPTION_COLORS[i] } },
      h("span.opt-letter", OPTION_LETTERS[i]),
      h("span.qt-test-text", text),
      h("span.qt-test-voters")));
  const grid = h("div.qt-test-grid", { dataset: { n: options.length } }, cells);
  canvas.append(grid);

  return {
    reveal(reveal, players) {
      const right = reveal.solution.index;
      cells.forEach((cell, i) => cell.classList.add(i === right ? "is-right" : "is-wrong"));
      for (const [pid, shown] of Object.entries(reveal.answers)) {
        const player = players.find((p) => p.id === pid);
        if (player && cells[shown]) cells[shown].querySelector(".qt-test-voters").append(avatar(player, 54));
      }
    },
    destroy() {},
  };
}
