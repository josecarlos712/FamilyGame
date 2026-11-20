# Arquitectura

```
                 ┌──────────── PC (servidor) ────────────┐
 Tele  ─/tv──────┤ Starlette + Uvicorn                    │
   ws /ws/tv  ◄──┤   GameServer ── Game (motor puro)      │◄── preguntas/*.toml
                 │      │            ├ Board              │◄── question_types/*/type.py
 Móviles ─/──────┤      │            ├ Settings / Players │
   ws /ws/phone ◄┤   ticker (5/s) ──►└ QuestionHistory ───┼──► data/historial.json
                 └────────────────────────────────────────┘
```

| Módulo | Responsabilidad |
|---|---|
| `src/main.py` | Arranque, argumentos, resumen en consola. |
| `familygame/config.py` | Lee `config.toml` con valores por defecto. |
| `familygame/questions/base.py` | Clase base `QuestionType`, `FieldReader`, `Evaluation`. |
| `familygame/questions/registry.py` | Carga dinámica de `question_types/*/type.py`. |
| `familygame/categories.py` | Lee los `.toml`, valida cada pregunta y recoge errores. |
| `familygame/game/engine.py` | Máquina de estados de la partida. Sin E/S ni reloj: recibe `now`. |
| `familygame/game/board.py` | Circuito de 28 casillas y movimiento. |
| `familygame/game/players.py` | Jugadores, paleta con contraste y reglas de nombre. |
| `familygame/game/picker.py` | Elección de pregunta sin repetir e historial entre partidas. |
| `familygame/server.py` | HTTP, WebSockets, fotos, QR y recursos de los tipos. |
| `web/` | Pantallas de tele (`tv.html`) y móvil (`phone.html`) en JS sin compilar. |

El motor es determinista con un `Random` inyectado y el tiempo como parámetro, por eso los tests
recorren partidas enteras en milisegundos (`tests/test_engine.py`).

## Fases

```
lobby ─► choosing ─► reading ─► answering ─► reveal ─► board ─┬─► choosing …
                                                               └─► finished
                     empate al final ─► tiebreak ─► reading ─► answering ─► reveal ─┬─► finished
                                                                                    └─► tiebreak
```

| Fase | Termina cuando |
|---|---|
| `choosing` | Se sortea una mecánica (ruleta, moneda, rival, elección; ver `docs/mecanicas-categoria.md`); quien actúa tiene `elegir_categoria` s tras la intro, o el motor actúa por él (1,5 s si está desconectado). |
| `reading` | Pasan los segundos de `lectura` de la pregunta. |
| `answering` | Todos los conectados respondieron (o están exentos), o se acaba `tiempo` + 0,6 s de margen de red. |
| `reveal` | Pasan `revelar` s (el anfitrión puede saltar). |
| `board` | Pasan `tablero` s + 1,8 s por cada texto de casilla (el anfitrión puede saltar). |
| `tiebreak` | 4 s de presentación y empieza la pregunta de desempate. |

Si no queda ningún móvil conectado, todos los relojes se congelan.

## Puntuación

| Concepto | Valor |
|---|---|
| Acierto | puntos base × (1 + 0,5 × tiempo restante / tiempo total) |
| Puntos base | dificultad 1/2/3 → 100/150/200, o `puntos` |
| Casilla «puntos dobles» | ×2 en la siguiente pregunta |
| Cerrar categoría | +100 |
| Pasar por la salida | +50 |
| Duelo | el ganador roba 50 (gana quien acierta; si ambos, el más rápido; si ninguno, nadie) |
| Avance | 2 casillas por acierto, +1 al más rápido (empates incluidos) |
| «¿Lo conoces?» | amigo que acierta +100; conocido +100 por acierto ajeno y −50 por fallo (si sale negativo, retrocede 1 casilla); −50 si no elige |

Constantes en la cabecera de `engine.py`.

## Ronda

Una ronda termina cuando cada jugador conectado ha elegido categoría una vez (orden de llegada).
En el modo «rondas», la partida acaba al terminar la última.

## Protocolo WebSocket

Mensajes JSON con un campo `t`.

### Móvil → servidor (`/ws/phone`)

| `t` | Campos | Quién |
|---|---|---|
| `hello` | `token` (o `null`) | todos, al conectar |
| `join` | `name`, `color`, `avatar` (`{kind:"icon", value}` o `{kind:"photo", data:"data:image/jpeg;base64,..."}`) | sin jugador |
| `profile` | igual que `join` | jugador, fuera de partida |
| `settings` | `changes`: `mode`, `targetPoints`, `rounds`, `categoriesToClose`, `hitsToClose`, `toggleMechanic`, `toggleCategory`, `disabled` (mecánicas: `docs/mecanicas-categoria.md`) | anfitrión, en el lobby |
| `start` | — | anfitrión |
| `choose` | `category` (id) | quien actúa en `rival`/`eleccion` (ver `docs/mecanicas-categoria.md`) |
| `spin` | — | quien actúa en `ruleta`/`moneda` |
| `answer` | `value` (lo que valide el tipo) | participantes |
| `unavailable` | `reason` | participantes |
| `next` | — | anfitrión (salta revelación/tablero) |
| `kick` | `player` | anfitrión |
| `leave` | — | jugador |
| `lobby` | — | anfitrión (termina y vuelve al lobby) |
| `reload` | — | anfitrión (relee los `.toml`) |

### Servidor → móvil

| `t` | Contenido |
|---|---|
| `welcome` | `id`, `token` (si el token era válido), `types`, `icons`, `mapsKey`, `joinUrl` |
| `joined` | `id`, `token` (el móvil lo guarda para reconectar) |
| `state` | `now` (reloj del servidor) y `state` con la vista del jugador |
| `error` | `msg` para mostrar |
| `kicked` / `left` / `replaced` | el móvil vuelve a la pantalla de perfil |

La tele (`/ws/tv`) solo recibe `welcome` y `state` con la vista completa (tablero, categorías,
movimientos, registro de eventos). Las respuestas de los demás jugadores nunca viajan a un móvil
antes de la revelación.

Los relojes se sincronizan con `now`: cada pantalla calcula su desfase y cuenta hacia el `deadline`
del servidor.

## Seguridad (red de casa)

- Fotos: solo JPEG/PNG/WebP comprobando la firma del archivo, máx. 400 KB, en memoria.
- Recursos de tipos: solo extensiones de una lista blanca, nunca `.py`, sin salir de la carpeta.
- Imágenes de preguntas: solo dentro de `preguntas/`.
- Textos de jugadores y archivos se insertan siempre como texto (`h()`), nunca como HTML.
- Mensajes de más de 700 KB se rechazan.

No hay contraseñas: cualquiera en la misma wifi puede entrar mientras haya sitio.

## Sonido

`web/js/sound.js` sintetiza efectos y la melodía de serie con WebAudio, y reproduce las canciones de
`musica/` con un `<audio>` enganchado al mismo bus (volumen, atenuado y silencio local valen igual).
El ajuste `track` es la ruta relativa de la canción (`""` = melodía de serie) y `music` significa
sonando/parada. `src/familygame/music.py` (`MusicLibrary`) lista la carpeta, valida las rutas (la tele
pide el archivo en `/music/<ruta>`) y guarda favoritos y última canción en `data/musica.json`. El
móvil del anfitrión pide la lista con `{t: "music"}` y marca favoritas con `{t: "musicFav", track}`;
el servidor contesta solo a ese móvil con `{t: "music", tracks, favorites}`. Al acabar una canción la
tele envía `{t: "ended", track, play}` (`play` = `trackPlay`, que sube en cada cambio): el servidor
elige otra al azar (`MusicLibrary.pick_next`) y la publica en el siguiente `state`; si varias teles
avisan a la vez, solo cuenta la primera. `musicVolume` (0-100) escala solo el bus de música. Solo suena
la tele: `web/js/tv.js` compara el estado anterior con el nuevo y decide qué efecto toca
(`soundCues`). Los ajustes `music`, `sfx` y `volume` viven en `Settings` del motor, los cambia el
anfitrión con el mensaje `settings` **en cualquier fase** (el resto de opciones solo en el lobby) y
llegan a la tele en cada `state`.

## Salidas, reconexión y pausa

- `Game.away` guarda a quien sale durante una partida (`Away`: jugador, motivo `left`/`kicked`,
  posición). `reclaim` (salió solo; lo reconoce el servidor por IP en `welcome.claimable` y el móvil
  confirma con `claim`), `readmit`, `forget_away` y `assign_away` son acciones del anfitrión.
- `Game.pause/unpause`: los relojes se congelan en `tick` y las vistas llevan `pausedAt` para que
  tele y móviles paren también su cuenta atrás (`freezeClock` en `ui.js`).
- Ausencia (`presence`, `_check_afk`): el móvil manda `ping` con `visible`; un cierre de conexión o un
  latido silencioso de `HEARTBEAT_TIMEOUT` s también cuentan. Pasados `AFK_GRACE` s se pausa solo.
- `Game.checkpoint` (`"save"`/`"clear"`) pide al servidor escribir o borrar `data/autoguardado.json`.
- Mensajes nuevos del móvil: `ping`, `pause`, `unpause`, `host`, `readmit`, `forget`, `assign`, `claim`.
