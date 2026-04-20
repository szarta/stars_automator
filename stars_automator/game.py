#!/usr/bin/env python3
"""
game.py — Create a Stars! game from a JSON configuration file.

Creates /tmp/<experiment_name>/, copies stars.exe there, generates .r1 race
files, writes game.def, then runs `wine stars.exe -a game.def` headlessly via
Xvfb to produce the initial game files (.hst, .m1…mN, .xy).

Usage:
    python3 -m stars_automator.game <config.json> [--display :99] [--start-xvfb]

Outputs land in /tmp/<experiment_name>/.

Configuration file schema (JSON):
  {
    "experiment_name": "my_run",          # required; names the /tmp/ subdirectory
    "game_name": "Game",                  # optional; default "Game"
    "stars_exe": "~/…/stars.exe",         # optional; overrides STARS_EXE env var
    "parser_dir": "~/…/target/debug",     # optional; overrides STARS_PARSER_DIR env var

    "universe": {
      "map_size":        "tiny|small|medium|large|huge",   # required
      "density":         "sparse|normal|dense|packed",     # required; NOTE: "packed" fails silently in headless mode — stars.exe -a produces no output files; use "dense" instead
      "player_positions":"close|random|farther|distant",   # required
      "seed":            12345                             # required
    },

    "options": {                          # all optional; default false
      "max_minerals":       false,
      "slow_tech":          false,
      "bbs_play":           false,
      "galaxy_clumping":    false,
      "computer_alliances": false,
      "no_random_events":   false,
      "public_scores":      false
    },

    "victory": {                          # optional; defaults shown
      "planets":        {"enabled": true,  "percent": 60},
      "tech":           {"enabled": true,  "level": 26, "fields": 4},
      "score":          {"enabled": false, "score": 5000},
      "exceeds_nearest":{"enabled": false, "percent": 150},
      "production":     {"enabled": false, "capacity": 100},
      "capital_ships":  {"enabled": false, "number": 100},
      "turns":          {"enabled": false, "years": 100},
      "must_meet": 1,
      "min_years": 50
    },

    "human_races": [                      # at least one entry required
      // each entry is one of:
      //   a) a full race JSON object (format_version, name, prt, ...)
      //   b) a path string to a .json race file
      //   c) a path string to a pre-built .r1 file (copied as-is)
    ],

    "ai_players": [                       # optional; default []
      {"difficulty": 2, "param": 1}       # difficulty: 0=easy 1=standard 2=harder 3=expert
    ]
  }
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from stars_automator._cli import die
from stars_automator.config import DEFAULT_PARSER_DIR, DEFAULT_STARS_EXE
from stars_automator.wine import ensure_xvfb, make_wine_env, wine_path

DEFAULT_VICTORY = {
    "planets": {"enabled": True, "percent": 60},
    "tech": {"enabled": True, "level": 26, "fields": 4},
    "score": {"enabled": False, "score": 5000},
    "exceeds_nearest": {"enabled": False, "percent": 150},
    "production": {"enabled": False, "capacity": 100},
    "capital_ships": {"enabled": False, "number": 100},
    "turns": {"enabled": False, "years": 100},
    "must_meet": 1,
    "min_years": 50,
}

DEFAULT_OPTIONS = {
    "max_minerals": False,
    "slow_tech": False,
    "bbs_play": False,
    "galaxy_clumping": False,
    "computer_alliances": False,
    "no_random_events": False,
    "public_scores": False,
}


def run_tool(cmd, description):
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        die(
            f"{description} failed:\n  cmd: {' '.join(str(c) for c in cmd)}\n"
            f"  stderr: {result.stderr.decode().strip()}"
        )
    return result


def check_tool(path):
    if not os.path.isfile(path):
        die(f"tool not found: {path}\n  Run `cargo build` in the stars_file_parser directory.")


def resolve_race(entry, workdir, player_idx, json_to_r1_bin, env):
    """
    Given a race config entry (inline dict, .json path, or .r1 path),
    return the Windows-format path to the .r1 file in workdir.
    """
    r1_dest = os.path.join(workdir, f"player{player_idx}.r1")

    if isinstance(entry, str):
        entry = os.path.expanduser(entry)
        if entry.endswith(".r1"):
            shutil.copy2(entry, r1_dest)
            print(f"  player {player_idx}: copied {entry}")
        elif entry.endswith(".json"):
            if not os.path.isfile(entry):
                die(f"race JSON file not found: {entry}")
            run_tool([json_to_r1_bin, entry, r1_dest], f"json_to_r1 (player {player_idx})")
            print(f"  player {player_idx}: converted {entry} → player{player_idx}.r1")
        else:
            die(
                f"human_races entry {player_idx!r} is a string but not "
                f"a .json or .r1 path: {entry!r}"
            )
    elif isinstance(entry, dict):
        json_path = os.path.join(workdir, f"player{player_idx}.json")
        with open(json_path, "w") as f:
            json.dump(entry, f, indent=2)
        run_tool([json_to_r1_bin, json_path, r1_dest], f"json_to_r1 (player {player_idx})")
        name = entry.get("name", "?")
        print(f"  player {player_idx}: inline race '{name}' → player{player_idx}.r1")
    else:
        die(f"human_races[{player_idx}] must be a dict or a file path string")

    return wine_path(r1_dest, env)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", help="Path to the game configuration JSON file")
    parser.add_argument("--display", default=":99", help="X display to use for Wine (default: :99)")
    parser.add_argument(
        "--start-xvfb",
        action="store_true",
        help="Start Xvfb on --display if it is not already running",
    )
    args = parser.parse_args()

    config_path = os.path.expanduser(args.config)
    if not os.path.isfile(config_path):
        die(f"config file not found: {config_path}")
    with open(config_path) as f:
        cfg = json.load(f)

    experiment_name = cfg.get("experiment_name")
    if not experiment_name:
        die("config must include 'experiment_name'")

    game_name = cfg.get("game_name", "Game")
    stars_exe = os.path.expanduser(cfg.get("stars_exe", DEFAULT_STARS_EXE))
    parser_dir = os.path.expanduser(cfg.get("parser_dir", DEFAULT_PARSER_DIR))
    universe = cfg.get("universe")
    options = {**DEFAULT_OPTIONS, **cfg.get("options", {})}
    victory = {**DEFAULT_VICTORY, **cfg.get("victory", {})}
    human_races = cfg.get("human_races", [])
    ai_players = cfg.get("ai_players", [])

    if not universe:
        die("config must include a 'universe' section")
    if not human_races:
        die("config must include at least one entry in 'human_races'")

    required_universe_keys = {"map_size", "density", "player_positions", "seed"}
    missing = required_universe_keys - set(universe.keys())
    if missing:
        die(f"universe section missing keys: {', '.join(sorted(missing))}")

    json_to_r1_bin = os.path.join(parser_dir, "json_to_r1")
    json_to_def_bin = os.path.join(parser_dir, "json_to_def")
    for tool in [json_to_r1_bin, json_to_def_bin]:
        check_tool(tool)
    if not os.path.isfile(stars_exe):
        die(f"stars.exe not found: {stars_exe}")

    env = make_wine_env(display=args.display)

    xvfb_proc = None
    if args.start_xvfb:
        print("[xvfb]")
        xvfb_proc = ensure_xvfb(args.display)

    workdir = os.path.join("/tmp", experiment_name)
    if os.path.exists(workdir):
        print(f"[setup] using existing directory: {workdir}")
    else:
        os.makedirs(workdir)
        print(f"[setup] created: {workdir}")

    stars_dest = os.path.join(workdir, "stars.exe")
    if os.path.exists(stars_dest) and os.path.samefile(stars_exe, stars_dest):
        print(f"[setup] stars.exe already linked → {workdir}/stars.exe")
    else:
        try:
            os.link(stars_exe, stars_dest)
            print(f"[setup] hardlinked stars.exe → {workdir}/stars.exe")
        except OSError:
            shutil.copy2(stars_exe, stars_dest)
            print(f"[setup] copied stars.exe → {workdir}/stars.exe")

    print("[races]")
    r1_wine_paths = []
    for idx, race_entry in enumerate(human_races, start=1):
        wp = resolve_race(race_entry, workdir, idx, json_to_r1_bin, env)
        r1_wine_paths.append(wp)

    print("[game.def]")
    xy_wine = wine_path(os.path.join(workdir, f"{game_name}.xy"), env)

    players = [{"human": {"race_file": wp}} for wp in r1_wine_paths]
    for ai in ai_players:
        players.append({"ai": {"difficulty": ai["difficulty"], "param": ai.get("param", 1)}})

    game_def = {
        "game_name": game_name,
        "universe": universe,
        "options": options,
        "players": players,
        "victory": victory,
        "output_xy": xy_wine,
    }

    def_json_path = os.path.join(workdir, "game.json")
    def_path = os.path.join(workdir, "game.def")
    with open(def_json_path, "w") as f:
        json.dump(game_def, f, indent=2)
    run_tool([json_to_def_bin, def_json_path, def_path], "json_to_def")
    print(
        f"  wrote game.def  ({len(players)} player(s): "
        f"{len(r1_wine_paths)} human, {len(ai_players)} AI)"
    )

    print("[stars.exe]")
    print(f"  running: wine stars.exe -a game.def  (cwd={workdir})")
    with open(os.devnull, "w") as devnull:
        result = subprocess.run(
            ["wine", "stars.exe", "-a", "game.def"],
            cwd=workdir,
            env=env,
            stdout=devnull,
            stderr=devnull,
        )
    if result.returncode != 0:
        die(
            f"stars.exe exited {result.returncode} — check that Xvfb is running "
            f"on {args.display} and that WINEPREFIX={env['WINEPREFIX']} is valid"
        )

    print("[output]")
    expected = [f"{game_name}.hst", f"{game_name}.xy"]
    for n in range(1, len(players) + 1):
        expected.append(f"{game_name}.m{n}")

    all_ok = True
    for fname in expected:
        fpath = os.path.join(workdir, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            print(f"  {fname:<20s}  {size:>8d} bytes")
        else:
            print(f"  {fname:<20s}  MISSING", file=sys.stderr)
            all_ok = False

    if not all_ok:
        die("one or more expected output files were not created")

    print(f"\nDone. Game files are in {workdir}/")

    if xvfb_proc is not None:
        xvfb_proc.terminate()


if __name__ == "__main__":
    main()
