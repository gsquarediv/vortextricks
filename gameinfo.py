from __future__ import annotations
from dataclasses import dataclass, field
import json
from typing import Optional

# See: https://github.com/Nexus-Mods/vortex-games to get game info
# See also: https://github.com/sonic2kk/steamtinkerlaunch/blob/master/misc/vortexgames.txt
# See also: https://github.com/Furglitch/modorganizer2-linux-installer/tree/1.9.3
# See also: https://github.com/SulfurNitride/NaK/blob/a76d8da398e92e6062e4921c1a04e6b92666560f/Plugin%20Support/fixgameregistry/__init__.py#L22

@dataclass
class GameInfo:
    """Container for all known identifiers for a single game."""
    name: str
    game_id: str
    nexus_domain_name: Optional[str] = None
    steamapp_ids: list[str] = field(default_factory=list)
    gog_id: Optional[str] = None
    ms_id: Optional[str] = None
    epic_id: Optional[str] = None
    registry_entries: dict = field(default_factory=dict)

    # symlink-specific fields
    override_mygames: Optional[str] = None
    override_appdata: Optional[str] = None

class GameRegistry:
    """
    Holds a collection of GameInfo objects and provides fast lookup by
    Steam app ID or GOG ID.  The constructor builds two dictionaries:
    one mapping each Steam ID to its GameInfo, and another mapping each
    GOG ID to its GameInfo.  Lookups are O(1).
    """
    def __init__(self, games: list[GameInfo]):
        self._games = games
        # Build lookup tables
        self._steam_index: dict[str, GameInfo] = {}
        self._gog_index: dict[str, GameInfo] = {}
        for game in games:
            for sid in game.steamapp_ids:
                self._steam_index[sid] = game
            if game.gog_id:
                self._gog_index[game.gog_id] = game

    def get_game_by_id(self, id: str) -> Optional[GameInfo]:
        """
        Return the GameInfo for the given Steam app ID or GOG ID.
        If the ID is unknown, returns None.
        """
        return self._steam_index.get(id) or self._gog_index.get(id)

    @property
    def games(self) -> list[GameInfo]:
        """Return the raw list of games."""
        return self._games

def games_to_json(games: list[GameInfo]) -> str:
    return json.dumps(games, default=lambda o: o.__dict__, indent=2)

def load_games_from_json(data: str) -> GameRegistry:
    """
    Load a JSON string containing a list of games and return a GameRegistry
    instance for fast lookup.  Each object in the JSON is converted to a
    GameInfo.
    """
    objs = json.loads(data)
    games = [GameInfo(**o) for o in objs]
    return GameRegistry(games)

# Example usage
games = [
    GameInfo(
        name = "Fallout New Vegas",
        game_id="falloutnv",
        nexus_domain_name="newvegas",
        steamapp_ids=["22380", "22490"],
        gog_id="1454587428",
        ms_id="BethesdaSoftworks.FalloutNewVegas",
        epic_id="5daeb974a22a435988892319b3a4f476",
        registry_entries={
            r"HKEY_LOCAL_MACHINE\Software\Wow6432Node\Bethesda Softworks\FalloutNV": "Installed Path"
        },
        override_mygames="FalloutNV",
        override_appdata="FalloutNV"
    ),
    GameInfo(
        name = "Skyrim Special Edition",
        game_id="skyrimse",
        steamapp_ids=["489830"],
        gog_id="1711230643",
        ms_id="BethesdaSoftworks.SkyrimSE-PC",
        epic_id="ac82db5035584c7f8a2c548d98c86b2c",
        registry_entries={
            r"HKEY_LOCAL_MACHINE\Software\Wow6432Node\Bethesda Softworks\Skyrim Special Edition": "Installed Path"
        }
    ),
    # TODO: Get GOG IDs and registry entries for games below here
    GameInfo(
        name="Skyrim",
        game_id="skyrim",
        steamapp_ids=["72850"],
    ),
    GameInfo(
        name="Oblivion",
        game_id="oblivion",
        steamapp_ids=["22330"],
    ),
    GameInfo(
        name="Fallout 4",
        game_id="fallout4",
        steamapp_ids=["377160"],
        override_mygames="Fallout4",
        override_appdata="Fallout4",
    ),
    GameInfo(
        name="Fallout 3 GOTY",
        game_id="fallout3goty",
        steamapp_ids=["22370"],
        override_mygames="Fallout3",
        override_appdata="Fallout3",
    ),
    GameInfo(
        name="Fallout 3",
        game_id="fallout3",
        steamapp_ids=["22300"],
    ),
    GameInfo(
        name="Morrowind",
        game_id="morrowind",
        steamapp_ids=["22320"],
    )
    # add more GameInfo objects here
]