# Mecánicas de elección de categoría

Al empezar cada turno el motor sortea **cómo** se elige la categoría, con la misma probabilidad
entre las mecánicas aplicables. Nadie sabe cuál le va a tocar.

| Id | Nombre en pantalla | Icono | Quién actúa | Qué pasa |
|---|---|---|---|---|
| `ruleta` | Ruleta | 🎡 | el jugador del turno | Toca la ruleta en su móvil; gira en la tele y en todos los móviles y cae en una categoría al azar (todas con la misma probabilidad). |
| `moneda` | Cara o cruz | 💰 | el jugador del turno | Cara = su **mejor** categoría, cruz = su **peor**. Toca la moneda: sube girando, cae y se hace zoom a la cara que ha salido. |
| `rival` | Amigo de tus enemigos | 😈 | otro jugador al azar | Ese jugador elige en su móvil la categoría para el del turno, entre todas las disponibles. |
| `eleccion` | Elección propia | 🃏 | el jugador del turno | Elige una entre 3 categorías sorteadas. |

Aplicabilidad (si una no se puede usar, se sortea entre las demás):

- `rival` necesita al menos otro jugador conectado.
- `moneda` y `ruleta` necesitan al menos 2 categorías disponibles; con una sola categoría disponible
  se usa `eleccion` (que la ofrece directamente).
- `eleccion` ofrece `min(3, disponibles)`.

Mejor y peor categoría (moneda): tasa de acierto del jugador **en esta partida** por categoría
disponible, suavizada como `(aciertos + 1) / (preguntas + 2)`. Mejor = la tasa más alta, peor = la
más baja, desempates al azar, y siempre dos categorías distintas. Al principio de la partida todas
valen 0,5, así que la moneda enfrenta dos categorías al azar hasta que haya datos.

El anfitrión puede desactivar mecánicas en el lobby (`settings.mechanics`, por defecto las cuatro;
al menos una debe quedar activa).

## Tiempos (segundos, constantes del motor)

| Constante | Valor | Uso |
|---|---|---|
| `CHOICE_INTRO` | 2.5 | Anuncio de la mecánica; durante este tiempo se rechazan acciones. |
| `WHEEL_TIME` | 4.5 | Animación de la ruleta desde el toque hasta empezar la pregunta. |
| `COIN_TIME` | 4.0 | Lanzamiento (≈2.6) + zoom a la cara (≈1.4). |
| `PICK_REVEAL` | 1.5 | Tras elegir en `rival` o `eleccion`, se muestra la categoría elegida. |

Si quien actúa no hace nada en `elegir_categoria` segundos (tras la intro), el motor actúa por él:
gira la ruleta, lanza la moneda o elige al azar. Si está desconectado, a los 1.5 s.

## Contrato servidor ↔ pantallas

Mensajes del móvil:

- `{"t": "spin"}` — quien actúa en `ruleta` o `moneda` gira/lanza.
- `{"t": "choose", "category": "<id>"}` — quien actúa en `rival` o `eleccion` elige.

En la vista común (tele y móviles), con `phase == "choosing"`, además de los campos de siempre
(`chooserId`, `deadline`, `offered`):

```json
"choice": {
  "mechanic": "ruleta" | "moneda" | "rival" | "eleccion",
  "chooserId": "<jugador del turno>",
  "actorId": "<quien actúa: el del turno, o el rival que elige>",
  "offered": ["<id>", ...],          // ruleta: porciones en orden; moneda: [cara, cruz]; rival: todas; eleccion: 3
  "introUntil": 1700000000.0,        // hora del servidor hasta la que se muestra el anuncio
  "spinAt": null | 1700000003.1,     // hora en que empezó a girar / lanzarse / se eligió
  "revealUntil": null | 1700000007.6,// hora en que acaba la animación y empieza la pregunta
  "result": null | "<id>",           // categoría resultante, presente desde spinAt
  "outcome": null | "cara" | "cruz", // solo moneda
  "stats": {"cara": 0.8, "cruz": 0.2} | null // solo moneda: % de acierto real del jugador (null si sin datos)
}
```

`deadline` es la hora de la acción automática antes de actuar, y `revealUntil` después.
Durante `choosing` todos los móviles reciben `categories` (id, nombre, icono, color) para dibujar la
ruleta, la moneda y los botones. Las animaciones se sincronizan con `serverNow()` y siempre acaban en
`result`/`outcome`, que decide el servidor.
