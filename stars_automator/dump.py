#!/usr/bin/env python3
"""
dump.py — Dump planet/fleet/universe info from a Stars! player file.

Runs `wine stars.exe -d[pfm] <game>.mN` headlessly.  No display or Xvfb
required — the -d flag is fully CLI and exits immediately after writing files.

stars.exe must be present in the game directory (game.py copies it there
automatically; pass --copy-exe if it is missing).

Output files (written by stars.exe in the game directory):
    Without NewReports=1 in stars.ini:
        <game>.pla   planets
        <game>.fle   fleets
        <game>.map   universe definition

    With NewReports=1 in stars.ini (richer output, recommended):
        <game>.pNN   planets  (NN = player number)
        <game>.fNN   fleets   (NN = player number)
        <game>.map   universe definition (extension unchanged)

Usage:
    python3 -m stars_automator.dump <game_dir> <player_file> [options]

Arguments:
    game_dir      Directory containing the .mN file (and stars.exe).
    player_file   Player file name, e.g. Game.m1  (relative to game_dir).

Options:
    --planets          Dump planet info   (default: all three)
    --fleets           Dump fleet info    (default: all three)
    --map              Dump universe map  (default: all three)
    --copy-exe PATH    Copy stars.exe from PATH into game_dir before running.

Examples:
    # Dump everything for player 1:
    python3 -m stars_automator.dump /path/to/game Game.m1

    # Dump only planets and fleets:
    python3 -m stars_automator.dump /path/to/game Game.m1 --planets --fleets
"""

import argparse
import os
import shutil
import subprocess
import sys

from stars_automator._cli import die
from stars_automator.ini import ensure_stars_ini
from stars_automator.wine import make_wine_env


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("game_dir",     help="Directory containing the player file")
    parser.add_argument("player_file",  help="Player file name, e.g. Game.m1")
    parser.add_argument("--planets",    action="store_true", help="Dump planet info")
    parser.add_argument("--fleets",     action="store_true", help="Dump fleet info")
    parser.add_argument("--map",        action="store_true", help="Dump universe map")
    parser.add_argument("--copy-exe",   metavar="PATH",
                        help="Copy stars.exe from PATH into game_dir")
    args = parser.parse_args()

    game_dir    = os.path.realpath(os.path.expanduser(args.game_dir))
    player_file = args.player_file

    if not os.path.isdir(game_dir):
        die(f"game_dir not found: {game_dir}")

    player_path = os.path.join(game_dir, player_file)
    if not os.path.isfile(player_path):
        die(f"player file not found: {player_path}")

    exe_path = os.path.join(game_dir, "stars.exe")
    if args.copy_exe:
        src = os.path.expanduser(args.copy_exe)
        if not os.path.isfile(src):
            die(f"stars.exe source not found: {src}")
        shutil.copy2(src, exe_path)
        print(f"[setup] copied stars.exe → {exe_path}")
    elif not os.path.isfile(exe_path):
        die(
            f"stars.exe not found in {game_dir}\n"
            f"  Pass --copy-exe <path/to/stars.exe> to copy it in, or run\n"
            f"  stars_automator.game which copies it automatically."
        )

    dump_planets = args.planets
    dump_fleets  = args.fleets
    dump_map     = args.map
    if not (dump_planets or dump_fleets or dump_map):
        dump_planets = dump_fleets = dump_map = True

    flag_chars = ""
    if dump_planets:
        flag_chars += "p"
    if dump_fleets:
        flag_chars += "f"
    if dump_map:
        flag_chars += "m"

    d_flag = f"-d{flag_chars}"

    env = make_wine_env(display=os.environ.get("DISPLAY", ":0"))

    print("[stars.ini]")
    ensure_stars_ini()

    print(f"[stars.exe] running: wine stars.exe {d_flag} {player_file}  (cwd={game_dir})")

    before_mtimes = {
        f: os.path.getmtime(os.path.join(game_dir, f))
        for f in os.listdir(game_dir)
        if os.path.isfile(os.path.join(game_dir, f))
    }
    before_set = set(before_mtimes)

    with open(os.devnull, "w") as devnull:
        result = subprocess.run(
            ["wine", "stars.exe", d_flag, player_file],
            cwd=game_dir, env=env,
            stdout=devnull, stderr=devnull,
        )

    if result.returncode != 0:
        die(f"stars.exe exited {result.returncode}")

    print("[output]")
    touched = []
    for fname in sorted(os.listdir(game_dir)):
        fpath = os.path.join(game_dir, fname)
        if not os.path.isfile(fpath):
            continue
        mtime = os.path.getmtime(fpath)
        if fname not in before_set or mtime > before_mtimes[fname]:
            touched.append(fname)

    for fname in touched:
        fpath = os.path.join(game_dir, fname)
        size  = os.path.getsize(fpath)
        print(f"  {fname:<24s}  {size:>8d} bytes")

    if not touched:
        print("  (no files written — check that the player file is valid)")

    print(f"\nDone. Dump files written to {game_dir}/")


if __name__ == "__main__":
    main()
