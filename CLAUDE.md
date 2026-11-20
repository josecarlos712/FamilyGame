# FamilyGame

Trivial familiar: tele (`/tv`) + móviles (`/`) en la red local. Python 3.15, Starlette/Uvicorn,
frontend JS sin compilar.

## Comandos

- Arrancar: `iniciar.bat` o `.venv\Scripts\python src\main.py [--puerto N] [--sin-internet]`
- Tests: `.venv\Scripts\python -m pytest`
- Vista previa: `.claude/launch.json` (configuración `familygame`, puerto 8000)

## Mapa del código

- Motor puro y testeable: `src/familygame/game/engine.py` (recibe `now`, sin E/S).
- Tipos de pregunta = plugins en `question_types/<tipo>/` (`type.py` + `tv.js` + `phone.js`).
- Categorías = archivos `preguntas/*.toml` (los que empiezan por `_` se ignoran).
- Documentación: `docs/preguntas.md`, `docs/tipos-de-pregunta.md`, `docs/arquitectura.md`.

## Reglas

- No meter lógica de un tipo concreto en el motor ni en las pantallas: va en su carpeta.
- Nada de `innerHTML` con datos de jugadores o archivos: usar `h()` de `web/js/ui.js`.
- `style` con variables CSS: `h()` usa `setProperty` (Object.assign no sirve para `--var`).
- Probar partidas con bots: un script que se conecte a `/ws/phone`, haga `hello` + `join` y responda.
