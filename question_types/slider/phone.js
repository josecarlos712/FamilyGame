// Phone side of the slider question: big value, range input, fine-tune buttons, confirm.
export function renderPhone(canvas, q, ctx) {
  const { h, fmt, snap } = ctx;
  const { min, max, step, unit, start } = q.data;
  let value = snap(start, min, step);
  let locked = false;

  const output = h("output.qt-sl-value");
  const input = h("input.qt-sl-input", { type: "range", min, max, step, value, "aria-label": "Valor" });
  const confirm = h("button.btn.primary.block", { type: "button" }, "Confirmar");
  const nudge = (dir) => h("button.btn.qt-sl-nudge", { type: "button", "aria-label": dir > 0 ? "Más" : "Menos",
    onclick: () => set(value + dir * step) }, dir > 0 ? "+" : "−");

  function set(v) {
    if (locked) return;
    value = Math.min(max, Math.max(min, snap(Number(v), min, step)));
    input.value = value;
    output.textContent = fmt(value, unit);
  }
  input.addEventListener("input", () => set(input.value));
  confirm.addEventListener("click", () => {
    if (locked) return;
    lock(value);
    ctx.submit(value);
  });
  set(value);

  canvas.append(h("div.qt-sl-phone", output, h("div.qt-sl-row", nudge(-1), input, nudge(1)),
    h("div.qt-sl-limits", h("span", fmt(min, unit)), h("span", fmt(max, unit))), confirm));

  function lock(shown) {
    locked = true;
    canvas.classList.add("is-locked");
    output.textContent = fmt(shown, unit);
    input.disabled = true;
    confirm.disabled = true;
  }
  return {
    lock,
    reveal(reveal) {
      lock(value);
      canvas.querySelector(".qt-sl-phone").append(h("p.qt-sl-solution", "Respuesta: ", h("b", reveal.solution.text)));
    },
    destroy() {},
  };
}
