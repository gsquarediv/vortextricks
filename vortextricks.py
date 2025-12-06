from dataclasses import dataclass, field
import json
import logging
import os
import pathlib
import shutil
import subprocess
from enum import Enum
from typing import Dict, Optional, Tuple

import requests
import vdf

import gameinfo
import vortex_symlink

class Store(Enum):
    STEAM = "Steam"
    GOG = "GOG"

@dataclass
class InstalledGame(gameinfo.GameInfo):
    game_path: pathlib.Path = field(default_factory=pathlib.Path)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)

os.environ['WINEDEBUG'] = 'fixme-all'

# Build the registry
game_registry = gameinfo.GameRegistry(gameinfo.games)

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
            logging.warning(f"Duplicate game detected: {game_id} (Steam={steam_app}, GOG={gog_app})")

    # ----------------------------------------------------------------------------------------------------- #
    # 2. Determine prefix(es) to use for Vortex, create prefix(es) if necessary, and handle duplicate games
    # ----------------------------------------------------------------------------------------------------- #
    try:
        wine_command = detect_bottles()
        logging.info(f"Bottles CLI: {' '.join(wine_command)}")
        if duplicates:
            steam_games, gog_games, bottle_names = handle_duplicates(duplicates, steam_games, gog_games, wine_command)
            bottles_path = get_bottles_path(wine_command)
            prefixes: Dict[Store, pathlib.Path] = {
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
            # raise RuntimeError("Could not locate bottles-cli or wine")
            install_wine()
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
    if "bottles-cli" in wine_command or "--command=bottles-cli" in wine_command:
        bottles_path = get_bottles_path(wine_command)
        temp_dir = bottles_path.parent.joinpath("temp")
        for bottle_name in set(bottle_names.values()):
            programs = run(wine_command + ["--json", "programs", "-b", bottle_name], check=True, capture_output=True).stdout.decode("utf-8")
            if "Vortex.exe" not in programs:
                temp_dir.mkdir(parents=True, exist_ok=True)
                installer_path = download_vortex(temp_dir)
                install_vortex(wine_command, installer_path, bottle_name)
    else:
        if not pathlib.Path(pathlib.Path(os.environ['WINEPREFIX']) / "drive_c/Program Files/Black Tree Gaming Ltd/Vortex/Vortex.exe").exists():
            temp_dir = pathlib.Path("/tmp")
            installer_path = download_vortex(temp_dir)
            install_vortex(wine_command, installer_path)
            shortcut_path = pathlib.Path.home() / ".local" / "share" / "applications" / "wine" / "Programs" / "Black Tree Gaming Ltd" / "Vortex.desktop"
            with open(shortcut_path, "a", encoding="utf-8") as f:
                f.write("Categories=Game;\n")
                f.write("MimeType=x-scheme-handler/nxm;x-scheme-handler/nxm-protocol\n")
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
        bottles_command = ["flatpak", "run", "--command=bottles-cli", "com.usebottles.bottles"]
        if run(bottles_command + ["info", "health-check"], check=True, capture_output=True):
            return bottles_command
        else:
            raise RuntimeError("Could not locate bottles-cli")
    else:
        raise RuntimeError("Could not locate bottles-cli or flatpak")

def is_existing_bottle(bottles_command: list[str], bottle_name = "Vortex") -> bool:
    bottles = json.loads(run(bottles_command + ["--json", "list", "bottles"], check=True, capture_output=True).stdout)
    bottle = bottles.get(bottle_name)
    if bottle is not None:
        logging.debug(json.dumps(bottle, indent=4))
        return True
    else:
        return False

def create_bottle(bottles_command: list[str], bottle_name = "Vortex") -> pathlib.Path:
    fix_bottles_permissions()
    components = json.loads(run(bottles_command + ["--json", "list", "components"], check=True, capture_output=True).stdout)
    logging.debug(json.dumps(components, indent=4))
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

def install_wine() -> None:
    """Install Wine using dnf package manager."""
    if shutil.which("dnf"):
        run(["sudo", "dnf", "install", "wine-core.x86_64", "wine-common", "wine-mono", "wine-fonts", "wine-pulseaudio"], check=True)
    else:
        raise RuntimeError("Could not locate bottles-cli or wine")

def find_vortex_prefix() -> pathlib.Path:
    if 'WINEPREFIX' not in os.environ:
        os.environ['WINEPREFIX'] = str(pathlib.Path.home() / 'Games/vortex/pfx')
    return pathlib.Path(os.environ['WINEPREFIX'])

def find_steam() -> pathlib.Path | None:
    if 'STEAM_COMPAT_CLIENT_INSTALL_PATH' in os.environ and pathlib.Path(os.environ['STEAM_COMPAT_CLIENT_INSTALL_PATH']).exists():
        path = pathlib.Path(os.environ['STEAM_COMPAT_CLIENT_INSTALL_PATH'])
    else:
        # try:
        #     import protontricks
        #     path = pathlib.Path(protontricks.find_steam_path()[0])
        # except ImportError:
            if pathlib.Path.exists(pathlib.Path.home() / '.local/share/Steam'):
                path = pathlib.Path.home() / '.local/share/Steam'
            elif pathlib.Path.exists(pathlib.Path.home() / '.steam/steam'):
                path = pathlib.Path.home() / '.steam/steam'
            else:
                path = None
    return path

def find_heroic() -> pathlib.Path | None:
    path = pathlib.Path.home() / ".var/app/com.heroicgameslauncher.hgl/config/heroic"
    if pathlib.Path.exists(path):
        return path

def create_wine_prefix(proton_path = None) -> None:
    os.makedirs(os.environ['WINEPREFIX'], exist_ok=True)
    if proton_path is None:
        run(["wineboot", "-u"], check=True)
    else:
        run([proton_path, "wineboot", "-u"], check=True)

def configure_vortex_environment(wine_command: list[str], store: Store, library: dict[str, InstalledGame], vortex_prefix: pathlib.Path, bottle_name = "Vortex") -> None:
    """
    Register the games that are already in the user's library inside the Vortex
    bottle.  `library` is the dict returned by ``list_installed_*_games`` - it
    maps an app-id to an ``InstalledGame`` instance.
    """
    for app_id, installed_game in library.items():
        # Look up the game metadata in the registry
        game = game_registry.get_game_by_id(app_id)
        if game is None:
            logging.warning(f"Game {app_id} not found in registry")
            continue

        # Verify that the app‑id actually belongs to this game
        if store == Store.STEAM and app_id not in game.steamapp_ids:
            continue
        if store == Store.GOG and app_id not in (game.gog_id or []):
            continue

        logging.info(f"Found game {game.game_id} (appid={app_id})")

        # Add all registry entries
        for key, value in game.registry_entries.items():
            # Convert the Unix path to a Windows‑style path that Vortex expects
            win_path = pathlib.PureWindowsPath("z:", pathlib.PurePosixPath(installed_game.game_path))
            logging.info(f"  Adding registry entry: {key}\\{value} -> {win_path}")
            add_registry_entry(wine_command, key, value, win_path, bottle_name)

        # Create the game‑specific symlinks when we’re dealing with Steam
        if store == Store.STEAM:
            vortex_symlink.create_game_symlinks(
                app_id=app_id,
                vortex_prefix=vortex_prefix,
                game_prefix=pathlib.Path.home() / f'.local/share/Steam/steamapps/compatdata/{app_id}/pfx',
                username=os.environ["USER"])

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
                    moddable_games.update({appid: InstalledGame(game_id=game.game_id, nexus_domain_name=game.nexus_domain_name, steamapp_ids=[appid], gog_id=game.gog_id, ms_id=game.ms_id, epic_id=game.epic_id, registry_entries=game.registry_entries, game_path = install_path)})
            except Exception:
                continue

    logging.debug(json.dumps(list(games.values()), indent=4))
    return moddable_games

def list_installed_gog_games(heroic_path: pathlib.Path) -> dict[str, InstalledGame]:
    """
    List all installed GOG games managed by Heroic (Flatpak).
    """
    gog_store_path = heroic_path / "gog_store" / "installed.json"

    if not gog_store_path.exists():
        raise FileNotFoundError(f"GOG installed.json not found: {gog_store_path}")

    with gog_store_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    installed_section = data.get("installed", [])
    if not isinstance(installed_section, list):
        raise TypeError(f"Expected 'installed' to be a list, got {type(installed_section).__name__}")

    games = []
    moddable_games = {}
    for entry in installed_section:
        if not isinstance(entry, dict):
            continue

        install_path = os.path.expanduser(entry.get("install_path", ""))
        name = pathlib.Path(install_path).name if install_path else entry.get("appName", "Unknown")
        appid = entry.get("appName") or name

        games.append({
            "appid": appid,
            "name": name,
            "path": install_path,
            "platform": entry.get("platform"),
            "version": entry.get("version"),
        })

        game = game_registry.get_game_by_id(appid)
        if game:
            moddable_games.update({appid: InstalledGame(game_id=game.game_id, nexus_domain_name=game.nexus_domain_name, steamapp_ids=game.steamapp_ids, gog_id=appid, ms_id=game.ms_id, epic_id=game.epic_id, registry_entries=game.registry_entries, game_path = install_path)})

    logging.debug(json.dumps(games, indent=4))
    return moddable_games

def add_registry_entry(wine_command: list[str], key: str, value: str, data: pathlib.PureWindowsPath, bottle_name = "Vortex") -> subprocess.CompletedProcess:
    if "bottles-cli" in wine_command or "--command=bottles-cli" in wine_command:
        result = run(wine_command + ["reg", "-b", bottle_name, "-k",
                                   key, "-v", value, "-d",
                                   str(data), "-t", "REG_SZ", "add"], check=True, capture_output=True)
    else:
        result = run(wine_command + ["reg", "add",
                                   key,
                                   "/t", "REG_SZ", "/v", value, "/d",
                                   str(data)], check=True)
    return result

def download(url: str | bytes, destination) -> None:
    """Download a file from a URL using requests."""
    logging.info(f"Downloading {url} to {destination}")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(destination, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)

def download_vortex(directory: pathlib.Path) -> pathlib.Path:
    logging.info("Fetching latest Vortex release from GitHub...")
    api_url = "https://api.github.com/repos/Nexus-Mods/Vortex/releases/latest"
    response = requests.get(api_url)
    response.raise_for_status()
    release = response.json()
    latest_tag = release.get("tag_name")
    logging.info(f"Latest tag: {latest_tag}")

    filename = f"vortex-setup-{latest_tag.lstrip('v')}.exe"
    download_url = f"https://github.com/Nexus-Mods/Vortex/releases/download/{latest_tag}/{filename}"
    path = directory.joinpath(filename)
    download(download_url, path)
    return path

def install_vortex(wine_command: list[str], installer_path: pathlib.Path, bottle_name = "Vortex") -> subprocess.CompletedProcess:
    if "bottles-cli" in wine_command or "--command=bottles-cli" in wine_command:
        result = run(wine_command + ["run", "-b", bottle_name, "-e", str(installer_path)], check=True)
    else:
        result = run(wine_command + [str(installer_path), "/SILENT"], check=True)
    installer_path.unlink(missing_ok=True)
    return result

def fix_bottles_permissions() -> None:
    run(["flatpak", "override", "--user", "com.usebottles.bottles", "--filesystem=xdg-data/Steam"], check=True)
    run(["flatpak", "override", "--user", "com.usebottles.bottles", "--filesystem=~/Games/Heroic"], check=True)

def find_duplicate_games(
    steam_games: Dict[str, InstalledGame],
    gog_games:   Dict[str, InstalledGame]
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """
    Detect games that appear in **both** the Steam and GOG libraries.

    Returns a mapping from the canonical `game_id` (e.g. “skyrimse”) to
    a tuple `(steam_app_id, gog_app_id)`.  Either element may be
    ``None`` if the game is present on only one platform.
    """

    # ----------------------------------------------------------
    # 1. Build app‑id → GameInfo maps (skip unknown IDs)
    # ----------------------------------------------------------
    steam_appid_to_info: Dict[str, gameinfo.GameInfo] = {}
    for app_id in steam_games:
        gi = game_registry.get_game_by_id(app_id)
        if gi is not None:            # `gi` is guaranteed to be a GameInfo
            steam_appid_to_info[app_id] = gi

    gog_appid_to_info: Dict[str, gameinfo.GameInfo] = {}
    for app_id in gog_games:
        gi = game_registry.get_game_by_id(app_id)
        if gi is not None:
            gog_appid_to_info[app_id] = gi

    # ----------------------------------------------------------
    # 2. Canonical game_id → app‑id maps
    # ----------------------------------------------------------
    steam_id_to_appid: Dict[str, str] = {}
    for app_id, gi in steam_appid_to_info.items():
        steam_id_to_appid[gi.game_id] = app_id

    gog_id_to_appid: Dict[str, str] = {}
    for app_id, gi in gog_appid_to_info.items():
        gog_id_to_appid[gi.game_id] = app_id

    # ----------------------------------------------------------
    # 3. Find common canonical IDs
    # ----------------------------------------------------------
    common_ids = set(steam_id_to_appid) & set(gog_id_to_appid)

    # ----------------------------------------------------------
    # 4. Build the result mapping
    # ----------------------------------------------------------
    duplicates: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for cid in common_ids:
        duplicates[cid] = (
            steam_id_to_appid.get(cid),
            gog_id_to_appid.get(cid),
        )

    return duplicates

def handle_duplicates(
    duplicates: Dict[str, Tuple[Optional[str], Optional[str]]],
    steam_games: Dict[str, InstalledGame],
    gog_games:   Dict[str, InstalledGame],
    wine_command: list[str]
) -> Tuple[Dict[str, InstalledGame], Dict[str, InstalledGame], Dict[Store, str]]:
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
    bottle_names: Dict[Store, str] = {Store.STEAM: "Vortex", Store.GOG: "Vortex"}
    using_bottles = "bottles-cli" in wine_command or "--command=bottles-cli" in wine_command
    separate_bottles = False

    for canonical_id, (steam_appid, gog_appid) in duplicates.items():
        print(f"\nDuplicate detected for '{canonical_id}':")
        print(f"  1) Use Steam version (AppID={steam_appid})")
        print(f"  2) Use GOG version   (AppID={gog_appid})")
        choice = ""
        if using_bottles:
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
        elif choice == "3" and using_bottles:
            separate_bottles = True

    # Create (or reuse) the appropriate bottles
    if using_bottles:
        if separate_bottles:
            # Create two bottles if they don't exist
            for store, bottle_name in [(Store.STEAM, "Vortex-Steam"),
                                    (Store.GOG, "Vortex-GOG")]:
                if not is_existing_bottle(wine_command, bottle_name):
                    logging.info(f"Creating bottle '{bottle_name}' for {store.value} store.")
                    create_bottle(wine_command, bottle_name=bottle_name)
                bottle_names[store] = bottle_name
        else:
            # Create one bottle if it does not exist
            if not is_existing_bottle(wine_command, "Vortex"):
                logging.info("Creating default 'Vortex' bottle.")
                create_bottle(wine_command, bottle_name="Vortex")

    return steam_games, gog_games, bottle_names

def get_bottles_path(bottles_command: list[str]) -> pathlib.Path:
    return pathlib.Path(run(bottles_command + ["info", "bottles-path"], check=True, capture_output=True).stdout.decode("utf-8").strip())

if __name__ == "__main__":
    main()
