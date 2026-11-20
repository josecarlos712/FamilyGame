"""Music folder: listing, safety and favourites."""

from __future__ import annotations

from pathlib import Path

import pytest

from familygame.music import BUILT_IN, MusicLibrary, track_name


@pytest.fixture
def library(tmp_path: Path) -> MusicLibrary:
    folder = tmp_path / "musica"
    (folder / "Pelis").mkdir(parents=True)
    (folder / "zeta.ogg").write_bytes(b"x")
    (folder / "Pelis" / "Álbum_uno.MP3").write_bytes(b"x")
    (folder / "portada.jpg").write_bytes(b"x")
    (tmp_path / "fuera.mp3").write_bytes(b"x")
    return MusicLibrary(folder, tmp_path / "data" / "musica.json")


def test_lists_audio_files_with_the_built_in_tune_first(library: MusicLibrary) -> None:
    assert library.tracks() == [BUILT_IN, "Pelis/Álbum_uno.MP3", "zeta.ogg"]
    listing = library.listing()
    assert listing["tracks"][1] == {"id": "Pelis/Álbum_uno.MP3", "name": "Álbum uno", "folder": "Pelis"}
    assert listing["tracks"][2]["folder"] == ""
    assert track_name(BUILT_IN).startswith("Melodía")


def test_only_audio_inside_the_folder_is_reachable(library: MusicLibrary) -> None:
    assert library.exists("zeta.ogg") and library.exists(BUILT_IN)
    assert not library.exists("portada.jpg")
    assert not library.exists("../fuera.mp3")
    assert not library.exists("no_existe.mp3")
    assert library.file_for(BUILT_IN) is None


def test_favourites_and_last_track_survive_a_restart(library: MusicLibrary, tmp_path: Path) -> None:
    assert library.toggle_favorite("zeta.ogg") is True
    assert library.toggle_favorite(BUILT_IN) is True
    assert library.toggle_favorite("zeta.ogg") is False
    library.remember("Pelis/Álbum_uno.MP3")
    with pytest.raises(ValueError):
        library.toggle_favorite("no_existe.mp3")
    again = MusicLibrary(library.folder, library.store)
    assert again.favorites == [BUILT_IN] and again.last_track == "Pelis/Álbum_uno.MP3"


def test_a_missing_or_broken_store_is_ignored(tmp_path: Path) -> None:
    store = tmp_path / "musica.json"
    store.write_text("{roto", encoding="utf-8")
    library = MusicLibrary(tmp_path / "no_hay_carpeta", store)
    assert library.tracks() == [BUILT_IN] and library.favorites == [] and library.last_track == BUILT_IN
