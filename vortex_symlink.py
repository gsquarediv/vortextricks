from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Configure module logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.propagate = False


@dataclass(frozen=True)
class GameInfo:
    """Metadata about a supported game."""
    name: str
    app_id: str
    game_dir: str
    override_mygames: Optional[str] = None
    override_appdata: Optional[str] = None


# === Known games ===
GAMES: dict[str, GameInfo] = {
    "489830": GameInfo("Skyrim Special Edition", "489830", "Skyrim Special Edition"),
    "72850": GameInfo("Skyrim", "72850", "Skyrim"),
    "22330": GameInfo("Oblivion", "22330", "Oblivion"),
    "377160": GameInfo(
        "Fallout 4", "377160", "Fallout 4",
        override_mygames="Fallout4", override_appdata="Fallout4"
    ),
    "22370": GameInfo(
        "Fallout 3 GOTY", "22370", "Fallout 3 goty",
        override_mygames="Fallout3", override_appdata="Fallout3"
    ),
    "22300": GameInfo("Fallout 3", "22300", "Fallout 3"),
    "22380": GameInfo(
        "Fallout New Vegas", "22380", "Fallout New Vegas",
        override_mygames="FalloutNV", override_appdata="FalloutNV"
    ),
    "22320": GameInfo("Morrowind", "22320", "Morrowind"),
}


def _safe_symlink(target: Path, link_path: Path) -> None:
    """Create or replace a symlink safely."""
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink(missing_ok=True)
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target)
    logger.info(f"Linked {link_path} -> {target}")


def create_game_symlinks(
    app_id: str,
    vortex_prefix: Path,
    game_prefix: Path,
    username: str
) -> None:
    """
    Create symlinks inside the Vortex Wine prefix that point to the game's save folder and AppData folder.

    Parameters
    ----------
    app_id : str
        Steam App ID (e.g., "489830" for Skyrim SE).
    vortex_prefix : Path
        Path to the root of the Vortex Wine prefix.
    game_prefix : Path
        Path to the game's Proton prefix.
    username : str
        Linux username (used for building Vortex prefix paths).
    """
    game = GAMES.get(app_id)
    if not game:
        raise ValueError(f"Unknown App ID: {app_id}")

    if not game_prefix.is_dir():
        logger.warning(f"No Proton prefix found for {game.name} at {game_prefix}")
        return

    game_user = "steamuser"  # Proton prefixes always use this by default
    mygames = game.override_mygames or game.game_dir
    appdata = game.override_appdata or game.game_dir

    # Target directories inside Proton prefix
    proton_my_games = game_prefix / "drive_c" / "users" / game_user / "Documents" / "My Games" / mygames
    proton_appdata = game_prefix / "drive_c" / "users" / game_user / "AppData" / "Local" / appdata

    # Destination directories inside Vortex prefix
    vortex_user_root = vortex_prefix / "drive_c" / "users" / username
    vortex_my_games = vortex_user_root / "Documents" / "My Games" / mygames
    vortex_appdata = vortex_user_root / "AppData" / "Local" / appdata

    # Ensure Vortex folder structure exists
    for directory in [
        vortex_user_root / "Documents" / "My Games",
        vortex_user_root / "AppData" / "Local"
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    # Create symlinks
    _safe_symlink(proton_my_games, vortex_my_games)
    _safe_symlink(proton_appdata, vortex_appdata)

    logger.info(f"Symlinks successfully created for {game.name}")


__all__ = ["GameInfo", "GAMES", "create_game_symlinks"]
