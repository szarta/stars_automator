#!/usr/bin/env python3
"""
ini.py — Ensure Stars.ini contains the settings needed for rich dump output.

Background
----------
Stars! stores player options in a file called Stars.ini located in the
Windows directory.  Under Wine (WINEPREFIX=~/.wine32, WINEARCH=win32) that
path is:

    ~/.wine32/drive_c/windows/Stars.ini

The key setting for oracle/research use is:

    [Misc]
    NewReports=1

When set, the -d dump flag writes richer output and changes the file
extensions from the generic .PLA / .FLE to player-specific .PNN / .FNN
(where NN is the zero-padded player number), making it easy to tell which
player's dump is which.  The .map extension for the universe file is
unchanged.

This module is idempotent: it reads the existing Stars.ini, adds or updates
only the keys listed in REQUIRED_SETTINGS, and writes it back.  All other
existing settings are preserved.

Usage
-----
Standalone:
    python3 -m stars_automator.ini [--wineprefix PATH] [--dry-run]

As a library:
    from stars_automator.ini import ensure_stars_ini
    ensure_stars_ini()
"""

import argparse
import configparser
import os
import shutil
import sys

from stars_automator.config import DEFAULT_WINEPREFIX

# Key=value pairs that must be present for dump scripts to work correctly.
# Section names are case-sensitive (Stars.ini uses [Misc] not [misc]).
REQUIRED_SETTINGS = {
    "Misc": {
        "NewReports": "1",
    },
}


def stars_ini_path(wineprefix: str) -> str:
    return os.path.join(wineprefix, "drive_c", "windows", "Stars.ini")


def ensure_stars_ini(wineprefix: str = DEFAULT_WINEPREFIX, dry_run: bool = False) -> bool:
    """
    Read Stars.ini, inject any missing required settings, and write it back.

    Returns True if the file was modified (or would be in dry-run mode),
    False if it was already correct.
    """
    ini_path = stars_ini_path(wineprefix)

    if not os.path.isfile(ini_path):
        sys.exit(
            f"error: Stars.ini not found at {ini_path}\n"
            f"  Is WINEPREFIX={wineprefix} correct and has Stars! been run at least once?"
        )

    # Use a case-preserving parser (default configparser lowercases keys).
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str
    cfg.read(ini_path)

    changes = []
    for section, pairs in REQUIRED_SETTINGS.items():
        if not cfg.has_section(section):
            cfg.add_section(section)
            for key, value in pairs.items():
                cfg.set(section, key, value)
                changes.append(f"  added [{section}] {key}={value}")
        else:
            for key, value in pairs.items():
                current = cfg.get(section, key, fallback=None)
                if current != value:
                    cfg.set(section, key, value)
                    if current is None:
                        changes.append(f"  added [{section}] {key}={value}")
                    else:
                        changes.append(f"  updated [{section}] {key}: {current!r} → {value!r}")

    if not changes:
        print(f"[stars.ini] already correct ({ini_path})")
        return False

    for line in changes:
        print(line)

    if dry_run:
        print("[stars.ini] dry-run — no changes written")
        return True

    backup = ini_path + ".bak"
    shutil.copy2(ini_path, backup)
    print(f"[stars.ini] backed up → {backup}")

    with open(ini_path, "w") as fh:
        cfg.write(fh, space_around_delimiters=False)

    print(f"[stars.ini] written → {ini_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--wineprefix", default=DEFAULT_WINEPREFIX,
        help=f"Wine prefix directory (default: {DEFAULT_WINEPREFIX})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing",
    )
    args = parser.parse_args()
    ensure_stars_ini(wineprefix=args.wineprefix, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
