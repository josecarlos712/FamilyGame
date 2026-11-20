# FamilyGame

Trivial familiar para jugar en la tele: las preguntas y el tablero se ven en una pantalla común y
cada jugador (hasta 6) responde a la vez desde su móvil.

![Pregunta en la tele: cuatro opciones y quién ha respondido ya](docs/img/tv-question.png)

| Lobby | Elegir categoría | Resultados |
|---|---|---|
| ![Lobby con QR y jugadores](docs/img/tv-lobby.png) | ![Elección de categoría](docs/img/tv-choosing.png) | ![Resultados de la pregunta](docs/img/tv-reveal.png) |
| **Tablero** | **Podio** | |
| ![Circuito con las fichas](docs/img/tv-board.png) | ![Podio final](docs/img/tv-finished.png) | |

En el móvil:

| Perfil | Elegir | Responder | Resultado |
|---|---|---|---|
| ![Perfil en el móvil](docs/img/movil-lobby.png) | ![Elegir categoría en el móvil](docs/img/movil-choosing.png) | ![Responder en el móvil](docs/img/movil-question.png) | ![Resultado en el móvil](docs/img/movil-reveal.png) |

Documentación detallada:

- [docs/preguntas.md](docs/preguntas.md): todos los campos de los archivos de preguntas, con ejemplos.
- [docs/tipos-de-pregunta.md](docs/tipos-de-pregunta.md): cómo programar un tipo de respuesta nuevo.
- [docs/arquitectura.md](docs/arquitectura.md): módulos, fases de la partida, puntuación y protocolo.

## Arrancar

Doble clic en **`iniciar.bat`** (la primera vez crea el entorno e instala dependencias).

- **Tele:** `http://localhost:8000/tv` (se abre sola). Ponla a pantalla completa con F11.
- **Móviles:** escanean el QR de la tele o abren la dirección que aparece debajo
  (los móviles tienen que estar en la misma red wifi que el PC).

A mano: `.venv\Scripts\python src\main.py [--puerto 8000] [--sin-internet]`.

## Cómo se juega

1. Cada jugador entra con nombre, icono (o foto de la galería) y un color.
2. El primero en entrar es el **anfitrión** 👑: elige cómo se gana, qué categorías se juegan y empieza.
3. Por turnos, un jugador elige la categoría (o «Al azar»). **Todos responden a la vez.**
4. Acertar da puntos (más cuanto antes respondas) y casillas en el tablero:
   2 por acierto, +1 al más rápido.
5. Casillas del circuito:
   - **★ Estrella:** si aciertas la siguiente pregunta estando en ella, cierras su categoría.
   - **🎲 Evento:** puntos dobles, regalo, mala suerte, avanzar, retroceder, robar al líder, cambiar el sitio.
   - **⚔️ Duelo:** retas al jugador con puntos más parecidos; en la siguiente, quien lo haga mejor le roba 50.
   - **Salida:** pasar por ella da +50.
6. **Victoria** (la elige el anfitrión): llegar a X puntos, jugar X rondas, o cerrar X categorías
   (con N aciertos en una categoría o acertando desde una estrella).
   Cerrar una categoría da +100 en cualquier modo.

## Añadir preguntas (sin tocar código)

Cada archivo `.toml` de la carpeta **`preguntas/`** es una categoría (puedes usar subcarpetas).
Copia `preguntas/_PLANTILLA.toml`, quítale el guion bajo y escribe. Ahí están documentados todos
los campos. Ejemplo mínimo:

```toml
[categoria]
nombre = "Mi categoría"
icono = "🎲"
color = "#4dabf7"

[[pregunta]]
enunciado = "¿Cuál es la capital de Australia?"
opciones = ["Sídney", "Canberra", "Melbourne"]
correcta = "Canberra"
tiempo = 15
```

Tipos disponibles: `test`, `slider` (un número con tolerancia), `rango` (doble slider con
criterio solapar / contener / coincidir) y `mapa` (punto + radio en metros, o una zona).
Cada pregunta define su propio `tiempo` (2 a 300 s).

Con el servidor arrancado, el anfitrión puede pulsar **«Recargar preguntas»** en el lobby para
ver los cambios sin reiniciar. Las preguntas con errores se ignoran y la tele las lista en el lobby
(archivo y motivo); el resto de la categoría sigue funcionando.

## Mapas

Las preguntas `mapa` usan Google Maps. Pon tu clave de la *Maps JavaScript API* en
`config.toml` (`[mapas] google_maps_api_key`). Restríngela por referente HTTP en la consola de
Google, porque la clave viaja a los navegadores. Sin clave o sin internet, esas preguntas no se
ofrecen; si el mapa falla en un móvil concreto, a ese jugador la pregunta no le cuenta.

## Crear un tipo de pregunta nuevo

Copia `question_types/_plantilla` a una carpeta nueva (sin `_` delante) y edita:

| Archivo | Qué hace |
|---|---|
| `type.py` | Clase que hereda de `QuestionType`: lee y valida los campos del archivo, valida la respuesta del móvil y decide si es correcta. |
| `tv.js` | `renderTV(canvas, q, ctx)`: lo que se ve en la tele y cómo se revela la solución. |
| `phone.js` | `renderPhone(canvas, q, ctx)`: los controles para responder; envía con `ctx.submit(valor)`. |
| `style.css` | Estilos del tipo (opcional). |

El juego descubre la carpeta al arrancar; el valor de `type_id` es lo que se escribe en `tipo = "..."`.

## Decisiones de partida

- **Empates:** pregunta de desempate a muerte súbita entre los empatados (se prefieren sliders:
  gana el más cercano). Tras 3 intentos sin desempate, victoria compartida.
- **Nombres repetidos:** no se permiten (sin distinguir mayúsculas ni tildes).
- **Colores:** paleta fija de 12, todos legibles sobre el fondo de la tele; cada color, un jugador.
- **Desconexiones:** el móvil se reconecta solo y recupera su jugador. Si quien elige se va, la
  categoría sale al azar. Si no queda nadie conectado, el reloj se congela. El anfitrión puede
  sacar a un jugador. Se puede entrar con la partida empezada (con 0 puntos).
- **Repeticiones:** una pregunta no sale dos veces en la misma partida; además se prefieren las que
  no salieron en partidas anteriores (`data/historial.json`). Si se agotan, se avisa y se repiten.
- **Categorías grandes y pequeñas:** «Al azar» elige categoría con la misma probabilidad para todas,
  tenga 200 preguntas o 10. El anfitrión puede limitar cuántas categorías se ofrecen cada turno.
- **Fotos:** se reducen a 256 px en el móvil, se guardan en el propio móvil para la próxima vez y
  el servidor solo las tiene en memoria durante la sesión.

## Configuración

`config.toml`: puerto, clave de mapas, máximo de jugadores y segundos de cada fase.

## Desarrollo

```powershell
.venv\Scripts\python -m pytest
```

Las capturas de este README se regeneran con `.venv\Scripts\python tools\capturas.py` (usa Edge
en modo headless y las escenas congeladas de `tools/demo.py`).

Estructura: `src/familygame` (motor, carga de preguntas, servidor), `question_types/` (tipos),
`preguntas/` (categorías), `web/` (pantallas de tele y móvil), `tests/`.
