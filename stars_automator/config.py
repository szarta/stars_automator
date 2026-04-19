"""
Default paths for Stars! automation tools.

All defaults can be overridden with environment variables:

    STARS_EXE           Path to stars.exe (Wine-compatible binary)
    STARS_PARSER_DIR    Directory containing stars_file_parser binaries
                        (json_to_r1, json_to_def, m1_to_json, …)
    WINEPREFIX          Wine prefix directory (standard Wine env var)
    DISPLAY             X display for Wine / Xvfb (standard X11 env var)
"""
import os

DEFAULT_STARS_EXE = os.path.expanduser(
    os.environ.get(
        "STARS_EXE",
        "~/data/stars/stars-reborn-research/original/stars.exe",
    )
)

DEFAULT_PARSER_DIR = os.path.expanduser(
    os.environ.get(
        "STARS_PARSER_DIR",
        "~/data/stars/stars_file_parser/target/debug",
    )
)

DEFAULT_WINEPREFIX = os.path.expanduser(
    os.environ.get("WINEPREFIX", "~/.wine32")
)

DEFAULT_DISPLAY = os.environ.get("DISPLAY", ":99")
