#!/usr/bin/env python3
"""
r3_6_homeworld_distribution.py — R3.6: Player starting location distribution.

Three sub-experiments run in sequence:

  Part A — Distribution: single-player games across all map sizes / densities.
    Generates games with 1 human + 1 AI.  Extracts human homeworld (x, y),
    normalises to [0, 1] within the known bounding box, and records:
      - normalised coords (nx, ny)
      - distance from map centre (sqrt((nx-0.5)²+(ny-0.5)²))
      - distance from nearest edge (min(nx, 1-nx, ny, 1-ny))
    Goal: detect edge exclusion zones and/or centre bias.

  Part B — Separation threshold scaling: 6-player games across all map sizes,
    all four player_positions settings.
    Measures min pairwise Euclidean distance (raw and normalised by map dim).
    Goal: determine whether the R3.1 thresholds are absolute constants or
    scale proportionally with map size.

  Part C — PP / IT second starting planet: games with PP and IT races on
    non-Tiny maps (PP and IT do not receive a second planet on Tiny maps).
    Records main homeworld + second planet positions, distance between them,
    and each planet's normalised position relative to the bounding box.
    Goal: characterise where the second starting planet is placed.

Usage:
    python3 experiments/r3_6_homeworld_distribution.py [--seeds N] [--start-xvfb]
                                                       [--part a|b|c|all] [--force]

Options:
    --seeds N         Seeds per combination (default: 15)
    --start-xvfb      Start Xvfb on display :99 if not already running
    --part a|b|c|all  Which sub-experiment(s) to run (default: all)
    --force           Recreate game directories even if they already exist

Results:
    experiments/oracle_configs/r3_6/distribution.json   (Part A)
    experiments/oracle_configs/r3_6/scaling.json        (Part B)
    experiments/oracle_configs/r3_6/second_planet.json  (Part C)
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
JSON_TO_DEF = os.path.join(PARSER_DIR, "json_to_def")

HUMAN_R1 = os.path.expanduser("~/data/stars/stars-reborn-research/original/stars.r1")
PP_R1 = os.path.expanduser("~/data/stars/stars-reborn-research/original/basic_races/basic_pp.r1")
IT_R1 = os.path.expanduser("~/data/stars/stars-reborn-research/original/basic_races/basic_it.r1")

# Known universe bounding boxes: [origin, origin+dim] in both axes.
# Origin confirmed ~1000; dim from design doc (universe_parameters.rst).
MAP_DIMS = {
    "tiny": 400,
    "small": 800,
    "medium": 1200,
    "large": 1600,
    "huge": 2000,
}
MAP_ORIGIN = 1000  # coordinates start at ~1000

ALL_SIZES = ["tiny", "small", "medium", "large", "huge"]
ALL_DENSITIES = ["sparse", "normal", "dense"]
PLAYER_POSITIONS = ["close", "moderate", "farther", "distant"]

RESULTS_DIR = os.path.join(HERE, "oracle_configs", "r3_6")
BASE_SEED_A = 36000
BASE_SEED_B = 36500
BASE_SEED_C = 37000

# Map sizes where PP/IT get a second starting planet (not Tiny)
SECOND_PLANET_SIZES = ["small", "medium", "large", "huge"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def run_silent(cmd, cwd=None, env=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_game(
    workdir, game_name, map_size, density, player_positions, seed, players, env, human_r1=None
):
    """Create a Stars! game headlessly. Returns True on success."""
    if human_r1 is None:
        human_r1 = HUMAN_R1

    stars_dest = os.path.join(workdir, "stars.exe")
    if not os.path.exists(stars_dest):
        try:
            os.link(STARS_EXE, stars_dest)
        except OSError:
            shutil.copy2(STARS_EXE, stars_dest)

    r1_dest = os.path.join(workdir, "player1.r1")
    shutil.copy2(human_r1, r1_dest)
    r1_win = wine_path(r1_dest, env)

    player_list = [{"human": {"race_file": r1_win}}]
    for _ in range(players - 1):
        player_list.append({"ai": {"difficulty": 2, "param": 1}})

    xy_win = wine_path(os.path.join(workdir, f"{game_name}.xy"), env)

    game_def = {
        "game_name": game_name,
        "universe": {
            "map_size": map_size,
            "density": density,
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
        "players": player_list,
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
    r = run_silent(["wine", "stars.exe", "-a", "game.def"], cwd=workdir, env=env)
    return r.returncode == 0


def get_homeworld_coord(m_file):
    """Return (planet_idx, x, y) for the homeworld in a .mN file, or None."""
    result = subprocess.run([M1_TO_JSON, m_file], capture_output=True)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    hw_idx = data["player"]["homeworld_planet_idx"]
    for fleet in data.get("fleets", []):
        if fleet["orbit_planet_idx"] == hw_idx and not fleet["en_route"]:
            return (hw_idx, fleet["x"], fleet["y"])
    return None


def normalise(x, y, map_size):
    dim = MAP_DIMS[map_size]
    nx = (x - MAP_ORIGIN) / dim
    ny = (y - MAP_ORIGIN) / dim
    return nx, ny


def euclidean(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# ---------------------------------------------------------------------------
# Part A: Distribution
# ---------------------------------------------------------------------------


def run_part_a(n_seeds, force, env):
    """
    Single-player games (1 human + 1 AI) across all sizes × densities.
    Records normalised homeworld position and edge/centre distances.
    """
    print("\n=== Part A: Homeworld position distribution ===")
    results = []

    combos = [(sz, dn) for sz in ALL_SIZES for dn in ALL_DENSITIES]
    total = len(combos) * n_seeds
    done = 0

    for map_size, density in combos:
        combo_results = []
        print(f"\n  {map_size}/{density}")

        for seed_offset in range(n_seeds):
            seed = BASE_SEED_A + seed_offset
            name = f"r3_6a_{map_size}_{density}_s{seed}"
            workdir = os.path.join("/tmp", name)
            done += 1

            if force and os.path.exists(workdir):
                shutil.rmtree(workdir)

            if not os.path.exists(workdir):
                os.makedirs(workdir)
                ok = create_game(
                    workdir, "Game", map_size, density, "moderate", seed, players=2, env=env
                )
                if not ok:
                    print(f"    [{done}/{total}] FAIL game creation {name}")
                    continue
            # else: skip silently (already exists)

            hw = get_homeworld_coord(os.path.join(workdir, "Game.m1"))
            if hw is None:
                print(f"    [{done}/{total}] FAIL parse {name}")
                continue

            planet_idx, x, y = hw
            nx, ny = normalise(x, y, map_size)
            centre_dist = math.sqrt((nx - 0.5) ** 2 + (ny - 0.5) ** 2)
            edge_dist = min(nx, 1.0 - nx, ny, 1.0 - ny)

            combo_results.append(
                {
                    "map_size": map_size,
                    "density": density,
                    "seed": seed,
                    "planet_idx": planet_idx,
                    "x": x,
                    "y": y,
                    "nx": round(nx, 4),
                    "ny": round(ny, 4),
                    "centre_dist": round(centre_dist, 4),
                    "edge_dist": round(edge_dist, 4),
                }
            )

        results.extend(combo_results)

        if combo_results:
            edge_dists = [r["edge_dist"] for r in combo_results]
            centre_dists = [r["centre_dist"] for r in combo_results]
            min_edge = min(edge_dists)
            mean_edge = sum(edge_dists) / len(edge_dists)
            mean_ctr = sum(centre_dists) / len(centre_dists)
            print(
                f"    n={len(combo_results)}  min_edge={min_edge:.3f}  "
                f"mean_edge={mean_edge:.3f}  mean_ctr={mean_ctr:.3f}"
            )

    out = {
        "experiment": "R3.6 Part A — homeworld position distribution",
        "player_positions": "moderate",
        "n_players": 2,
        "human_player": 1,
        "n_seeds": n_seeds,
        "base_seed": BASE_SEED_A,
        "results": results,
    }
    path = os.path.join(RESULTS_DIR, "distribution.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Written: {path}  ({len(results)} entries)")
    return results


# ---------------------------------------------------------------------------
# Part B: Separation threshold scaling
# ---------------------------------------------------------------------------


def run_part_b(n_seeds, force, env):
    """
    6-player games across all sizes × all player_positions settings.
    Measures min pairwise homeworld distance (raw and normalised by dim).
    """
    print("\n=== Part B: Separation threshold scaling ===")
    results = []

    N_PLAYERS = 6
    combos = [(sz, pp) for sz in ALL_SIZES for pp in PLAYER_POSITIONS]
    total = len(combos) * n_seeds
    done = 0

    for map_size, player_positions in combos:
        combo_results = []
        print(f"\n  {map_size}/{player_positions}")
        dim = MAP_DIMS[map_size]

        for seed_offset in range(n_seeds):
            seed = BASE_SEED_B + seed_offset
            name = f"r3_6b_{map_size}_{player_positions}_s{seed}"
            workdir = os.path.join("/tmp", name)
            done += 1

            if force and os.path.exists(workdir):
                shutil.rmtree(workdir)

            if not os.path.exists(workdir):
                os.makedirs(workdir)
                ok = create_game(
                    workdir,
                    "Game",
                    map_size,
                    "normal",
                    player_positions,
                    seed,
                    players=N_PLAYERS,
                    env=env,
                )
                if not ok:
                    print(f"    [{done}/{total}] FAIL game creation {name}")
                    continue

            homeworlds = []
            actual_players = 0
            for pn in range(1, N_PLAYERS + 1):
                m_file = os.path.join(workdir, f"Game.m{pn}")
                if not os.path.isfile(m_file):
                    break
                hw = get_homeworld_coord(m_file)
                if hw is None:
                    print(f"    [{done}/{total}] WARN no homeworld in m{pn}")
                    continue
                actual_players += 1
                homeworlds.append({"player": pn, "planet_idx": hw[0], "x": hw[1], "y": hw[2]})

            if len(homeworlds) < 2:
                print(f"    [{done}/{total}] FAIL < 2 homeworlds {name}")
                continue

            coords = [(hw["x"], hw["y"]) for hw in homeworlds]
            distances = sorted(
                round(euclidean(coords[i], coords[j]), 2)
                for i in range(len(coords))
                for j in range(i + 1, len(coords))
            )
            min_d = distances[0]

            combo_results.append(
                {
                    "map_size": map_size,
                    "density": "normal",
                    "player_positions": player_positions,
                    "seed": seed,
                    "n_homeworlds": len(homeworlds),
                    "homeworlds": homeworlds,
                    "min_dist": min_d,
                    "min_dist_norm": round(min_d / dim, 4),
                    "max_dist": distances[-1],
                    "mean_dist": round(sum(distances) / len(distances), 2),
                    "distances": distances,
                }
            )

        results.extend(combo_results)

        if combo_results:
            all_mins = [r["min_dist"] for r in combo_results]
            all_norms = [r["min_dist_norm"] for r in combo_results]
            print(
                f"    n={len(combo_results)}  "
                f"min_dist range [{min(all_mins):.0f}, {max(all_mins):.0f}] ly  "
                f"norm [{min(all_norms):.3f}, {max(all_norms):.3f}]"
            )

    out = {
        "experiment": "R3.6 Part B — separation threshold scaling",
        "n_players": N_PLAYERS,
        "density": "normal",
        "n_seeds": n_seeds,
        "base_seed": BASE_SEED_B,
        "results": results,
    }
    path = os.path.join(RESULTS_DIR, "scaling.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Written: {path}  ({len(results)} entries)")
    return results


# ---------------------------------------------------------------------------
# Part C: PP / IT second starting planet
# ---------------------------------------------------------------------------


def get_all_starting_planets(m_file):
    """
    Return list of {planet_idx, x, y} for every colonised starting planet the
    player owns at turn 0 (main homeworld + second planet for PP/IT).
    Also returns the race PRT string.
    Returns (prt, [planets]) or (None, []) on failure.
    """
    result = subprocess.run([M1_TO_JSON, m_file], capture_output=True)
    if result.returncode != 0:
        return None, []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, []

    prt = data["player"]["race"].get("prt", "?")
    hw_idx = data["player"]["homeworld_planet_idx"]

    # Build coord map: planet_idx → (x, y) from non-en-route fleets
    coord_map = {}
    for fleet in data.get("fleets", []):
        idx = fleet.get("orbit_planet_idx")
        if idx is not None and not fleet.get("en_route"):
            coord_map[idx] = (fleet["x"], fleet["y"])

    planets = []
    for planet in data.get("planets", []):
        idx = planet.get("planet_index")
        if idx is None or not planet.get("colonized"):
            continue
        coords = coord_map.get(idx)
        if coords is None:
            continue
        planets.append(
            {
                "planet_idx": idx,
                "x": coords[0],
                "y": coords[1],
                "is_homeworld": (idx == hw_idx),
            }
        )

    return prt, planets


def run_part_c(n_seeds, force, env):
    """
    PP and IT races on non-Tiny maps.  Extracts both starting planet positions
    and records distance + normalised coords for each.
    """
    print("\n=== Part C: PP / IT second starting planet ===")
    results = []

    combos = [("PP", PP_R1, sz) for sz in SECOND_PLANET_SIZES] + [
        ("IT", IT_R1, sz) for sz in SECOND_PLANET_SIZES
    ]

    total = len(combos) * n_seeds
    done = 0

    for prt_label, r1_path, map_size in combos:
        combo_results = []
        dim = MAP_DIMS[map_size]
        print(f"\n  {prt_label}/{map_size}")

        for seed_offset in range(n_seeds):
            seed = BASE_SEED_C + seed_offset
            name = f"r3_6c_{prt_label.lower()}_{map_size}_s{seed}"
            workdir = os.path.join("/tmp", name)
            done += 1

            if force and os.path.exists(workdir):
                shutil.rmtree(workdir)

            if not os.path.exists(workdir):
                os.makedirs(workdir)
                ok = create_game(
                    workdir,
                    "Game",
                    map_size,
                    "normal",
                    "moderate",
                    seed,
                    players=2,
                    env=env,
                    human_r1=r1_path,
                )
                if not ok:
                    print(f"    [{done}/{total}] FAIL game creation {name}")
                    continue

            prt, planets = get_all_starting_planets(os.path.join(workdir, "Game.m1"))
            if not planets:
                print(f"    [{done}/{total}] FAIL no planets {name}")
                continue

            hw = next((p for p in planets if p["is_homeworld"]), None)
            others = [p for p in planets if not p["is_homeworld"]]

            if hw is None:
                print(f"    [{done}/{total}] WARN no homeworld found {name}")
                continue

            hw_nx, hw_ny = normalise(hw["x"], hw["y"], map_size)
            entry = {
                "prt": prt,
                "map_size": map_size,
                "seed": seed,
                "homeworld": {
                    "planet_idx": hw["planet_idx"],
                    "x": hw["x"],
                    "y": hw["y"],
                    "nx": round(hw_nx, 4),
                    "ny": round(hw_ny, 4),
                    "centre_dist": round(math.sqrt((hw_nx - 0.5) ** 2 + (hw_ny - 0.5) ** 2), 4),
                    "edge_dist": round(min(hw_nx, 1.0 - hw_nx, hw_ny, 1.0 - hw_ny), 4),
                },
                "second_planet": None,
                "inter_planet_dist": None,
                "inter_planet_dist_norm": None,
            }

            if others:
                sp = others[0]
                sp_nx, sp_ny = normalise(sp["x"], sp["y"], map_size)
                dist = euclidean((hw["x"], hw["y"]), (sp["x"], sp["y"]))
                entry["second_planet"] = {
                    "planet_idx": sp["planet_idx"],
                    "x": sp["x"],
                    "y": sp["y"],
                    "nx": round(sp_nx, 4),
                    "ny": round(sp_ny, 4),
                    "centre_dist": round(math.sqrt((sp_nx - 0.5) ** 2 + (sp_ny - 0.5) ** 2), 4),
                    "edge_dist": round(min(sp_nx, 1.0 - sp_nx, sp_ny, 1.0 - sp_ny), 4),
                }
                entry["inter_planet_dist"] = round(dist, 2)
                entry["inter_planet_dist_norm"] = round(dist / dim, 4)

            combo_results.append(entry)

        results.extend(combo_results)

        if combo_results:
            with_second = [r for r in combo_results if r["second_planet"]]
            print(
                f"    n={len(combo_results)}  "
                f"second_planet_found={len(with_second)}/{len(combo_results)}"
            )
            if with_second:
                dists = [r["inter_planet_dist"] for r in with_second]
                norms = [r["inter_planet_dist_norm"] for r in with_second]
                print(
                    f"    inter-planet dist range [{min(dists):.0f}, {max(dists):.0f}] ly  "
                    f"norm [{min(norms):.3f}, {max(norms):.3f}]"
                )

    out = {
        "experiment": "R3.6 Part C — PP/IT second starting planet",
        "player_positions": "moderate",
        "density": "normal",
        "n_players": 2,
        "n_seeds": n_seeds,
        "base_seed": BASE_SEED_C,
        "results": results,
    }
    path = os.path.join(RESULTS_DIR, "second_planet.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Written: {path}  ({len(results)} entries)")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=15)
    parser.add_argument("--start-xvfb", action="store_true")
    parser.add_argument("--part", choices=["a", "b", "c", "all"], default="all")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    env = make_wine_env(display=DEFAULT_DISPLAY)
    if args.start_xvfb:
        print("[xvfb] starting Xvfb")
        ensure_xvfb(DEFAULT_DISPLAY)

    if args.part in ("a", "all"):
        run_part_a(args.seeds, args.force, env)

    if args.part in ("b", "all"):
        run_part_b(args.seeds, args.force, env)

    if args.part in ("c", "all"):
        run_part_c(args.seeds, args.force, env)

    print("\nDone.")


if __name__ == "__main__":
    main()
