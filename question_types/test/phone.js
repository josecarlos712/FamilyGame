// Phone side of the multiple-choice question: one big button per option.
export function renderPhone(canvas, q, ctx) {
  const { h, OPTION_COLORS, OPTION_LETTERS } = ctx;
  let locked = false;
  const buttons = q.data.options.map((text, i) =>
    h("button.qt-test-btn", {
      type: "button",
      style: { "--oc": OPTION_COLORS[i] },
      onclick: () => {
        if (locked) return;
        mark(i);
        ctx.submit(i);
      },
    }, h("span.opt-letter", OPTION_LETTERS[i]), h("span", text)));
  canvas.append(h("div.qt-test-list", buttons));

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
      buttons[reveal.solution.index]?.classList.add("is-right");
    },
    destroy() {},
  };
}
