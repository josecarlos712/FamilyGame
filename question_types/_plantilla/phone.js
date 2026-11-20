// PLANTILLA · cómo responde cada jugador desde su MÓVIL.
//
// El móvil ya muestra el enunciado y el tiempo. Aquí dibujas los controles en `canvas`.
//
// ctx = { h, fmt, snap, avatar, OPTION_COLORS, OPTION_LETTERS, me, mapsKey,
//         submit(valor)      envía la respuesta (una sola vez); el servidor la valida
//                            con normalize_answer() de type.py
//         unavailable(motivo) si este móvil no puede mostrar la pregunta: no le cuenta }
//
// Devuelve un objeto con:
//   lock(respuesta)        el jugador ya respondió (p. ej. al recargar la página)
//   reveal(reveal, result) al acabar el tiempo; result = tu resultado {correct, points, detail}
//   destroy()
export function renderPhone(canvas, q, ctx) {
  const { h } = ctx;
  const input = h("input.qt-tpl-input", { type: "text", maxlength: 40, placeholder: `${q.data.letters} letras`, "aria-label": "Respuesta" });
  const send = h("button.btn.primary.block", { type: "button" }, "Enviar");
  canvas.append(h("div.qt-tpl-phone", input, send));

  function lock(value) {
    input.value = value ?? input.value;
    input.disabled = send.disabled = true;
  }
  send.addEventListener("click", () => {
    if (!input.value.trim()) return;
    lock();
    ctx.submit(input.value.trim());
  });

  return {
    lock,
    reveal(reveal) {
      lock();
      canvas.append(h("p.qt-tpl-hint", `Respuesta: ${reveal.solution.text}`));
    },
    destroy() {},
  };
}
