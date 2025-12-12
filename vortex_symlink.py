from __future__ import annotations

import logging
import shutil
from pathlib import Path

from vortextricks import InstalledGame

# Configure module logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.propagate = False


def _safe_symlink(target: Path, link_path: Path) -> None:
    """Create or replace a symlink safely."""
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink(missing_ok=True)
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target)
    logger.info("Linked %s -> %s", link_path, target)


def create_game_symlinks(
    game: InstalledGame,
    vortex_prefix: Path,
    game_prefix: Path,
    username: str
) -> None:
    """
    Create symlinks inside the Vortex Wine prefix that point to the game's save folder and AppData folder.

    Parameters
    ----------
    game : InstalledGame
        The `InstalledGame` object representing the game to create symlinks for.
    vortex_prefix : Path
        Path to the root of the Vortex Wine prefix.
    game_prefix : Path
        Path to the game's Proton prefix.
    username : str
        Linux username (used for building Vortex prefix paths).
    """
    if not game_prefix.is_dir():
        logger.warning("No Proton prefix found for %s at %s", game.name, game_prefix)
        return

    game_user = "steamuser"  # Proton prefixes always use this by default
    mygames = game.override_mygames or game.game_path.name
    appdata = game.override_appdata or game.game_path.name

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

    logger.info("Symlinks successfully created for %s", game.name)


__all__ = ["create_game_symlinks"]
