#!/usr/bin/env python3

"""
VortexTricks - Automate Vortex setup and game registration for Steam & GOG

This script performs the following high-level tasks:

1. **Detect installed game stores** - finds Steam and Heroic (GOG) installations.
2. **Enumerate installed games** - builds a mapping of app-IDs to `InstalledGame` objects.
3. **Resolve duplicate titles** - prompts the user to decide which copy of a game to keep
   (Steam vs. GOG) and optionally creates separate Bottles bottles.
4. **Create/locate WINE prefixes** - creates a Vortex-specific prefix when using vanilla
   WINE or Bottles.
5. **Register games inside Vortex** - writes registry entries and symlinks for each game.
6. **Install Vortex** - downloads the latest release from GitHub and installs it into the
   chosen prefix.

The module relies on several helper modules:

- `protontricks` - to locate the Steam installation.
- `vdf` - to parse Steam's `libraryfolders.vdf` and `appmanifest_*.acf` files.
- `gameinfo` - provides a registry of known games and their metadata.
- `vortex_symlink` - handles creation of game-specific symlinks.
- `requests` - for downloading the Vortex installer.
"""

from dataclasses import dataclass, field
import json
import logging
import os
import pathlib
import shutil
import subprocess
import urllib.parse
from enum import Enum
from typing import Optional

import protontricks
import requests
import vdf

import vortex_symlink
import gameinfo
from gameinfo import JSON_INDENT

class Store(Enum):
    """Enumeration of supported game distribution platforms.

    Represents the primary store platform for a game's distribution.
    Currently supports Steam and GOG, with potential for expansion.

    Attributes:
        STEAM: Represents Steam platform (App IDs in steamapp_ids)
        GOG: Represents GOG/heroic platform (IDs in gog_id)
    """
    STEAM = "Steam"
    GOG = "GOG"

@dataclass
class InstalledGame(gameinfo.GameInfo):
    """Represents an installed game, combining game information with its installation path.
    
    Extends GameInfo with the game's installation directory path for Vortex management.
    
    Attributes:
        game_path: The Path object pointing to the game's installation directory.
    """
    game_path: pathlib.Path = field(default_factory=pathlib.Path)

BOTTLES_PACKAGE = 'com.usebottles.bottles'

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)

os.environ['WINEDEBUG'] = 'fixme-all'

# Build the registry
with open('gameinfo.json', 'r', encoding='utf-8') as json_file:
    game_registry = gameinfo.load_games_from_json(json_file.read())

def main() -> None:
    """
    High-level orchestration of the Vortex setup workflow.

    Steps:
    1. Enumerate installed Steam/GOG games.
    2. Detect if the user is using Bottles or WINE.
    3. Create the Vortex prefix(es) if non-existant.
    4. Register the games inside the prefix.
    5. Ensure Vortex is installed; otherwise download & install it.
    """

    steam_path = find_steam()
    steam_games = {}
    heroic_path = find_heroic()
    gog_games = {}

    # ----------------------------------------------------------------------------------------------------- #
    # 1. Gather installed games
    # ----------------------------------------------------------------------------------------------------- #
    if steam_path is not None:
        steam_games = list_installed_steam_games(steam_path)
        logging.debug(steam_games)
    if heroic_path is not None:
        gog_games = list_installed_gog_games(heroic_path)
        logging.debug(gog_games)
    duplicates = find_duplicate_games(steam_games, gog_games)
    if duplicates:
        for game_id, (steam_app, gog_app) in duplicates.items():
            logging.warning("Duplicate game detected: %s (Steam=%s, GOG=%s)", game_id, steam_app, gog_app)

    # ----------------------------------------------------------------------------------------------------- #
    # 2. Determine prefix(es) to use for Vortex, create prefix(es) if necessary, and handle duplicate games
    # ----------------------------------------------------------------------------------------------------- #
    try:
        wine_command = detect_bottles()
        logging.info("Bottles CLI: %s", ' '.join(wine_command))
        if duplicates:
            steam_games, gog_games, bottle_names = handle_duplicates(duplicates, steam_games, gog_games, wine_command)
            bottles_path = get_bottles_path(wine_command)
            prefixes: dict[Store, pathlib.Path] = {
                store: bottles_path / bottle_names[store] for store in [Store.STEAM, Store.GOG]
            }
        else:
            # No duplicates – keep default bottle name mapping
            bottle_names = {Store.STEAM: "Vortex", Store.GOG: "Vortex"}
            if not is_existing_bottle(wine_command):
                logging.info("Creating default 'Vortex' bottle.")
                vortex_prefix = create_bottle(wine_command)
            else:
                vortex_prefix = get_bottles_path(wine_command) / 'Vortex'
            prefixes = {Store.STEAM: vortex_prefix, Store.GOG: vortex_prefix}
    except RuntimeError, subprocess.CalledProcessError:
        if shutil.which("wine") is None:
            if shutil.which("dnf"):
                command = ["sudo", "dnf", "install", "wine"]
                logging.info("WINE can be installed with the following command:\n%s", ' '.join(command))
            raise RuntimeError("Could not locate bottles-cli or wine")
        wine_command = ['wine']
        if duplicates:
            steam_games, gog_games, bottle_names = handle_duplicates(duplicates, steam_games, gog_games, wine_command)
        else:
            bottle_names = {Store.STEAM: "Vortex", Store.GOG: "Vortex"}
        vortex_prefix = find_vortex_prefix()
        prefixes = {Store.STEAM: vortex_prefix, Store.GOG: vortex_prefix}
        create_wine_prefix()

    # ----------------------------------------------------------------------------------------------------- #
    # 3. Register games inside the prefix(es)
    # ----------------------------------------------------------------------------------------------------- #
    for store in [Store.STEAM, Store.GOG]:
        store_library = gog_games if store == Store.GOG else steam_games
        if store_library:
            configure_vortex_environment(wine_command, store, store_library, prefixes[store], bottle_names[store])

    # ----------------------------------------------------------------------------------------------------- #
    # 4. Install Vortex into the prefix(es) that are used
    # ----------------------------------------------------------------------------------------------------- #
    if using_bottles(wine_command):
        bottles_path = get_bottles_path(wine_command)
        temp_dir = bottles_path.parent.joinpath("temp")
        for bottle_name in set(bottle_names.values()):
            programs = run(wine_command + ["--json", "programs", "-b", bottle_name], check=True, capture_output=True).stdout.decode("utf-8")
            if "Vortex.exe" not in programs:
                temp_dir.mkdir(parents=True, exist_ok=True)
                vortex_installer_path = download_vortex(temp_dir)
                install_program(wine_command, vortex_installer_path, bottle_name)
    elif not pathlib.Path(pathlib.Path(os.environ['WINEPREFIX']) / "drive_c/Program Files/Black Tree Gaming Ltd/Vortex/Vortex.exe").exists():
        temp_dir = pathlib.Path("/tmp")
        vortex_installer_path = download_vortex(temp_dir)
        install_program(wine_command, vortex_installer_path)
        # Modify shortcut to add NXM mimetype for Vortex integration with web browsers on nexusmods.com
        shortcut_path = pathlib.Path.home() / ".local" / "share" / "applications" / "wine" / "Programs" / "Black Tree Gaming Ltd" / "Vortex.desktop"
        with open(shortcut_path, "a", encoding="utf-8") as file:
            file.write("Categories=Game;\n")
            file.write("MimeType=x-scheme-handler/nxm;x-scheme-handler/nxm-protocol\n")
        run(["sudo", "update-desktop-database"], check=False)

def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Wrap subprocess.run() and automatically inject `run` for proton binaries."""
    # Expand user (~) and environment vars
    command = os.path.expanduser(args[0])
    command = os.path.expandvars(command)

    if os.path.basename(command).endswith("proton") and (len(args) == 1 or args[1] != "run"):
        # Inject 'run' if executable ends with 'proton'
        args = [command, "run", *args[1:]]
    elif command == "sudo" and shutil.which("sudo-rs"):
        # Prefer sudo-rs if available
        args = ["sudo-rs", *args[1:]]
    else:
        args = [command, *args[1:]]

    logging.debug("Running: %s", " ".join(args))
    return subprocess.run(args, **kwargs)

def detect_bottles() -> list[str]:
    """Return the first found bottles CLI or raise an exception."""
    if shutil.which("bottles-cli") is not None:
        return ["bottles-cli"]
    elif shutil.which("flatpak") is not None:
        bottles_command = ["flatpak", "run", "--command=bottles-cli", BOTTLES_PACKAGE]
        if run(bottles_command + ["info", "health-check"], check=True, capture_output=True):
            return bottles_command
        else:
            raise RuntimeError("Could not locate bottles-cli")
    else:
        raise RuntimeError("Could not locate bottles-cli or flatpak")

def using_bottles(wine_command: list[str]) -> bool:
    """Return whether the given command uses bottles."""
    return "bottles-cli" in wine_command or "--command=bottles-cli" in wine_command

def is_existing_bottle(bottles_command: list[str], bottle_name: str = "Vortex") -> bool:
    """
    Check if a specific game bottle exists in Vortex's configuration.
    
    Executes the provided command with --json flag to list bottles, parses the JSON output,
    and verifies if the specified bottle name exists in the configuration.
    
    Parameters:
        bottles_command (list[str]): Base command to interact with Vortex (e.g., ['vortex', 'bottles'])
        bottle_name (str, optional): Name of the bottle to check, defaults to "Vortex"
        
    Returns:
        bool: True if the bottle exists, False otherwise
    """
    bottles = json.loads(run(bottles_command + ["--json", "list", "bottles"], check=True, capture_output=True).stdout)
    bottle = bottles.get(bottle_name)
    if bottle is not None:
        logging.debug(json.dumps(bottle, indent=JSON_INDENT))
        return True
    else:
        return False

def create_bottle(bottles_command: list[str], bottle_name: str = "Vortex") -> pathlib.Path:
    """
    Create a new game bottle with the appropriate runner configuration.
    
    Selects either the sys-wine runner or a default runner based on available components,
    then creates a new bottle with the specified name.
    
    Args:
        bottles_command: List of command-line arguments for the bottles tool.
        bottle_name: Name of the new bottle (default: "Vortex").
        
    Returns:
        Path object pointing to the created bottle's directory.
    """
    fix_bottles_permissions()
    components = json.loads(run(bottles_command + ["--json", "list", "components"], check=True, capture_output=True).stdout)
    logging.debug(json.dumps(components, indent=JSON_INDENT))
    runners = components.get('runners')

    sys_wine_entry = next(
        (runner for runner in runners if runner.startswith("sys-wine")),
        None
    )
    if sys_wine_entry is not None:
        run(bottles_command + ["new", "--bottle-name", bottle_name, "--environment", "application", "--runner", sys_wine_entry], check=True)
    else:
        logging.warning("No sys-wine runner found.  Using default runner.")
        run(bottles_command + ["new", "--bottle-name", bottle_name, "--environment", "application"], check=True)

    return pathlib.Path(get_bottles_path(bottles_command)) / bottle_name

def find_vortex_prefix() -> pathlib.Path:
    """
    Locate or create the WINEPREFIX directory for Vortex Wine configuration.
    
    Checks if the 'WINEPREFIX' environment variable is set. If not, 
    defaults to creating a directory at $HOME/Games/vortex/pfx. 
    Returns the Path object for the configured WINEPREFIX.
    
    Returns:
        pathlib.Path: The absolute path to the Vortex Wine prefix directory
    """
    if 'WINEPREFIX' not in os.environ:
        os.environ['WINEPREFIX'] = str(pathlib.Path.home() / 'Games/vortex/pfx')
    return pathlib.Path(os.environ['WINEPREFIX'])

def find_steam() -> pathlib.Path | None:
    """Locate the Steam installation path using protontricks utility.
    
    Returns:
        pathlib.Path: The absolute path to the Steam installation directory if found
        None: If Steam cannot be located by protontricks
    
    Note:
        Relies on protontricks.find_steam_path() to determine the path
    """
    return protontricks.find_steam_path()[0]

def find_heroic() -> pathlib.Path | None:
    """
    Locate the Heroic games launcher configuration directory.

    Searches for the default configuration path used by the Heroic games
    launcher (now part of GOG's platform). Returns the path if it exists,
    otherwise returns None.

    The default path is constructed as:
    ~/.var/app/com.heroicgameslauncher.hgl/config/heroic

    This is used to locate game-specific configuration files for GOG games
    managed through the Heroic launcher.
    """
    path = pathlib.Path.home() / ".var/app/com.heroicgameslauncher.hgl/config/heroic"
    if pathlib.Path.exists(path):
        return path

def create_wine_prefix(proton_path: str | None = None) -> subprocess.CompletedProcess:
    """
    Creates the WINEPREFIX directory and initializes Wine configuration.
    
    Ensures the WINEPREFIX environment directory exists, then executes
    `wineboot -u` to initialize Wine. If proton_path is provided, it uses
    that executable instead of the default Wine binary.
    
    Parameters:
        proton_path (str | None): Optional path to Proton/Wine executable
    
    Returns:
        subprocess.CompletedProcess: Result of the wineboot command execution
    """
    os.makedirs(os.environ['WINEPREFIX'], exist_ok=True)
    if proton_path is None:
        return run(["wineboot", "-u"], check=True)
    else:
        return run([proton_path, "wineboot", "-u"], check=True)

def configure_vortex_environment(wine_command: list[str], store: Store, library: dict[str, InstalledGame], vortex_prefix: pathlib.Path, bottle_name: str = "Vortex") -> None:
    """
    Register the games that are already in the user's library inside the Vortex
    bottle.  `library` is the dict returned by ``list_installed_*_games`` - it
    maps an app-id to an ``InstalledGame`` instance.
    Raises:
       ValueError:
    """
    for app_id, installed_game in library.items():
        # Look up the game metadata in the registry
        game = game_registry.get_game_by_id(app_id)
        if game is None:
            logging.warning("Game %s not found in registry", app_id)
            continue

        # Verify that the app‑id actually belongs to this game
        if store == Store.STEAM and app_id not in game.steamapp_ids:
            continue
        if store == Store.GOG and app_id not in (game.gog_id or []):
            continue

        logging.info("Found game %s (appid=%s)", game.game_id, app_id)

        # Add all registry entries
        for key, value in game.registry_entries.items():
            # Convert the Unix path to a Windows‑style path that Vortex expects
            win_path = pathlib.PureWindowsPath("z:", pathlib.PurePosixPath(installed_game.game_path))
            logging.info("Adding registry entry: %s -> %s\\%s", win_path, key, value)
            add_registry_entry(wine_command, key, value, win_path, bottle_name)

        # Create the game‑specific symlinks when we’re dealing with Steam
        if store == Store.STEAM:
            vortex_symlink.create_game_symlinks(
                game=installed_game,
                vortex_prefix=vortex_prefix,
                game_prefix=pathlib.Path.home() / f'.local/share/Steam/steamapps/compatdata/{app_id}/pfx')
        elif store == Store.GOG:
            if installed_game.gog_id:
                folder_name = vortex_symlink.get_sorting_title(installed_game.gog_id)
                if folder_name:
                    vortex_symlink.create_game_symlinks(
                        game=installed_game,
                        vortex_prefix=vortex_prefix,
                        game_prefix=pathlib.Path.home() / "Games" / "Heroic" / "Prefixes" / "default" / folder_name)
            else:
                raise ValueError("Missing GOG ID")

def list_installed_steam_games(steam_path: pathlib.Path) -> dict[str, InstalledGame]:
    """
    Returns a list of installed Steam games (name, appid, and install path).

    Parameters:
        steam_path (Path): Steam root path.

    Returns:
        list[dict]: A list of dicts with keys: name, appid, and path.
    """
    steamapps = steam_path / "steamapps"
    if not steamapps.exists():
        raise FileNotFoundError(f"Steam path not found: {steamapps}")

    # --- Read libraryfolders.vdf to find all Steam library locations ---
    libraries = set()
    lib_file = steamapps / "libraryfolders.vdf"
    if lib_file.exists():
        with lib_file.open(encoding="utf-8") as file:
            data = vdf.load(file)
            libraries_section = data.get("libraryfolders", data)

            for key, entry in libraries_section.items():
                # Handle both modern and legacy formats
                if isinstance(entry, dict):
                    path = entry.get("path") or entry.get("contentid")
                    if not path and "apps" in entry:  # fallback if weird structure
                        path = key
                    if path:
                        path = pathlib.Path(path) / "steamapps"
                        if path.exists():
                            libraries.add(path)
                elif isinstance(entry, str) and pathlib.Path(entry).exists():
                    libraries.add(pathlib.Path(entry) / "steamapps")

    # Always ensure the main steamapps folder is included
    libraries.add(steamapps)

    # --- Find all installed games ---
    games = {}
    moddable_games = {}
    for lib in libraries:
        for app_manifest in lib.glob("appmanifest_*.acf"):
            try:
                data = vdf.load(app_manifest.open(encoding="utf-8"))
                appid = data["AppState"]["appid"]
                name = data["AppState"]["name"]
                installdir = data["AppState"]["installdir"]
                install_path = lib / "common" / installdir
                # Use appid as a unique key to prevent duplicates
                games[appid] = {
                    "name": name,
                    "appid": appid,
                    "path": str(install_path)
                }
                game = game_registry.get_game_by_id(appid)
                if game:
                    moddable_games.update({appid: InstalledGame(name=game.name, game_id=game.game_id, steamapp_ids=[appid], gog_id=game.gog_id, ms_id=game.ms_id, epic_id=game.epic_id, registry_entries=game.registry_entries, game_path = install_path, override_appdata=game.override_appdata, override_mygames=game.override_mygames)})
            except Exception as e:
                logging.error(e)
                continue

    logging.debug(json.dumps(list(games.values()), indent=JSON_INDENT))
    return moddable_games

def list_installed_gog_games(heroic_path: pathlib.Path) -> dict[str, InstalledGame]:
    """
    List all installed GOG games managed by Heroic (Flatpak).
    """
    gog_store_path = heroic_path / "gog_store" / "installed.json"

    if not gog_store_path.exists():
        raise FileNotFoundError(f"GOG installed.json not found: {gog_store_path}")

    with gog_store_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    installed_section = data.get("installed", [])
    if not isinstance(installed_section, list):
        raise TypeError(f"Expected 'installed' to be a list, got {type(installed_section).__name__}")

    games = []
    moddable_games = {}
    for entry in installed_section:
        if not isinstance(entry, dict):
            continue

        install_path = pathlib.Path(entry.get("install_path", ""))
        name = install_path.name if install_path else entry.get("appName", "Unknown")
        appid = entry.get("appName") or name

        games.append({
            "appid": appid,
            "name": name,
            "path": str(install_path),
            "platform": entry.get("platform"),
            "version": entry.get("version"),
        })

        game = game_registry.get_game_by_id(appid)
        if game:
            moddable_games.update({appid: InstalledGame(name=game.name, game_id=game.game_id, steamapp_ids=game.steamapp_ids, gog_id=appid, ms_id=game.ms_id, epic_id=game.epic_id, registry_entries=game.registry_entries, game_path = install_path, override_appdata=game.override_appdata, override_mygames=game.override_mygames)})

    logging.debug(json.dumps(games, indent=JSON_INDENT))
    return moddable_games

def add_registry_entry(wine_command: list[str], key: str, value: str, data: pathlib.PureWindowsPath, bottle_name: str = "Vortex") -> subprocess.CompletedProcess:
    """
    Adds a registry entry using Wine's reg command, handling both bottled and non-bottled environments.
    
    Constructs and executes a registry add command via Wine, supporting:
    - Bottled environments with specified bottle name
    - Non-bottled environments
    
    Parameters:
        wine_command: Base Wine command list for execution
        key: Registry key path (e.g., "HKEY_CURRENT_USER\\Software")
        value: Registry value name
        data: Registry data path (Windows-style path string)
        bottle_name: Name of the wine bottle to use (default: "Vortex")
    
    Returns:
        subprocess.CompletedProcess: Result of the registry operation
    """
    if using_bottles(wine_command):
        result = run(wine_command + ["reg", "-b", bottle_name, "-k",
                                   key, "-v", value, "-d",
                                   str(data), "-t", "REG_SZ", "add"], check=True, capture_output=True)
    else:
        result = run(wine_command + ["reg", "add",
                                   key,
                                   "/t", "REG_SZ", "/v", value, "/d",
                                   str(data)], check=True)
    return result

def download(url: str | bytes, destination: pathlib.Path) -> pathlib.Path:
    """Download a file from a URL using requests."""
    logging.info("Downloading %s to %s", url, destination)
    response = requests.get(url, stream=True, timeout=10)
    response.raise_for_status()
    if destination.is_dir():
        destination = destination / urllib.parse.urlparse(response.url).path.split("/")[-1]
    with open(destination, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    return destination

def download_vortex(directory: pathlib.Path, version: str | None = None) -> pathlib.Path:
    """
    Download the latest Vortex setup executable from GitHub releases.
    
    Fetches the latest release tag from the Nexus-Mods/Vortex repository,
    constructs the download URL for the Windows installer, and saves it
    to the specified directory with a filename formatted as:
    vortex-setup-{tag_version}.exe
    
    Parameters:
        directory (Path): Target directory for saving the downloaded file
        version (str, optional): Specific version to download. If None, fetches latest
        
    Returns:
        Path: Absolute path to the downloaded Vortex setup executable
        
    Raises:
        requests.exceptions.RequestException: If API request fails or network error occurs
        ValueError: If required release information is missing from the API response
    """
    if version is None:
        logging.info("Fetching latest Vortex release from GitHub...")
        api_url = "https://api.github.com/repos/Nexus-Mods/Vortex/releases/latest"
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        release = response.json()
        tag_version = release.get("tag_name")
        logging.info("Latest tag: %s", tag_version)
    else:
        tag_version = version
    filename = f"vortex-setup-{tag_version.lstrip('v')}.exe"
    download_url = f"https://github.com/Nexus-Mods/Vortex/releases/download/{tag_version}/{filename}"
    path = directory.joinpath(filename)
    download(download_url, path)
    return path

def install_program(wine_command: list[str], installer_path: pathlib.Path, bottle_name: str = "Vortex") -> subprocess.CompletedProcess:
    """Installs an application using WINE or Bottles."""
    if using_bottles(wine_command):
        result = run(wine_command + ["run", "-b", bottle_name, "-e", str(installer_path)], check=True)
    else:
        result = run(wine_command + [str(installer_path)], check=True)
    installer_path.unlink(missing_ok=True)
    return result

def fix_bottles_permissions() -> None:
    """
    Configure Bottles application permissions by granting filesystem access to Steam and Heroic directories.
    
    This function executes flatpak override commands to allow Bottles to access:
    1. Steam's xdg-data directory for game configuration files
    2. Heroic Games directory for game installations
    
    The overrides are necessary for Bottles to properly access game data when running Windows applications
    through the Linux environment.
    """
    run(["flatpak", "override", "--user", BOTTLES_PACKAGE, "--filesystem=xdg-data/Steam"], check=True)
    run(["flatpak", "override", "--user", BOTTLES_PACKAGE, "--filesystem=~/Games/Heroic"], check=True)

def find_duplicate_games(
    steam_games: dict[str, InstalledGame],
    gog_games:   dict[str, InstalledGame]
) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """
    Detect games that appear in **both** the Steam and GOG libraries.

    Returns a mapping from the canonical `game_id` (e.g. “skyrimse”) to
    a tuple `(steam_app_id, gog_app_id)`.  Either element may be
    ``None`` if the game is present on only one platform.
    """

    # ----------------------------------------------------------
    # 1. Build app‑id -> GameInfo maps (skip unknown IDs)
    # ----------------------------------------------------------
    steam_appid_to_info: dict[str, gameinfo.GameInfo] = {}
    for app_id in steam_games:
        game_info = game_registry.get_game_by_id(app_id)
        if game_info is not None:
            steam_appid_to_info[app_id] = game_info

    gog_appid_to_info: dict[str, gameinfo.GameInfo] = {}
    for app_id in gog_games:
        game_info = game_registry.get_game_by_id(app_id)
        if game_info is not None:
            gog_appid_to_info[app_id] = game_info

    # ----------------------------------------------------------
    # 2. Canonical game_id -> app‑id maps
    # ----------------------------------------------------------
    steam_id_to_appid: dict[str, str] = {}
    for app_id, game_info in steam_appid_to_info.items():
        steam_id_to_appid[game_info.game_id] = app_id

    gog_id_to_appid: dict[str, str] = {}
    for app_id, game_info in gog_appid_to_info.items():
        gog_id_to_appid[game_info.game_id] = app_id

    # ----------------------------------------------------------
    # 3. Find common canonical IDs
    # ----------------------------------------------------------
    common_ids = set(steam_id_to_appid) & set(gog_id_to_appid)

    # ----------------------------------------------------------
    # 4. Build the result mapping
    # ----------------------------------------------------------
    duplicates: dict[str, tuple[Optional[str], Optional[str]]] = {}
    for cid in common_ids:
        duplicates[cid] = (
            steam_id_to_appid.get(cid),
            gog_id_to_appid.get(cid),
        )

    return duplicates

def handle_duplicates(
    duplicates: dict[str, tuple[Optional[str], Optional[str]]],
    steam_games: dict[str, InstalledGame],
    gog_games:   dict[str, InstalledGame],
    wine_command: list[str]
) -> tuple[dict[str, InstalledGame], dict[str, InstalledGame], dict[Store, str]]:
    """
    Ask the user how to resolve each duplicate game.

    Parameters
    ----------
    duplicates : dict
        Mapping from canonical game_id to (steam_appid, gog_appid).
    steam_games, gog_games : dict
        The game dictionaries that will be cleaned.
    wine_command : list[str]
        The bottles-cli or wine command.

    Returns
    -------
    steam_games, gog_games : dict
        The cleaned dictionaries.
    bottle_names : dict
        Mapping Store -> bottle name (default "Vortex").
    """
    bottle_names: dict[Store, str] = {Store.STEAM: "Vortex", Store.GOG: "Vortex"}
    separate_bottles = False

    for canonical_id, (steam_appid, gog_appid) in duplicates.items():
        print(f"\nDuplicate detected for '{canonical_id}':")
        print(f"  1) Use Steam version (AppID={steam_appid})")
        print(f"  2) Use GOG version   (AppID={gog_appid})")
        choice = ""
        if using_bottles(wine_command):
            print("  3) Separate bottles for each store")
            while choice not in ("1", "2", "3"):
                choice = input("Enter 1, 2, or 3: ").strip()
        else:
            while choice not in ("1", "2"):
                choice = input("Enter 1 or 2: ").strip()

        if choice == "1":
            # Keep Steam entry, drop GOG
            if gog_appid in gog_games:
                del gog_games[gog_appid]
        elif choice == "2":
            # Keep GOG entry, drop Steam
            if steam_appid in steam_games:
                del steam_games[steam_appid]
        elif choice == "3" and using_bottles(wine_command):
            separate_bottles = True

    # Create (or reuse) the appropriate bottles
    if using_bottles(wine_command):
        if separate_bottles:
            # Create two bottles if they don't exist
            for store, bottle_name in [(Store.STEAM, "Vortex-Steam"),
                                    (Store.GOG, "Vortex-GOG")]:
                if not is_existing_bottle(wine_command, bottle_name):
                    logging.info("Creating bottle '%s' for %s store.", bottle_name, store.value)
                    create_bottle(wine_command, bottle_name=bottle_name)
                bottle_names[store] = bottle_name
        else:
            # Create one bottle if it does not exist
            if not is_existing_bottle(wine_command, "Vortex"):
                logging.info("Creating default 'Vortex' bottle.")
                create_bottle(wine_command, bottle_name="Vortex")

    return steam_games, gog_games, bottle_names

def get_bottles_path(bottles_command: list[str]) -> pathlib.Path:
    """Retrieve the path to the bottles directory."""
    return pathlib.Path(run(bottles_command + ["info", "bottles-path"], check=True, capture_output=True).stdout.decode("utf-8").strip())

if __name__ == "__main__":
    main()
