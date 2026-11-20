// Phone side of the double-slider question: two handles on one track.
export function renderPhone(canvas, q, ctx) {
  const { h, fmt, snap } = ctx;
  const { min, max, step, unit, maxWidth } = q.data;
  const span = max - min;
  let low = snap(min + span * 0.35, min, step);
  let high = snap(min + span * 0.65, min, step);
  let locked = false;

  const output = h("output.qt-sl-value.qt-rg-value");
  const fillBar = h("i.qt-rg-fill");
  const mk = (label, v) => h("input.qt-rg-input", { type: "range", min, max, step, value: v, "aria-label": label });
  const inLow = mk("Desde", low);
  const inHigh = mk("Hasta", high);
  const confirm = h("button.btn.primary.block", { type: "button" }, "Confirmar rango");
  const warn = h("p.qt-rg-warn");

  function render() {
    output.textContent = `${fmt(low)} – ${fmt(high, unit)}`;
    fillBar.style.left = ((low - min) / span) * 100 + "%";
    fillBar.style.width = ((high - low) / span) * 100 + "%";
    warn.textContent = maxWidth && high - low > maxWidth ? `Ojo: más ancho de ${fmt(maxWidth, unit)} no vale` : "";
  }
  inLow.addEventListener("input", () => {
    if (locked) return;
    low = Math.min(Number(inLow.value), high);
    inLow.value = low;
    render();
  });
  inHigh.addEventListener("input", () => {
    if (locked) return;
    high = Math.max(Number(inHigh.value), low);
    inHigh.value = high;
    render();
  });
  const nudges = (which) => h("div.qt-rg-nudges",
    h("span", which === "low" ? "Desde" : "Hasta"),
    ...[-1, 1].map((dir) => h("button.btn.qt-sl-nudge", { type: "button", "aria-label": `${which} ${dir > 0 ? "más" : "menos"}`, onclick: () => {
      if (locked) return;
      if (which === "low") low = Math.min(high, Math.max(min, snap(low + dir * step, min, step)));
      else high = Math.max(low, Math.min(max, snap(high + dir * step, min, step)));
      inLow.value = low; inHigh.value = high; render();
    } }, dir > 0 ? "+" : "−")));
  confirm.addEventListener("click", () => {
    if (locked) return;
    lock();
    ctx.submit([low, high]);
  });
  render();

  canvas.append(h("div.qt-sl-phone", output,
    h("div.qt-rg-wrap", h("div.qt-rg-track", fillBar), inLow, inHigh),
    h("div.qt-sl-limits", h("span", fmt(min, unit)), h("span", fmt(max, unit))),
    h("div.qt-rg-nudge-row", nudges("low"), nudges("high")), warn, confirm));

  function lock(shown) {
    if (shown) { [low, high] = shown; render(); }
    locked = true;
    canvas.classList.add("is-locked");
    inLow.disabled = inHigh.disabled = confirm.disabled = true;
  }
  return {
    lock,
    reveal(reveal) {
      lock();
      canvas.querySelector(".qt-sl-phone").append(h("p.qt-sl-solution", "Correcto: ", h("b", reveal.solution.text)));
    },
    destroy() {},
  };
}
