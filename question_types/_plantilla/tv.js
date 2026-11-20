// PLANTILLA · lo que se ve en la TELE para este tipo de pregunta.
//
// La tele ya dibuja el enunciado, la categoría, el tiempo y quién ha respondido.
// Aquí solo dibujas la zona de la pregunta dentro de `canvas` (un <div> vacío).
//
// q   = { key, type, prompt, time, read, points, image, data, category, ... }
//       q.data es lo que devuelve public_data() en type.py
// ctx = { h, fmt, snap, avatar, OPTION_COLORS, OPTION_LETTERS, mapsKey, players }
//       h("div.clase", {atributos}, ...hijos) crea elementos (sin innerHTML)
//
// Devuelve un objeto con:
//   reveal(reveal, players)  al acabar el tiempo. reveal = { solution, explanation,
//                            answers: {idJugador: respuesta}, results: {idJugador: {correct, points, ...}} }
//   destroy()                al pasar a otra pantalla
export function renderTV(canvas, q, ctx) {
  const { h, avatar } = ctx;
  const hint = h("p.qt-tpl-hint", `Una palabra de ${q.data.letters} letras`);
  const answers = h("div.qt-tpl-answers");
  canvas.append(h("div.qt-tpl", hint, answers));

  return {
    reveal(reveal, players) {
      hint.textContent = `Era: ${reveal.solution.text}`;
      for (const [pid, value] of Object.entries(reveal.answers)) {
        const player = players.find((p) => p.id === pid);
        const ok = reveal.results[pid]?.correct;
        if (player) answers.append(h("div.qt-tpl-row", { class: ok ? "is-good" : "" }, avatar(player, 48), h("span", value)));
      }
    },
    destroy() {},
  };
}
