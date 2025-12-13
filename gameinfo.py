"""
gameinfo

Provides data structures and helper functions for handling game metadata.

This module defines:

* **GameInfo** - a dataclass that stores all known identifiers for a single
  game (Steam app IDs, GOG ID, registry entries, etc.).

* **GameRegistry** - a lightweight container that indexes a list of
  `GameInfo` objects by Steam and GOG identifiers for fast lookup.

* **games_to_json** - serialises a list of `GameInfo` objects into a pretty-printed
  JSON string.

* **load_games_from_json** - validates a JSON string against
  :file:`gameinfo.schema.json` and returns a populated `GameRegistry`.

The JSON schema is located in the same directory as this module and
ensures that the data conforms to the expected structure before it is used
within the application.

"""

from __future__ import annotations
from dataclasses import dataclass, field
import json
import pathlib
from typing import Optional

from jsonschema import Draft202012Validator, ValidationError

# See: https://github.com/Nexus-Mods/vortex-games to get game info
# See also: https://github.com/sonic2kk/steamtinkerlaunch/blob/master/misc/vortexgames.txt
# See also: https://github.com/Furglitch/modorganizer2-linux-installer/tree/1.9.3
# See also: https://github.com/SulfurNitride/NaK/blob/a76d8da398e92e6062e4921c1a04e6b92666560f/Plugin%20Support/fixgameregistry/__init__.py#L22

JSON_INDENT = 4

@dataclass
class GameInfo:
    """Container for all known identifiers for a single game."""
    name: str
    game_id: str
    steamapp_ids: list[str] = field(default_factory=list[str])
    gog_id: Optional[str] = None
    ms_id: Optional[str] = None
    epic_id: Optional[str] = None
    registry_entries: dict[str, str] = field(default_factory=dict[str, str])

    # symlink-specific fields
    override_mygames: Optional[str] = None
    override_appdata: Optional[str] = None

class GameRegistry:
    """
    Holds a collection of GameInfo objects and provides fast lookup by
    Steam app ID or GOG ID.  The constructor builds two dictionaries:
    one mapping each Steam ID to its GameInfo, and another mapping each
    GOG ID to its GameInfo.
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

    def get_game_by_id(self, identifier: str) -> Optional[GameInfo]:
        """
        Return the GameInfo for the given Steam app ID or GOG ID.
        If the ID is unknown, returns None.
        """
        return self._steam_index.get(identifier) or self._gog_index.get(identifier)

    @property
    def games(self) -> list[GameInfo]:
        """Return the raw list of games."""
        return self._games

def games_to_json(games: list[GameInfo]) -> str:
    """
    Serialize a list of GameInfo objects to a JSON-formatted string.
    
    Converts each GameInfo object to a dictionary using its __dict__ attribute,
    then formats the output as a JSON array with indentation for readability.
    
    Parameters:
        games (list[GameInfo]): List of GameInfo objects to be serialized.
        
    Returns:
        str: JSON-formatted string representing the list of game information.
        
    Note:
        The output conforms to the structure defined in gameinfo.schema.json.
    """
    return json.dumps(games, default=lambda o: o.__dict__, indent=JSON_INDENT)

def load_games_from_json(data: str) -> GameRegistry:
    """
    Load a JSON string containing a list of games and return a GameRegistry
    instance for fast lookup.  Each object in the JSON is converted to a
    GameInfo.
    """
    schema_path = pathlib.Path(__file__).with_name("gameinfo.schema.json")
    with schema_path.open("r", encoding="utf-8") as file:
        schema = json.load(file)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    objects = json.loads(data)
    try:
        validator.validate(objects)
    except ValidationError as e:
        raise ValueError(f"gameinfo.json is invalid:\n{e.message}") from e
    games = [GameInfo(**object) for object in objects]
    return GameRegistry(games)
