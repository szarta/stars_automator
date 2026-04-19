"""
Default paths for Stars! automation tools.

Priority (highest to lowest):
  1. Environment variable
  2. stars_automator.local.cfg  (gitignored, machine-specific values)
  3. stars_automator.cfg        (committed, placeholder defaults)

To configure for your machine, copy stars_automator.cfg to
stars_automator.local.cfg and fill in the real paths.
"""
import configparser
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    for name in ("stars_automator.cfg", "stars_automator.local.cfg"):
        path = _REPO_ROOT / name
        if path.exists():
            cfg.read(path)
    return cfg


_CFG = _load_config()


def _get(section: str, key: str, env_var: str, fallback: str) -> str:
    if env_var in os.environ:
        return os.path.expanduser(os.environ[env_var])
    val = _CFG.get(section, key, fallback=fallback)
    return os.path.expanduser(val)


DEFAULT_STARS_EXE    = _get("paths", "stars_exe",          "STARS_EXE",          "/path/to/stars.exe")
DEFAULT_PARSER_DIR   = _get("paths", "stars_parser_dir",   "STARS_PARSER_DIR",   "/path/to/stars_file_parser/target/debug")
DEFAULT_RESEARCH_DIR = _get("paths", "stars_research_dir", "STARS_RESEARCH_DIR", "/path/to/stars-reborn-research")
DEFAULT_WINEPREFIX   = _get("wine",  "wineprefix",         "WINEPREFIX",         "~/.wine32")
DEFAULT_DISPLAY      = _get("wine",  "display",            "DISPLAY",            ":99")
