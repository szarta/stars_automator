#!/usr/bin/env python3
"""
turns.py — Generate one or more turns for an existing Stars! game.

Runs `wine stars.exe -gN <game>.hst` headlessly via Xvfb.  stars.exe must be
present in the game directory (game.py copies it there automatically; pass
--copy-exe if it is missing).

Usage:
    python3 -m stars_automator.turns <game_dir> [game_name] [options]

Arguments:
    game_dir    Directory containing the .hst file (and stars.exe).
    game_name   Name of the game (default: "Game").

Options:
    --turns N         Number of turns to generate (default: 1).
    --display :99     X display to use for Wine (default: :99).
    --start-xvfb      Start Xvfb on --display if it is not already running.
    --copy-exe PATH   Copy stars.exe from PATH into game_dir before running.

Notes:
    - stars.exe must be invoked from the game directory with a relative .hst
      path; absolute paths cause Wine to exit 0 with no output.
    - WINEPREFIX=~/.wine32, WINEARCH=win32 are required for the 32-bit binary.
"""

import argparse
import os
import shutil
import subprocess
import sys

from stars_automator._cli import die
from stars_automator.config import DEFAULT_STARS_EXE
from stars_automator.wine import ensure_xvfb, make_wine_env


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("game_dir",  help="Directory containing the .hst file")
    parser.add_argument("game_name", nargs="?", default="Game",
                        help="Game name (default: Game)")
    parser.add_argument("--turns",   type=int, default=1,
                        help="Number of turns to generate (default: 1)")
    parser.add_argument("--display", default=":99",
                        help="X display for Wine (default: :99)")
    parser.add_argument("--start-xvfb", action="store_true",
                        help="Start Xvfb on --display if not already running")
    parser.add_argument("--copy-exe", metavar="PATH",
                        help="Copy stars.exe from PATH into game_dir")
    args = parser.parse_args()

    game_dir  = os.path.realpath(os.path.expanduser(args.game_dir))
    game_name = args.game_name

    if not os.path.isdir(game_dir):
        die(f"game_dir not found: {game_dir}")

    hst_path = os.path.join(game_dir, f"{game_name}.hst")
    if not os.path.isfile(hst_path):
        die(f".hst file not found: {hst_path}")

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

    env = make_wine_env(display=args.display)

    xvfb_proc = None
    if args.start_xvfb:
        print("[xvfb]")
        xvfb_proc = ensure_xvfb(args.display)

    flag    = f"-g{args.turns}"
    hst_rel = f"{game_name}.hst"
    print(f"[stars.exe] running: wine stars.exe {flag} {hst_rel}  (cwd={game_dir})")

    with open(os.devnull, "w") as devnull:
        result = subprocess.run(
            ["wine", "stars.exe", flag, hst_rel],
            cwd=game_dir, env=env,
            stdout=devnull, stderr=devnull,
        )

    if result.returncode != 0:
        die(
            f"stars.exe exited {result.returncode}\n"
            f"  Check that Xvfb is running on {args.display} and that\n"
            f"  WINEPREFIX={env['WINEPREFIX']} is valid."
        )

    print("[output]")
    for fname in sorted(os.listdir(game_dir)):
        fpath = os.path.join(game_dir, fname)
        if not os.path.isfile(fpath):
            continue
        size = os.path.getsize(fpath)
        print(f"  {fname:<24s}  {size:>8d} bytes")

    print(f"\nDone. {args.turns} turn(s) generated in {game_dir}/")

    if xvfb_proc is not None:
        xvfb_proc.terminate()


if __name__ == "__main__":
    main()
