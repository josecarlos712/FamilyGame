// Phone side of «¿Lo conoces?»: one big button per option. The subject picks their own
// preference first; the others pick what they think the subject chose (the shell says who is who).
export function renderPhone(canvas, q, ctx) {
  const { h, OPTION_COLORS, OPTION_LETTERS } = ctx;
  let locked = false;
  const buttons = q.data.options.map((text, i) =>
    h("button.qt-know-btn", {
      type: "button",
      style: { "--oc": OPTION_COLORS[i] },
      onclick: () => {
        if (locked) return;
        mark(i);
        ctx.submit(i);
      },
    }, h("span.qt-know-letter", OPTION_LETTERS[i]), h("span", text)));
  canvas.append(h("div.qt-know-list", buttons));

  function mark(i) {
    locked = true;
    canvas.classList.add("is-locked");
    buttons[i]?.classList.add("is-picked");
  }

  return {
    lock(display) { mark(display); },
    reveal(reveal) {
      locked = true;
      canvas.classList.add("is-locked");
      const chosen = reveal.solution.index;
      if (chosen !== null && chosen !== undefined) buttons[chosen]?.classList.add("is-right");
    },
    destroy() {},
  };
}
