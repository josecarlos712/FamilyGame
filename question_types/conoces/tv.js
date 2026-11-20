// TV side of «¿Lo conoces?»: the options; at the end, the subject's pick and who guessed it.
export function renderTV(canvas, q, ctx) {
  const { h, avatar, OPTION_COLORS, OPTION_LETTERS } = ctx;
  const options = q.data.options;
  const cells = options.map((text, i) =>
    h("div.qt-know-opt", { style: { "--oc": OPTION_COLORS[i] } },
      h("span.qt-know-letter", OPTION_LETTERS[i]),
      h("span.qt-know-text", text),
      h("span.qt-know-voters")));
  canvas.append(h("div.qt-know-grid", { dataset: { n: options.length } }, cells));

  return {
    reveal(reveal, players) {
      const chosen = reveal.solution.index;
      if (chosen === null || chosen === undefined) {
        canvas.classList.add("is-void");
        return;
      }
      cells.forEach((cell, i) => cell.classList.add(i === chosen ? "is-right" : "is-wrong"));
      const subject = players.find((p) => p.id === reveal.subject);
      if (subject) cells[chosen].prepend(h("span.qt-know-owner", avatar(subject, 76)));
      for (const [pid, shown] of Object.entries(reveal.answers)) {
        if (pid === reveal.subject) continue;
        const player = players.find((p) => p.id === pid);
        if (player && cells[shown]) cells[shown].querySelector(".qt-know-voters").append(avatar(player, 54));
      }
    },
    destroy() {},
  };
}
