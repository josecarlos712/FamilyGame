# Crear un tipo de pregunta

Un tipo de pregunta es una carpeta dentro de `question_types/` que el juego carga al arrancar.
El motor no sabe cómo funciona cada tipo: solo llama a los métodos de la clase base y entrega a los
módulos JS un contenedor (`canvas`) donde dibujar.

```
question_types/
  mi_tipo/
    type.py     ← obligatorio: clase Python
    tv.js       ← obligatorio: dibujo en la tele
    phone.js    ← obligatorio: controles del móvil
    style.css   ← opcional, se carga solo la primera vez que sale el tipo
    ...         ← cualquier otro recurso (.js, .svg, .png, .json, .mp3...)
```

Los archivos de la carpeta se sirven en `/qtypes/<carpeta>/<archivo>` (nunca los `.py`), así que
`tv.js` puede hacer `import "./otro.js"`. Las carpetas que empiezan por `_` no se cargan: la
plantilla lista para copiar es `question_types/_plantilla`.

Si un tipo falla al importar, el juego sigue: el error aparece en la consola y en el lobby de la tele,
y las preguntas de ese tipo salen como «tipo desconocido».

## Ciclo de vida

```
archivo .toml ──► __init__ ──► parse()            validar al cargar (una vez)
                               is_available(env)  ¿se puede ofrecer ahora?
se pregunta  ──► prepare(rng) ──► state           estado aleatorio de esta vez
             ──► to_public(state) ──► tele y móviles (sin la solución)
móvil envía  ──► normalize_answer(raw, state) ──► evaluate(answer, state)
fin de tiempo──► to_reveal(state) + answer_for_display(answer, state) ──► tele y móviles
```

## Python: `type.py`

```python
from familygame.questions.base import (
    AnswerError, Environment, Evaluation, FieldReader, QuestionFormatError, QuestionType,
)

class MiPregunta(QuestionType):
    type_id = "mi_tipo"          # lo que se escribe en tipo = "..."
    aliases = ("mi tipo",)        # otros nombres válidos (sin importar tildes ni mayúsculas)
    display_name = "Mi tipo"
    default_time = 20             # si la pregunta no pone «tiempo»
    requires_internet = False     # True: no se ofrece sin conexión
    tiebreak_priority = 0         # >0: preferido para desempates «gana el más cercano»
    about_chooser = False         # True: pregunta sobre quien eligió la categoría (ver abajo)
```

### Preguntas sobre un jugador (`about_chooser = True`)

Para tipos como «¿Lo conoces?» (`question_types/conoces`), donde no hay respuesta correcta en el
archivo: la respuesta buena es la que elige el jugador que sacó la pregunta (el *conocido*).

1. Tras la lectura, solo el conocido puede responder (`question.stage == "subject"`); a los demás el
   motor les contesta «Espera: primero elige…» y sus móviles no montan el módulo todavía.
2. Su respuesta se pasa a `set_reference(respuesta, state)` (por defecto la guarda en
   `state["reference"]`), y el reloj vuelve a empezar para los amigos (`stage == "guess"`).
3. `evaluate` y `solution_data` comparan con `state["reference"]`. Si el conocido no llegó a
   elegir, no existe: `solution_data` debe aguantarlo (la pregunta queda anulada).

Puntuación (constantes en `engine.py`): amigo que acierta +100 (sin bonus de rapidez); conocido
+100 por amigo que acierta y −50 por amigo que falla (nunca baja de 0; quien no responde no cuenta).
El conocido cuenta como acierto (casillas, progreso, ×2) si acierta al menos la mitad. Si se le acaba
el tiempo, la pregunta se anula y pierde 50; si se va o no puede verla, se anula sin castigo.
Estas preguntas nunca salen en desempates ni si no hay al menos dos jugadores conectados.

La tele y el móvil ya muestran «Pregunta sobre X», la espera y el resultado del conocido; `q.subject`
y `q.stage` llegan en la pregunta, y `reveal.subject` y `reveal.void` en la revelación.

| Método | Obligatorio | Qué hace |
|---|---|---|
| `parse(fields)` | sí | Lee los campos propios con `FieldReader` y lanza `QuestionFormatError("mensaje")` si algo está mal. Los campos comunes ya están leídos. |
| `prepare(rng)` | no | Devuelve un `dict` con lo aleatorio de esta vez (p. ej. el orden barajado). Por defecto `{}`. |
| `public_data(state)` | sí | `dict` serializable a JSON que reciben tele y móviles. **No debe contener la solución.** |
| `normalize_answer(raw, state)` | sí | Valida lo que manda el móvil y lo convierte a la forma interna. Lanza `AnswerError` si no vale. |
| `evaluate(answer, state)` | sí | Devuelve `Evaluation(correct, closeness, detail)`. |
| `solution_data(state)` | sí | `dict` con la solución para la revelación. |
| `answer_for_display(answer, state)` | no | Cómo se envía a la tele la respuesta de cada jugador (por defecto, tal cual). |
| `is_available(env)` | no | `(True, "")` o `(False, "motivo")`. `env.internet` y `env.google_maps_api_key`. |

`FieldReader` valida con mensajes en español: `text(clave, por_defecto)`, `number(clave, por_defecto,
mínimo, máximo)`, `integer(...)`, `boolean(clave, por_defecto)`, `choice(clave, opciones,
por_defecto)`, `get(clave)` y `has(clave)`. Los campos que nadie lee se avisan como desconocidos.

`Evaluation`:

- `correct`: si cuenta como acierto (puntos, casillas, progreso de categoría).
- `closeness`: de 0 a 1, lo cerca que estuvo. Desempata duelos y desempates aunque nadie acierte.
- `detail`: texto corto para el móvil («A 12 km», «Solape del 60 %»).

Los puntos los calcula el motor, no el tipo: puntos base × (1 + 0,5 × fracción de tiempo restante).

## JavaScript: `tv.js`

```js
export function renderTV(canvas, q, ctx) {
  // dibuja dentro de canvas
  return {
    reveal(reveal, players) {},   // al acabar el tiempo
    destroy() {},                 // al cambiar de pantalla
  };
}
```

La tele ya pinta el enunciado, la imagen, la categoría, el cronómetro y quién ha respondido. El
módulo se monta cuando se abre el tiempo de respuesta (no durante la lectura). La tele trabaja sobre
un lienzo fijo de **1920 × 1080 px** escalado a la pantalla: usa píxeles grandes (textos de 40 px o más).

## JavaScript: `phone.js`

```js
export function renderPhone(canvas, q, ctx) {
  // ctx.submit(valor) envía la respuesta, una vez
  return {
    lock(respuesta) {},           // ya respondió (p. ej. al reconectar)
    reveal(reveal, result) {},    // result: { correct, points, detail, ... } de este jugador
    destroy() {},
  };
}
```

Si el móvil no puede mostrar la pregunta (no carga un recurso, falta un permiso…), llama a
`ctx.unavailable("motivo")`: a ese jugador la pregunta no le cuenta y no se le espera.

## Datos que reciben los módulos

`q` (pregunta pública):

```js
{ key, type, prompt, time, read, difficulty, points, image,
  data,                 // lo de public_data()
  number, openAt, deadline, tiebreak,
  category: { id, name, icon, color }, starPlayers, duels }
```

`reveal`:

```js
{ explanation, solution,          // lo de solution_data()
  answers: { idJugador: valor },  // lo de answer_for_display()
  results: { idJugador: { answered, exempt, correct, points, bonus, steps, fastest, closed, detail, duel } } }
```

`ctx` (los dos lados): `h`, `fmt`, `snap`, `avatar`, `OPTION_COLORS`, `OPTION_LETTERS`, `mapsKey`.
En la tele además `players`; en el móvil `me`, `submit` y `unavailable`.

- `h("div.clase#id", { atributos, onclick, style: { "--var": "x" } }, ...hijos)` crea elementos sin
  `innerHTML`: úsalo para cualquier texto que venga de archivos o jugadores.
- `fmt(1234.5, "km")` → `"1.234,5 km"`; `snap(valor, min, paso)` redondea al paso.
- `avatar(jugador, tamaño)` dibuja el avatar con el anillo de su color.

## Estilos

Prefija tus clases (`.qt-mitipo-...`) para no chocar con otros tipos. Tienes disponibles las
variables de `web/css/base.css`: `--bg`, `--surface`, `--surface-2`, `--ink`, `--muted`,
`--accent`, `--good`, `--bad`, `--star`, `--radius`, `--ease`, y las animaciones `pop`, `rise` y
`pulse`.

## Probarlo

1. Escribe una pregunta de tu tipo en un `.toml` de `preguntas/`.
2. Añade tests en `tests/` (mira `tests/test_questions.py`: los tipos se crean con
   `registry.get("mi_tipo")(raw_dict, "cat:1")`).
3. Reinicia el servidor (los tipos se cargan al arrancar; «Recargar preguntas» solo relee los `.toml`).
