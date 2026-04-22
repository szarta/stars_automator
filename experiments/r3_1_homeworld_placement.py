#!/usr/bin/env python3
"""
r3_1_homeworld_placement.py — R3.1: Measure homeworld placement by player_positions setting.

For each of the four player_positions values (close, moderate, farther, distant),
generates N games on a Small/Normal map with 6 players, then extracts homeworld
coordinates from each player's .mN file and computes pairwise Euclidean distances.

Each player's .mN file contains a `player.homeworld_planet_idx` field, and the
starting fleet at that planet carries the (x, y) coordinates.

Usage:
    python3 experiments/r3_1_homeworld_placement.py [--seeds N] [--start-xvfb] [--force]

Options:
    --seeds N       Number of seeds per player_positions setting (default: 10)
    --start-xvfb    Start Xvfb on display :99 if not already running
    --force         Recreate game directories even if they already exist

Results are written to:
    experiments/oracle_configs/r3_1/results.json
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stars_automator.config import (
    DEFAULT_DISPLAY,
    DEFAULT_PARSER_DIR,
    DEFAULT_STARS_EXE,
)
from stars_automator.ini import ensure_stars_ini
from stars_automator.wine import ensure_xvfb, make_wine_env, wine_path

HERE = os.path.dirname(os.path.abspath(__file__))
PARSER_DIR = DEFAULT_PARSER_DIR
STARS_EXE = DEFAULT_STARS_EXE
M1_TO_JSON = os.path.join(PARSER_DIR, "m1_to_json")
JSON_TO_R1 = os.path.join(PARSER_DIR, "json_to_r1")
JSON_TO_DEF = os.path.join(PARSER_DIR, "json_to_def")

HUMAN_R1 = os.path.expanduser("~/data/stars/stars-reborn-research/original/stars.r1")

# Experiment parameters
MAP_SIZE = "small"
DENSITY = "normal"
N_HUMAN = 1
N_AI = 5
BASE_SEED = 31000

PLAYER_POSITIONS = ["close", "moderate", "farther", "distant"]

RESULTS_DIR = os.path.join(HERE, "oracle_configs", "r3_1")
RESULTS_FILE = os.path.join(RESULTS_DIR, "results.json")


def run_silent(cmd, cwd=None, env=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_game(workdir, game_name, player_positions, seed, env):
    """Create a game in workdir. Returns True on success."""
    stars_dest = os.path.join(workdir, "stars.exe")
    if not os.path.exists(stars_dest):
        try:
            os.link(STARS_EXE, stars_dest)
        except OSError:
            shutil.copy2(STARS_EXE, stars_dest)

    r1_dest = os.path.join(workdir, "player1.r1")
    shutil.copy2(HUMAN_R1, r1_dest)

    r1_win = wine_path(r1_dest, env)
    xy_win = wine_path(os.path.join(workdir, f"{game_name}.xy"), env)

    players = [{"human": {"race_file": r1_win}}]
    for _ in range(N_AI):
        players.append({"ai": {"difficulty": 2, "param": 1}})

    game_def = {
        "game_name": game_name,
        "universe": {
            "map_size": MAP_SIZE,
            "density": DENSITY,
            "player_positions": player_positions,
            "seed": seed,
        },
        "options": {
            "max_minerals": False,
            "slow_tech": False,
            "bbs_play": False,
            "galaxy_clumping": False,
            "computer_alliances": False,
            "no_random_events": True,
            "public_scores": False,
        },
        "players": players,
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

    def_json = os.path.join(workdir, "game.json")
    def_file = os.path.join(workdir, "game.def")
    with open(def_json, "w") as f:
        json.dump(game_def, f, indent=2)

    r = run_silent([JSON_TO_DEF, def_json, def_file], cwd=workdir)
    if r.returncode != 0:
        return False

    ensure_stars_ini()
    r = run_silent(
        ["wine", "stars.exe", "-a", "game.def"],
        cwd=workdir,
        env=env,
    )
    return r.returncode == 0


def get_homeworld_coord(m_file):
    """
    Parse a .mN file and return (planet_idx, x, y) for the homeworld.
    Returns None if the file cannot be parsed or has no homeworld fleet.
    """
    result = subprocess.run(
        [M1_TO_JSON, m_file],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    hw_idx = data["player"]["homeworld_planet_idx"]
    fleets = data.get("fleets", [])
    for fleet in fleets:
        if fleet["orbit_planet_idx"] == hw_idx and not fleet["en_route"]:
            return (hw_idx, fleet["x"], fleet["y"])
    return None


def euclidean(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def analyse_game(workdir, game_name, n_players):
    """
    Parse all .mN files, extract homeworld coords, compute pairwise distances.
    Returns a dict with homeworld list and distance stats, or None on failure.
    """
    homeworlds = []
    for n in range(1, n_players + 1):
        m_file = os.path.join(workdir, f"{game_name}.m{n}")
        if not os.path.isfile(m_file):
            continue
        coord = get_homeworld_coord(m_file)
        if coord is None:
            print(f"    [warn] could not read {game_name}.m{n}")
            continue
        homeworlds.append({"player": n, "planet_idx": coord[0], "x": coord[1], "y": coord[2]})

    if len(homeworlds) < 2:
        return None

    coords = [(hw["x"], hw["y"]) for hw in homeworlds]
    distances = []
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            distances.append(round(euclidean(coords[i], coords[j]), 2))

    distances.sort()
    return {
        "homeworlds": homeworlds,
        "n_homeworlds": len(homeworlds),
        "distances": distances,
        "min_dist": distances[0],
        "max_dist": distances[-1],
        "mean_dist": round(sum(distances) / len(distances), 2),
        "median_dist": round(distances[len(distances) // 2], 2),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=10,
        help="Number of seeds per player_positions setting (default: 10)",
    )
    parser.add_argument("--start-xvfb", action="store_true", help="Start Xvfb on display :99")
    parser.add_argument(
        "--force", action="store_true", help="Delete and recreate existing game directories"
    )
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    env = make_wine_env(display=DEFAULT_DISPLAY)

    if args.start_xvfb:
        print("[xvfb] starting Xvfb")
        ensure_xvfb(DEFAULT_DISPLAY)

    n_total = len(PLAYER_POSITIONS) * args.seeds
    done = 0
    all_results = []

    for setting in PLAYER_POSITIONS:
        setting_results = []
        print(f"\n=== player_positions={setting} ===")

        for seed_offset in range(args.seeds):
            seed = BASE_SEED + seed_offset
            name = f"r3_1_{setting}_s{seed}"
            workdir = os.path.join("/tmp", name)

            done += 1
            print(f"  [{done}/{n_total}] {name}")

            if args.force and os.path.exists(workdir):
                shutil.rmtree(workdir)

            if not os.path.exists(workdir):
                os.makedirs(workdir)
                ok = create_game(workdir, "Game", setting, seed, env)
                if not ok:
                    print(f"    [error] game creation failed for {name}")
                    continue
            else:
                print("    [skip] already exists")

            n_players = N_HUMAN + N_AI
            result = analyse_game(workdir, "Game", n_players)
            if result is None:
                print(f"    [error] analysis failed for {name}")
                continue

            result["setting"] = setting
            result["seed"] = seed
            setting_results.append(result)

            min_d = result["min_dist"]
            max_d = result["max_dist"]
            mean_d = result["mean_dist"]
            n_hw = result["n_homeworlds"]
            print(f"    n={n_hw}  min={min_d:.0f}  max={max_d:.0f}  mean={mean_d:.0f} ly")

        all_results.extend(setting_results)

        if setting_results:
            all_mins = [r["min_dist"] for r in setting_results]
            all_maxs = [r["max_dist"] for r in setting_results]
            all_means = [r["mean_dist"] for r in setting_results]
            print(
                f"  SUMMARY: min_dist range [{min(all_mins):.0f}, {max(all_mins):.0f}]  "
                f"max_dist range [{min(all_maxs):.0f}, {max(all_maxs):.0f}]  "
                f"mean_dist range [{min(all_means):.0f}, {max(all_means):.0f}]"
            )

    output = {
        "experiment": "R3.1 homeworld placement",
        "map_size": MAP_SIZE,
        "density": DENSITY,
        "n_players": N_HUMAN + N_AI,
        "n_seeds": args.seeds,
        "base_seed": BASE_SEED,
        "results": all_results,
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults written to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
