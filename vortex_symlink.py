"""
Utilities for creating symbolic links between a Proton prefix and a Vortex WINE
prefix.

The module defines two main helpers:

* ``_safe_symlink(target, link_path)`` - Creates or replaces a symlink
  safely, handling existing files or directories.
* ``create_game_symlinks(game, vortex_prefix, game_prefix)`` - For a
  given :class:`InstalledGame` instance, this function creates symlinks that
  point the Vortex WINE installation to the corresponding save-game
  (``My Games``) and ``AppData`` directories inside the Proton
  prefix. It ensures the destination directories exist and logs
  informative messages.
* ``get_sorting_title(gog_id)`` - Fetch a GOG sorting title for a given GOG release ID from
  the GOG GamesDB API.  Used to build the prefix folder for GOG games installed through
  Heroic.

These utilities are used to keep game saves and configuration files in sync
between Proton and the Vortex WINE environment.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import requests

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
    link_path.symlink_to(target, target_is_directory=target.is_dir())
    logger.info("Linked %s -> %s", link_path, target)


def create_game_symlinks(
    game: InstalledGame,
    vortex_prefix: Path,
    game_prefix: Path,
    vortex_user: str | None = os.environ.get("USER")
) -> None:
    """
    Create symlinks inside the Vortex Wine prefix that point to the game's save folder and
    AppData folder.

    Parameters
    ----------
    game : InstalledGame
        The `InstalledGame` object representing the game to create symlinks for.
    vortex_prefix : Path
        Path to the root of the Vortex Wine prefix.
    game_prefix : Path
        Path to the game's Proton prefix.
    vortex_user : str, optional
        The username under which Vortex runs. Defaults to the current
        environment user.
    """
    if vortex_user is None:
        raise RuntimeError("Could not ascertain Vortex user")

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
    vortex_user_root = vortex_prefix / "drive_c" / "users" / vortex_user
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

def get_sorting_title(gog_id: str, locale: str = "en-US") -> str | None:
    """
    Fetches the sorting_title for a given GOG ID from the GamesDB endpoint.

    Args:
        gog_id (str): The external GOG release ID (e.g. "1454587428").
        locale (str): Locale for sorting_title (default "en-US").

    Returns:
        str | None: The sorting title if found, otherwise None.
    """
    url = f"https://gamesdb.gog.com/platforms/gog/external_releases/{gog_id}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Try locale-specific field first
        sorting = data.get("sorting_title", {})
        if isinstance(sorting, dict):
            # Return locale-specific if available, otherwise fallback to '*' or any str
            return sorting.get(locale) or sorting.get("*") or None

        # If not a dict, just return it directly
        return sorting if sorting else None

    except (requests.RequestException, ValueError):
        logger.exception("Error fetching sorting_title from gog.com")
        return None


__all__ = ["create_game_symlinks", "get_sorting_title"]
