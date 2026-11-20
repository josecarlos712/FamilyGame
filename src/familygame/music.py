"""Background music the host can pick: the files in ``musica/`` plus the built-in synthesised tune.

A track is identified by its path relative to the folder, with forward slashes
(``"Bandas sonoras/tema.mp3"``). The empty string is the built-in tune, which has no file.
Favourites and the last track picked live in a small JSON file under ``data/``.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BUILT_IN = ""
BUILT_IN_NAME = "Melodía tranquila (de serie)"
AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}
MAX_FAVORITES = 500


def track_name(track: str) -> str:
    """Readable title of a track: the file name without extension, underscores as spaces."""
    if track == BUILT_IN:
        return BUILT_IN_NAME
    stem = Path(track).stem.replace("_", " ").strip()
    return stem or track


def _sort_key(text: str) -> str:
    """Case- and accent-insensitive key, so «Álbum» sorts next to «album», not after «zeta»."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _folder_of(track: str) -> str:
    parent = Path(track).parent.as_posix()
    return "" if parent == "." else parent


class MusicLibrary:
    """Lists the music folder and remembers the host's favourites.

    Args:
        folder: Folder with the audio files (may not exist yet).
        store: JSON file where favourites and the last track are kept.
    """

    def __init__(self, folder: Path, store: Path) -> None:
        self.folder = folder
        self.store = store
        self.favorites: list[str] = []
        self.last_track = BUILT_IN
        self._load()

    # ------------------------------------------------------------------ files

    def tracks(self) -> list[str]:
        """Every audio file in the folder (subfolders included), sorted by title, built-in first."""
        found: list[str] = []
        if self.folder.is_dir():
            try:
                for path in self.folder.rglob("*"):
                    if path.suffix.lower() in AUDIO_TYPES and path.is_file():
                        found.append(path.relative_to(self.folder).as_posix())
            except OSError as exc:
                log.warning("No se pudo leer la carpeta de música: %s", exc)
        found.sort(key=lambda t: (_sort_key(track_name(t)), _sort_key(t)))
        return [BUILT_IN, *found]

    def exists(self, track: str) -> bool:
        """Is ``track`` the built-in tune or an audio file inside the folder?"""
        if track == BUILT_IN:
            return True
        return self.file_for(track) is not None

    def file_for(self, track: str) -> Path | None:
        """The file behind ``track``, or None if it is not an audio file inside the folder."""
        if not track or Path(track).suffix.lower() not in AUDIO_TYPES:
            return None
        try:
            base = self.folder.resolve()
            target = (base / track).resolve()
        except (OSError, ValueError):
            return None
        if base not in target.parents or not target.is_file():
            return None
        return target

    def listing(self) -> dict[str, Any]:
        """What the host's phone shows: every track with its title, and the favourites."""
        tracks = self.tracks()
        present = set(tracks)
        return {
            "tracks": [{"id": t, "name": track_name(t), "folder": _folder_of(t)} for t in tracks],
            "favorites": [f for f in self.favorites if f in present],
        }

    # ------------------------------------------------------------------ state

    def toggle_favorite(self, track: str) -> bool:
        """Mark or unmark ``track`` as a favourite; returns whether it is one now.

        Raises:
            ValueError: If the track does not exist.
        """
        if not self.exists(track):
            raise ValueError("Esa canción ya no está en la carpeta")
        if track in self.favorites:
            self.favorites.remove(track)
            now = False
        else:
            self.favorites = [track, *self.favorites][:MAX_FAVORITES]
            now = True
        self._save()
        return now

    def remember(self, track: str) -> None:
        """Keep the last track picked so it plays again next time the server starts."""
        if track != self.last_track:
            self.last_track = track
            self._save()

    def _load(self) -> None:
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("No se pudieron leer los favoritos de música: %s", exc)
            return
        if not isinstance(data, dict):
            return
        favorites = data.get("favorites")
        if isinstance(favorites, list):
            self.favorites = [f for f in favorites if isinstance(f, str)][:MAX_FAVORITES]
        last = data.get("track")
        if isinstance(last, str) and self.exists(last):
            self.last_track = last

    def _save(self) -> None:
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.store.with_suffix(".tmp")
            tmp.write_text(json.dumps({"favorites": self.favorites, "track": self.last_track},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.store)
        except OSError as exc:
            log.warning("No se pudieron guardar los favoritos de música: %s", exc)
