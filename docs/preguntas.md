# Guía para escribir preguntas

Cada archivo `.toml` dentro de `preguntas/` es **una categoría = un tema** (historia, ciencia, cine…).
La mecánica de respuesta se elige **por pregunta** con `tipo` (test, slider, rango, mapa, conoces): cualquier
categoría puede mezclar tipos. Una pregunta «relámpago» es una pregunta normal con `tiempo` y `lectura`
pequeños. Las preguntas de mapa se saltan solas si no hay clave de Google Maps. Se pueden organizar en
subcarpetas. Se ignoran los archivos y carpetas cuyo nombre empieza por `_` (como `_PLANTILLA.toml`),
así que sirven para borradores.

El formato es [TOML](https://toml.io/es/): texto entre comillas, números sin comillas, listas entre
corchetes y `#` para comentarios. Guárdalo en UTF-8 (cualquier editor moderno lo hace por defecto).

## Cabecera de la categoría

```toml
[categoria]
nombre = "Cine y TV"        # si falta, se usa el nombre del archivo
icono = "🎬"                # un emoji
color = "#f783ac"           # #rrggbb; si falta, se asigna uno
descripcion = "Opcional"
```

## Campos comunes a todas las preguntas

Cada pregunta empieza con `[[pregunta]]` (doble corchete).

| Campo | Obligatorio | Valor | Por defecto |
|---|---|---|---|
| `tipo` | no | `test`, `slider`, `rango`, `mapa` (también valen alias como `"doble slider"`) | `test` |
| `enunciado` | **sí** | texto, máx. 300 caracteres | — |
| `tiempo` | no | segundos para responder, de 2 a 300 | test 20, slider 20, rango 25, mapa 45 |
| `lectura` | no | segundos de lectura antes de poder responder (0–30) | según la longitud del enunciado (2–6 s) |
| `dificultad` | no | 1, 2 o 3 → 100, 150 o 200 puntos base | 1 |
| `puntos` | no | puntos base exactos (sustituye a la dificultad) | — |
| `explicacion` | no | dato curioso que se muestra al revelar | — |
| `imagen` | no | ruta dentro de `preguntas/`, p. ej. `"img/torre.jpg"` | — |
| `id` | no | identificador único; si cambias el enunciado y quieres que cuente como la misma pregunta | el propio enunciado |

Las preguntas **relámpago** son las que tienen un `tiempo` de 5 segundos o menos. El juego las avisa
(«⚡ ¡Pregunta relámpago!» en la tele y en los móviles) y nunca deja menos lectura de la que corresponde
por la longitud del enunciado, más 1,5 s para el aviso: así da tiempo a leerla antes de que salgan las
respuestas. Una `lectura` más larga sí se respeta.

```toml
[[pregunta]]
enunciado = "¿Cuántas patas tiene una araña?"
opciones = ["6", "8", "10"]
correcta = "8"
tiempo = 3
lectura = 1.5
```

## Tipo `test`

| Campo | Valor |
|---|---|
| `opciones` | lista de 2 a 8 textos distintos |
| `correcta` | el texto exacto de la opción (sin importar mayúsculas) **o** su número empezando en 1 |
| `barajar` | `true` (por defecto) baraja el orden cada vez; `false` para Verdadero/Falso o «Todas las anteriores» |

Vale si eliges la opción correcta.

## Tipo `slider` (un número)

| Campo | Valor |
|---|---|
| `min`, `max` | límites del slider (`max` > `min`) |
| `paso` | salto entre valores (por defecto 1; admite decimales: `0.1`) |
| `unidad` | texto tras el número: `"km"`, `"°C"`… |
| `respuesta` | el valor correcto, dentro de min–max |
| `tolerancia` | margen absoluto: vale `respuesta ± tolerancia` |
| `tolerancia_pct` | margen en % de la respuesta (no se puede usar con respuesta 0) |
| `inicio` | dónde aparece el selector al empezar (por defecto, en medio) |

Usa `tolerancia` **o** `tolerancia_pct`, no las dos. Sin ninguna, solo vale el valor exacto.
Las respuestas se ajustan al `paso` más cercano.

## Tipo `rango` (doble slider)

| Campo | Valor |
|---|---|
| `min`, `max`, `paso`, `unidad` | como en el slider |
| `respuesta` | `[desde, hasta]` |
| `criterio` | `solapar` (por defecto), `contener` o `coincidir` |
| `solape_min` | para `solapar`: % mínimo de solape (1–100, por defecto 50) |
| `ancho_max` | para `contener`: ancho máximo del rango del jugador (por defecto, el doble del correcto o el 10 % del slider, lo que sea mayor) |
| `margen` | para `coincidir`: error permitido en cada extremo (por defecto 0) |

Criterios:

- **solapar**: se calcula intersección ÷ unión de los dos rangos. Marcar todo el slider da un
  solape bajo, así que no compensa hacer trampa.
- **contener**: tu rango debe contener el correcto entero y no pasar de `ancho_max`.
- **coincidir**: los dos extremos a ± `margen` de los correctos.

## Tipo `mapa`

Necesita internet y una clave de Google Maps en `config.toml`. Dos formas de definir la respuesta:

```toml
# Punto + radio en metros
respuesta = { lat = 48.8584, lng = 2.2945 }
radio = 30000

# o una zona (polígono de al menos 3 puntos [lat, lng])
zona = [[39.96, 2.80], [39.92, 3.20], [39.30, 3.20], [39.35, 2.40]]
```

`vista = { lat = 46, lng = 2, zoom = 5 }` fija la vista inicial (si no, se ve el mundo entero).
«Cerca» sin número no existe: sin `radio` o `zona` la pregunta se rechaza.

Coordenadas: en Google Maps, clic derecho sobre un sitio → el primer elemento del menú copia
`lat, lng`.

## Tipo `conoces` («¿Lo conoces?»)

Una pregunta sobre el jugador que eligió la categoría (el *conocido*). No hay respuesta correcta en
el archivo: primero el conocido elige en secreto lo que de verdad prefiere, y después los demás
intentan adivinarlo. Escribe el enunciado en tercera persona y sin nombres (la tele ya muestra sobre
quién es) y con opciones que dividan a la familia.

```toml
[[pregunta]]
tipo = "conoces"
enunciado = "¿Qué plato prefiere?"
opciones = ["Paella", "Tortilla de patatas", "Cocido", "Pizza"]   # de 2 a 6
barajar = true          # opcional (por defecto true)
```

Puntos: cada amigo que acierta gana 100; el conocido gana 100 por cada amigo que acierta y pierde 50
por cada uno que falla; si el saldo de la pregunta es negativo, resta y retrocede una casilla. Si no elige a tiempo, la pregunta se anula y pierde 50. Solo
salen con dos o más jugadores y nunca en los desempates.

## Qué pasa si me equivoco

No se cae nada. Al arrancar (o al pulsar «Recargar preguntas» en el lobby):

- Una **pregunta** mal escrita se descarta y el resto de la categoría sigue funcionando.
- Un **archivo** que no se puede leer (por ejemplo, una comilla sin cerrar) deja esa categoría
  desactivada.
- Una pregunta **repetida** (mismo enunciado) se ignora.
- Un campo desconocido se ignora con un aviso.

La tele muestra en el lobby el archivo y el motivo; la consola donde corre el servidor también.
Para comprobar los archivos sin jugar:

```powershell
.venv\Scripts\python -m pytest tests/test_questions.py -k bundled
```

## Repeticiones y equilibrio

- En una partida no se repite ninguna pregunta. Si una categoría se agota, deja de ofrecerse; si se
  agotan todas, el juego avisa y vuelven a salir.
- Entre partidas se prefieren las preguntas que no han salido nunca o hace más tiempo
  (`data/historial.json`; bórralo para empezar de cero).
- «Al azar» elige primero la categoría con la misma probabilidad para todas, así que una categoría
  con muchas preguntas no sale más que una con pocas.

## Origen de las preguntas incluidas

- Unas 1.150 preguntas tipo test (marcadas en la cabecera de cada archivo) proceden del
  [megaestudio español de cultura general](https://doi.org/10.6084/m9.figshare.14073899)
  (Buades-Sitjar, Planchuelo y Duñabeitia, 2021), licencia
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Se revisaron, se descartaron las dudosas
  o desfasadas y la `dificultad` sale del porcentaje de acierto real de 48.000 participantes en España.
- Las coordenadas de las preguntas de mapa y las capitales de `geografia.toml` salen de [Wikidata](https://www.wikidata.org) (CC0).
- El resto (historia de España, deportes, cine y TV, relámpago y numéricas) se redactó para el juego.
  Si ves un dato erróneo o desfasado, corrígelo o bórralo en su archivo.

Para validar archivos sueltos con el cargador real (también avisa de enunciados repetidos entre ellos):

```powershell
.venv\Scripts\python tools\validar_preguntas.py preguntas\historia.toml preguntas\deportes.toml
```
