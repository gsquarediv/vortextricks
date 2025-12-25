# VortexTricks

**Automate Vortex Mod Manager setup in Linux for Steam & Heroic**

VortexTricks is a lightweight, self‑contained Python utility that

* Detects your Steam and Heroic installations
* Resolves duplicate titles between your Steam and GOG libraries
* Creates the necessary WINE prefix / WINE bottles
* Registers the games inside Vortex by adding the correct registry keys and
  creating save‑game / `AppData` symlinks
* Downloads and installs the latest Vortex release

> **⚠️ Disclaimer** – This project is provided as-is. Use it at your own risk.

---

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Usage](#usage)
5. [Manual Post‑Execution Steps](#manual-postexecution-steps)
6. [Extending the Game Registry](#extending-the-game-registry)
7. [Troubleshooting](#troubleshooting)
8. [Contributing](#contributing)

---

## Features

| Feature | Description |
|---------|-------------|
| **Store detection** | Automatically locates Steam and Heroic (GOG) installations. |
| **Duplicate handling** | Prompts you to decide which copy to keep or to use separate bottles. |
| **Bottle creation** | Creates a default `Vortex` bottle, or separate ones per store, with the appropriate WINE runner. |
| **Registry registration** | Adds the required Windows registry entries for each game into the Vortex prefix. |
| **Symlink creation** | Links the Proton prefix’s `My Games` & `AppData` folders into the Vortex WINE prefix so that saves and settings stay in sync. |
| **Automatic Vortex install** | Downloads the latest Vortex installer from GitHub and installs it into the chosen prefix. |

---

## Prerequisites

| Item | Requirement | Notes |
|------|-------------|-------|
| **Linux** | Any | Tested with Fedora Linux 43 (KDE Plasma Desktop Edition) |
| **Python** | 3.9+ | Tested with 3.14 |
| **WINE / Bottles** | Required for running Windows binaries | Either vanilla WINE or Bottles (flatpak or native) |
| **Flatpak** | Optional | If you use Bottles via Flatpak |
| **Steam** | Optional | Game store |
| **Heroic (GOG)** | Optional | Game store |
| **`protontricks`** | pip package | Used to find Steam |
| **`requests`** | pip package | For downloading the Vortex installer |
| **`vdf`** | pip package | For parsing Steam VDF files |
| **`jsonschema`** | pip package | For validating `gameinfo.json` |

---

## Installation

```bash
# Clone the repo
git clone https://github.com/gsquarediv/vortextricks.git
cd vortextricks

# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Install the script globally
#   pip install .
#   # or create a symlink to the python script
#   ln -s $(pwd)/vortextricks.py /usr/local/bin/vortextricks
```

---

## Usage

```bash
# Run the script (it will create/verify the Vortex prefix and register all games)
./vortextricks.py

# If you installed it globally:
vortextricks
```

Upon execution, this script will:

1. Detect Steam and GOG game libraries.
2. Prompt you if the same title appears in both libraries.
3. Ask whether to use the Steam copy, the GOG copy, or keep both in separate bottles.
4. Create the necessary bottles or WINE prefixes.
5. Register Windows registry entries for each game to enable auto-detection of the game path in Vortex.
6. Create symlinks for `My Games` & `AppData`.
7. Download and install Vortex if not present.

### Command‑Line Options

At the moment the script has no command‑line arguments; it is intended to be run once during initial setup.  If you wish to run a specific step or skip interactive prompts, you can modify the script directly.

---

## Manual Post‑Execution Steps

After the script finishes, you may need to perform a few manual steps to complete the setup:

- **Desktop shortcut & browser integration**  
  - **Bottles** – The script automatically creates a hidden desktop shortcut for Vortex and registers the `nxm` MIME type for browser integration with [Nexus Mods](https://www.nexusmods.com/).  
    > ⚠️ **Note:** If you choose to use separate bottles for duplicate games, a hidden desktop shortcut will be created for each bottle, but you will have to run `xdg-mime default` manually to select which instance of Vortex is the default handler for browser integration.
  - **Native WINE** – Automatic MIME type configuration is not implemented.  You will have to manually configure MIME type integration for browser links to work with Vortex.  

- **Game initialization**  
  Any game to be modded needs to be ran once before attempting to mod it.  Otherwise, missing files may cause errors in Vortex.

- **Mod staging folder**  
  Vortex needs a staging folder where it temporarily stores mods before deploying them.  When running Vortex in Bottles (Flatpak), the default suggestions seem to work pretty well.  You may be able to simply enable "Automatically use suggested path for staging folder" in Settings and let Vortex handle it.  If that does not work, you will have to manually set your staging folder for every game.

---

## Extending the Game Registry

The registry of known games is stored in `gameinfo.json`.  
To add a new game:

1. Add an entry in the array, e.g.:

```json
{
  "name": "Example Game",
  "game_id": "examplegame",
  "steamapp_ids": ["123456"],
  "gog_id": "987654321",
  "ms_id": null,
  "epic_id": null,
  "registry_entries": {
    "HKEY_LOCAL_MACHINE\\Software\\ExampleCompany\\ExampleGame": "Installed Path"
  },
  "override_mygames": "ExampleGame",
  "override_appdata": "ExampleGame"
}
```

2. Validate the JSON against the schema:

```bash
python -c "import jsonschema, json, pathlib; schema = json.load(open('gameinfo.schema.json')); validator = jsonschema.Draft202012Validator(schema); json.load(open('gameinfo.json'))" || echo "Invalid JSON"
```

3. Rerun the script – the new game will now be recognized.

> **Tip** – The `registry_entries` dictionary keys are the full registry paths; the values are the string data that will be written.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `protontricks` cannot find Steam | Steam is not installed or the environment path is missing | Install Steam or set `STEAM_HOME` |
| Wine fails to create the prefix | Missing Wine binary or broken permissions | Install `wine` (`sudo dnf install wine` on Fedora) |
| `Using bottles-cli` errors | `bottles-cli` not found and `flatpak` is missing | Install Bottles via `flatpak install com.usebottles.bottles` or use vanilla WINE |
| Duplicate game prompts not showing | The duplicate detection logic didn’t find overlapping game IDs | Ensure both stores are present and the game IDs match those in `gameinfo.json` |
| Symlinks not working | Proton prefix path is wrong or the target does not exist | Verify the Proton prefix (default: `~/.steam/root/compatdata/<APPID>/pfx`) |
| Vortex.exe not launching | The installer could not be downloaded | Check internet connectivity or the GitHub API rate‑limit |

---

## Contributing

1. Fork the repository.
2. Create a new branch (`git checkout -b feature/…`).
3. Commit your changes with descriptive messages.
4. Push the branch and open a pull request.
