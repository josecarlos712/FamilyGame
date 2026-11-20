# Editor de preguntas

Herramienta aparte del juego para añadir preguntas pegando texto. Doble clic en **`editor.bat`**
(o `.venv\Scripts\python src\editor.py`): se abre en el navegador en `http://127.0.0.1:8766/`.
Solo escucha en este ordenador (escribe archivos y no tiene contraseña). Puede estar abierto
con el juego arrancado o parado.

1. Elige la **categoría** (o «Categoría nueva…»: nombre, icono y color; el archivo se crea al añadir).
2. Elige la **mecánica** de lo que vas a pegar. El recuadro «Formato de…» enseña cómo se escribe.
3. Pega las preguntas. Se revisan solas mientras escribes con el **mismo validador que el juego**:
   cada tarjeta enseña cómo quedará, la opción correcta, los errores y avisos, y el bloque TOML.
   Clic en una tarjeta selecciona sus líneas en el texto.
4. **Añadir N a «Categoría»** añade las válidas al final del archivo. Las que tienen errores no se
   añaden y se quedan en el cuadro de texto para corregirlas.
5. En el juego, pulsa **«Recargar preguntas»** en el lobby (o reinícialo).

Antes de escribir, el editor copia el archivo en `data/editor_copias/` y, después, lo vuelve a leer
con el cargador del juego; si algo no cuadra, restaura la copia. Las preguntas se añaden al final con
un comentario `# --- Añadidas con el editor el <fecha> ---`, sin tocar lo que ya había.

Se rechazan las preguntas cuyo enunciado ya existe en cualquier categoría (sin mirar mayúsculas ni
tildes) o que se repiten dentro del texto pegado. El texto se guarda como borrador en el navegador.
«Copiar guía completa» copia este formato para todas las mecánicas, por si lo quieres pegar en un chat.

## Formato

Un **bloque por pregunta**, separados por una línea en blanco (o `---`).

- La **primera línea** sin clave es el **enunciado** (puede seguir en la línea siguiente).
- Las líneas `clave: valor` son campos. Una línea sin clave continúa el campo anterior.
- `- texto` es una opción; `+ texto` la correcta (en las mecánicas con opciones).
- Las líneas que empiezan por `#` son comentarios.
- Las claves no distinguen mayúsculas ni tildes (`Explicación:` = `explicacion:`).
- Números con coma o punto decimal (`36,6` o `36.6`). **Sin punto de miles**: `1000000` o
  `1 000 000` (`1.000` se leería como 1).

### Campos comunes (todas las mecánicas, opcionales)

| Clave | Ejemplo | Qué es |
|---|---|---|
| `tiempo` | `tiempo: 15` | segundos para responder (2-300) |
| `lectura` | `lectura: 2` | segundos de lectura antes de poder responder |
| `dificultad` | `dificultad: 2` | 1, 2 o 3 (100, 150 o 200 puntos) |
| `puntos` | `puntos: 300` | puntos exactos (sustituye a la dificultad) |
| `explicacion` | `explicacion: Dato curioso…` | se enseña al revelar (máx. 400 caracteres) |
| `imagen` | `imagen: img/torre.jpg` | ruta dentro de `preguntas/` |
| `id` | `id: colon-1492` | identificador fijo (opcional) |
| `tipo` | `tipo: mapa` | cambia la mecánica de este bloque |

Un bloque que **solo** tiene `tipo: …` cambia la mecánica de todos los bloques siguientes, así se
pueden mezclar mecánicas en un mismo pegado.

### Tipo test

```
¿En qué año llegó Colón a América?
- 1453
+ 1492
- 1512
- 1588
tiempo: 10
explicacion: Llegó a la isla de Guanahaní el 12 de octubre.

¿El Sol es una estrella?
+ Verdadero
- Falso
barajar: no
```

De 2 a 8 opciones, exactamente una con `+` (o `correcta: 2` con su número). `barajar: no` mantiene
el orden.

### Slider (un número)

```
¿Cuántos metros mide el Everest?
respuesta: 8849
escala: 5000 - 10000
paso: 10
unidad: m
tolerancia: 3%
```

`escala: desde - hasta` (o `min:` y `max:`), `respuesta:` dentro de la escala, `tolerancia: 2`
(absoluta) o `tolerancia: 10%` (de la respuesta); sin tolerancia solo vale el valor exacto.
Opcionales: `paso` (1), `unidad`, `inicio` (dónde empieza el selector).

### Doble slider (rango)

```
¿Entre qué años duró la Guerra Civil española?
respuesta: 1936 - 1939
escala: 1900 - 1960
criterio: coincidir
margen: 0
```

`criterio`: `solapar` (por defecto; `solape: 50%` mínimo de intersección ÷ unión), `contener`
(`ancho: 20`, ancho máximo del rango del jugador) o `coincidir` (`margen: 1` en cada extremo).
Los rangos se escriben `desde - hasta`, `desde a hasta` o `desde..hasta`.

### Mapa

```
Señala dónde está la Torre Eiffel
punto: 48.8584, 2.2945
radio: 25 km
vista: 46, 2, 5

Toca dentro de la isla de Mallorca
zona:
39.96, 2.80
39.92, 3.20
39.30, 3.20
vista: 40, 2, 6
```

`punto: lat, lng` + `radio:` (en `km` o `m`; sin unidad, metros), o `zona:` con 3 o más puntos
(uno por línea, o separados por `;`). `vista: lat, lng, zoom` es opcional. Las coordenadas llevan
punto decimal (como las copia Google Maps con clic derecho).

### ¿Lo conoces?

```
¿Qué plato prefiere?
- Paella
- Tortilla de patatas
- Cocido
- Pizza
```

De 2 a 6 opciones, todas con `-` (no hay correcta). Enunciado en tercera persona y sin nombres.

## Para tipos nuevos

Cada mecánica describe su formato en `question_types/<tipo>/editor.py` (ver
`question_types/_plantilla/editor.py` y [tipos-de-pregunta.md](tipos-de-pregunta.md)). Un tipo sin
`editor.py` usa un formato genérico: cada `clave: valor` pasa tal cual al archivo y las líneas
`- opción` van a `opciones`.
