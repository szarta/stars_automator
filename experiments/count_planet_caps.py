#!/usr/bin/env python3
"""
count_planet_caps.py — R3.2: Measure planet counts for capped size/density combos.

Generates N games each of Huge/Dense (and optionally Large/Dense) using
stars.exe -a, then counts planets from the .xy file via xy_to_json.

NOTE: Packed density fails silently in headless mode (stars.exe -a produces no
output for packed).  Huge/Packed data must be gathered via UI automation.

Usage:
    python3 experiments/count_planet_caps.py [--seeds N] [--start-xvfb]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stars_automator.config import (
    DEFAULT_DISPLAY,
    DEFAULT_PARSER_DIR,
    DEFAULT_STARS_EXE,
)
from stars_automator.wine import ensure_xvfb, make_wine_env, wine_path

PARSER_DIR = DEFAULT_PARSER_DIR
STARS_EXE = DEFAULT_STARS_EXE
XY_TO_JSON = os.path.join(PARSER_DIR, "xy_to_json")
JSON_TO_R1 = os.path.join(PARSER_DIR, "json_to_r1")
JSON_TO_DEF = os.path.join(PARSER_DIR, "json_to_def")

HUMANOID_R1 = os.path.expanduser(
    "~/data/stars/stars-reborn-engine/engine/tests/data/default_races/humanoid.r1"
)

COMBINATIONS = [
    ("huge", "dense"),
    ("large", "dense"),  # sanity check — should NOT be capped
]

BASE_SEED = 50000


def run(cmd, **kwargs):
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    kwargs.setdefault("stderr", subprocess.DEVNULL)
    return subprocess.run(cmd, **kwargs)


def create_game(workdir, size, density, seed, env):
    """Create a game in workdir. Returns True on success."""
    stars_dest = os.path.join(workdir, "stars.exe")
    if not os.path.exists(stars_dest):
        try:
            os.link(STARS_EXE, stars_dest)
        except OSError:
            shutil.copy2(STARS_EXE, stars_dest)

    r1_dest = os.path.join(workdir, "player1.r1")
    shutil.copy2(HUMANOID_R1, r1_dest)

    r1_win = wine_path(r1_dest, env)
    xy_win = wine_path(os.path.join(workdir, "Game.xy"), env)

    game_def = {
        "game_name": "Game",
        "universe": {
            "map_size": size,
            "density": density,
            "player_positions": "farther",
            "seed": seed,
        },
        "options": {
            "max_minerals": False,
            "slow_tech": False,
            "bbs_play": False,
            "galaxy_clumping": False,
            "computer_alliances": False,
            "no_random_events": False,
            "public_scores": False,
        },
        "players": [{"human": {"race_file": r1_win}}],
        "victory": {
            "planets": {"enabled": True, "percent": 60},
            "tech": {"enabled": True, "level": 26, "fields": 4},
            "score": {"enabled": False, "score": 5000},
            "exceeds_nearest": {"enabled": False, "percent": 150},
            "production": {"enabled": False, "capacity": 100},
            "capital_ships": {"enabled": False, "number": 100},
            "turns": {"enabled": False, "years": 100},
            "must_meet": 1,
            "min_years": 50,
        },
        "output_xy": xy_win,
    }

    json_path = os.path.join(workdir, "game.json")
    def_path = os.path.join(workdir, "game.def")
    with open(json_path, "w") as f:
        json.dump(game_def, f)

    r = run([JSON_TO_DEF, json_path, def_path])
    if r.returncode != 0:
        return False

    r = run(["wine", "stars.exe", "-a", "game.def"], cwd=workdir, env=env)
    if r.returncode != 0:
        return False

    return os.path.exists(os.path.join(workdir, "Game.xy"))


def count_planets(xy_path):
    r = subprocess.run([XY_TO_JSON, xy_path], capture_output=True)
    if r.returncode != 0:
        return None
    data = json.loads(r.stdout)
    return data.get("planet_count")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--seeds", type=int, default=10, help="Number of seeds per combination (default: 10)"
    )
    parser.add_argument("--display", default=DEFAULT_DISPLAY)
    parser.add_argument("--start-xvfb", action="store_true")
    args = parser.parse_args()

    env = make_wine_env(display=args.display)

    if args.start_xvfb:
        print("[xvfb] starting...")
        ensure_xvfb(args.display)

    results = {}

    for size, density in COMBINATIONS:
        label = f"{size}/{density}"
        counts = []
        print(f"\n=== {label} ({args.seeds} seeds) ===")
        for i in range(args.seeds):
            seed = BASE_SEED + i
            with tempfile.TemporaryDirectory(prefix=f"r3_2_{size}_{density}_{seed}_") as workdir:
                ok = create_game(workdir, size, density, seed, env)
                if not ok:
                    print(f"  seed {seed}: FAILED to create game")
                    continue
                xy_path = os.path.join(workdir, "Game.xy")
                n = count_planets(xy_path)
                if n is None:
                    print(f"  seed {seed}: FAILED to parse .xy")
                    continue
                counts.append(n)
                print(f"  seed {seed}: {n} planets")

        if counts:
            results[label] = counts
            print(
                f"  → min={min(counts)} max={max(counts)} mean={sum(counts) / len(counts):.1f} n={len(counts)}"
            )
        else:
            print("  → no successful games")

    print("\n=== SUMMARY ===")
    for label, counts in results.items():
        print(
            f"{label}: n={len(counts)} min={min(counts)} max={max(counts)} mean={sum(counts) / len(counts):.1f}"
        )
        dist = {}
        for c in counts:
            dist[c] = dist.get(c, 0) + 1
        for val in sorted(dist):
            print(f"  {val}: {dist[val]}x")

    out = {
        "experiment": "R3.2 planet count caps",
        "base_seed": BASE_SEED,
        "seeds_per_combo": args.seeds,
        "results": {label: counts for label, counts in results.items()},
    }
    out_path = os.path.join(os.path.dirname(__file__), "oracle_configs", "r3_2_planet_caps.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
