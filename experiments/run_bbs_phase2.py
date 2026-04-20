#!/usr/bin/env python3
"""Run R2.6 Phase 2 — BBS mineral survey.

Creates two single-player games (BBS and baseline, same seed), scouts the
entire universe with all starting fleets, then dumps and compares mineral
concentrations across all planets.

Usage:
    python3 run_bbs_phase2.py [--display :99] [--force] [--max-turns 60]

Options:
    --display     X display for Wine (default: :99)
    --force       Delete and recreate /tmp/<name>/ directories
    --max-turns   Turn-loop limit before giving up (default: 60)

Environment:
    STARS_PARSER_DIR   Path to Rust binary directory
    STARS_EXE          Path to stars.exe

Output:
    experiments/oracle_configs/r2_6/phase2_results.json
"""

import argparse
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import time

from stars_automator.config import DEFAULT_PARSER_DIR
from stars_automator.ini import ensure_stars_ini
from stars_automator.wine import ensure_xvfb, make_wine_env
from stars_automator.x1 import ResearchChange, WaypointAdd, write_x1

HERE = pathlib.Path(__file__).parent
CONFIGS_DIR = HERE / "oracle_configs" / "r2_6"

EXPERIMENTS = [
    "bbs_mineral_survey",
    "baseline_mineral_survey",
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def die(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list, description: str, timeout: int = 120) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        die(
            f"{description} failed (exit {result.returncode})\n"
            f"  cmd: {' '.join(str(c) for c in cmd)}\n"
            f"  stderr: {result.stderr.decode().strip()[:400]}"
        )
    return result


def create_game(cfg_path: pathlib.Path, display: str, timeout: int = 120) -> bool:
    cmd = [sys.executable, "-m", "stars_automator.game", str(cfg_path), "--display", display]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + timeout
    lines = []
    try:
        while True:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                print(f"  [TIMEOUT after {timeout}s]")
                return False
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
            print(f"    {line}", end="", flush=True)
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        print(f"  [ERROR] game creation exited {proc.returncode}")
        return False
    return True


def player1_file(workdir: pathlib.Path, game_name: str) -> pathlib.Path | None:
    """Return the player-1 turn file (Survey.m1). Stars! uses player number, not turn number."""
    p = workdir / f"{game_name}.m1"
    return p if p.exists() else None


# ── Planet coordinate loading ─────────────────────────────────────────────────


def get_planet_map(
    workdir: pathlib.Path, game_name: str, parser_dir: str, env: dict, display: str
) -> list[dict]:
    """Dump the universe map and return list of {number, x, y, name} dicts."""
    mfile = workdir / f"{game_name}.m1"
    if not mfile.exists():
        die(f"player file not found: {mfile}")

    ensure_stars_ini()

    with open(os.devnull, "w") as devnull:
        result = subprocess.run(
            ["wine", "stars.exe", "-dm", mfile.name],
            cwd=workdir,
            env=env,
            stdout=devnull,
            stderr=devnull,
        )
    if result.returncode != 0:
        die(f"stars.exe -dm failed (exit {result.returncode})")

    map_file = next(workdir.glob("*.map"), None)
    if map_file is None:
        die(f"no .map file found in {workdir}")

    map_to_json = os.path.join(parser_dir, "map_to_json")
    result = run([map_to_json, str(map_file)], "map_to_json")
    data = json.loads(result.stdout)
    return data["planets"]


# ── Fleet loading ─────────────────────────────────────────────────────────────


def get_player_fleets(workdir: pathlib.Path, game_name: str, parser_dir: str) -> list[dict]:
    """Parse the current player m-file and return player-0 fleet records."""
    mfile = player1_file(workdir, game_name)
    if mfile is None:
        die(f"no player file found in {workdir}")
    m1_to_json = os.path.join(parser_dir, "m1_to_json")
    result = run([m1_to_json, str(mfile)], "m1_to_json")
    data = json.loads(result.stdout)
    return [f for f in data.get("fleets", []) if f["player_idx"] == 0]


# ── Nearest-neighbour route ───────────────────────────────────────────────────


def nearest_neighbor_route(start_x: float, start_y: float, planets: list[dict]) -> list[dict]:
    """Greedy NN tour: start at (start_x, start_y), visit all planets once."""
    unvisited = list(planets)
    route: list[dict] = []
    cx, cy = start_x, start_y
    while unvisited:
        best = min(unvisited, key=lambda p: (p["x"] - cx) ** 2 + (p["y"] - cy) ** 2)
        route.append(best)
        cx, cy = best["x"], best["y"]
        unvisited.remove(best)
    return route


def assign_routes(fleets: list[dict], planets: list[dict]) -> dict[int, list[dict]]:
    """Assign planets to fleets in contiguous NN-route segments.

    Returns {fleet_index: [planet, ...]} assignments.
    All fleets start at the same homeworld position (turn-1 assumption).
    """
    if not fleets:
        die("no player fleets found — cannot assign routes")

    start_x = fleets[0]["x"]
    start_y = fleets[0]["y"]
    full_route = nearest_neighbor_route(start_x, start_y, planets)

    n = len(fleets)
    chunk = math.ceil(len(full_route) / n)
    assignments: dict[int, list[dict]] = {}
    for i, fleet in enumerate(fleets):
        segment = full_route[i * chunk : (i + 1) * chunk]
        if segment:
            assignments[fleet["fleet_index"]] = segment
    return assignments


# ── x1 generation ────────────────────────────────────────────────────────────


def generate_survey_x1(
    workdir: pathlib.Path, game_name: str, fleets: list[dict], planets: list[dict]
) -> None:
    """Write a Game.x1 file routing all fleets across all planets."""
    assignments = assign_routes(fleets, planets)

    waypoints: list[WaypointAdd] = []
    for fleet_idx, planet_list in assignments.items():
        for wp_nr, planet in enumerate(planet_list, start=1):
            waypoints.append(
                WaypointAdd(
                    fleet_num=fleet_idx,
                    wp_nr=wp_nr,
                    dest_x=planet["x"],
                    dest_y=planet["y"],
                    target_idx=planet["number"] - 1,  # 1-based map_number → 0-based
                    warp=4,
                )
            )

    m1_path = workdir / f"{game_name}.m1"
    x1_path = workdir / f"{game_name}.x1"
    # Direct all research toward Electronics (field 4) to increase scanner range each turn.
    research = [ResearchChange(current_field=4, next_field=4, research_percent=25)]
    write_x1(x1_path, waypoints, m1_path, research)
    print(
        f"  [x1] wrote {len(waypoints)} waypoints across {len(assignments)} fleets → {x1_path.name}"
    )


# ── Planet scan check ─────────────────────────────────────────────────────────


def get_scanned_planet_count(
    workdir: pathlib.Path, game_name: str, parser_dir: str, env: dict
) -> int:
    """Return number of planets currently visible to player 1 via -dp dump."""
    mfile = player1_file(workdir, game_name)
    if mfile is None:
        return 0

    with open(os.devnull, "w") as devnull:
        subprocess.run(
            ["wine", "stars.exe", "-dp", mfile.name],
            cwd=workdir,
            env=env,
            stdout=devnull,
            stderr=devnull,
        )

    pla_file = next(workdir.glob("*.p01"), None) or next(workdir.glob("*.p1"), None)
    if pla_file is None:
        pla_file = next(workdir.glob("*.pla"), None)
    if pla_file is None:
        return 0

    pla_to_json = os.path.join(parser_dir, "pla_to_json")
    result = subprocess.run([pla_to_json, str(pla_file)], capture_output=True)
    if result.returncode != 0:
        return 0
    data = json.loads(result.stdout)
    return len(data.get("planets", []))


# ── Mineral harvest ───────────────────────────────────────────────────────────


def harvest_minerals(
    workdir: pathlib.Path, game_name: str, parser_dir: str, env: dict
) -> list[dict]:
    """Dump planet data and return mineral fields for all known planets."""
    mfile = player1_file(workdir, game_name)
    if mfile is None:
        return []

    with open(os.devnull, "w") as devnull:
        subprocess.run(
            ["wine", "stars.exe", "-dp", mfile.name],
            cwd=workdir,
            env=env,
            stdout=devnull,
            stderr=devnull,
        )

    pla_file = next(workdir.glob("*.p01"), None) or next(workdir.glob("*.p1"), None)
    if pla_file is None:
        pla_file = next(workdir.glob("*.pla"), None)
    if pla_file is None:
        return []

    pla_to_json = os.path.join(parser_dir, "pla_to_json")
    result = subprocess.run([pla_to_json, str(pla_file)], capture_output=True)
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    return [
        {
            "planet_name": p["planet_name"],
            "iron_conc": p["iron_mineral_conc"],
            "bora_conc": p["bora_mineral_conc"],
            "germ_conc": p["germ_mineral_conc"],
            "surface_iron": p["surface_iron"],
            "surface_bora": p["surface_bora"],
            "surface_germ": p["surface_germ"],
        }
        for p in data.get("planets", [])
    ]


# ── Turn loop ─────────────────────────────────────────────────────────────────


def run_survey_loop(
    workdir: pathlib.Path,
    game_name: str,
    parser_dir: str,
    display: str,
    env: dict,
    total_planets: int,
    max_turns: int,
) -> list[dict]:
    """Loop turns until all planets are scanned. Return mineral data."""
    for turn in range(1, max_turns + 1):
        print(f"  [turn {turn}] running stars.exe -g1 ...")
        with open(os.devnull, "w") as devnull:
            result = subprocess.run(
                ["wine", "stars.exe", "-g1", f"{game_name}.hst"],
                cwd=workdir,
                env=env,
                stdout=devnull,
                stderr=devnull,
            )
        if result.returncode != 0:
            print(f"  [WARN] stars.exe -g1 exited {result.returncode}")

        scanned = get_scanned_planet_count(workdir, game_name, parser_dir, env)
        print(f"  [turn {turn}] scanned {scanned}/{total_planets} planets")

        if scanned >= total_planets:
            print(f"  [done] all planets scanned after {turn} turn(s)")
            return harvest_minerals(workdir, game_name, parser_dir, env)

    print(f"  [WARN] reached max_turns={max_turns} with {scanned}/{total_planets} planets scanned")
    return harvest_minerals(workdir, game_name, parser_dir, env)


# ── Main ──────────────────────────────────────────────────────────────────────


def run_experiment(
    name: str,
    display: str,
    parser_dir: str,
    force: bool,
    max_turns: int,
    xvfb_proc,
) -> dict | None:
    cfg_path = CONFIGS_DIR / f"{name}.json"
    if not cfg_path.exists():
        die(f"config not found: {cfg_path}")

    cfg = json.loads(cfg_path.read_text())
    game_name = cfg.get("game_name", "Survey")
    workdir = pathlib.Path(f"/tmp/{name}")

    print(f"\n{'=' * 60}")
    print(f"Experiment: {name}  (bbs_play={cfg['options']['bbs_play']})")
    print(f"{'=' * 60}")

    if force and workdir.exists():
        print(f"  [force] removing {workdir}")
        shutil.rmtree(workdir)

    env = make_wine_env(display=display)

    # Create game if needed
    hst = workdir / f"{game_name}.hst"
    if hst.exists():
        print(f"  [skip] {game_name}.hst already exists")
    else:
        print("  [create]")
        if not create_game(cfg_path, display):
            return {"error": "game creation failed"}

    # Get planet map
    print("  [map] loading planet coordinates ...")
    planets = get_planet_map(workdir, game_name, parser_dir, env, display)
    total_planets = len(planets)
    print(f"  [map] {total_planets} planets in universe")

    # Get starting fleets
    fleets = get_player_fleets(workdir, game_name, parser_dir)
    print(f"  [fleets] {len(fleets)} player-1 fleets at turn 1")

    # Generate and write x1 with full planet survey routes
    print("  [routes] computing NN routes and writing x1 ...")
    generate_survey_x1(workdir, game_name, fleets, planets)

    # Survey loop
    print(f"  [survey] starting turn loop (max {max_turns} turns) ...")
    mineral_data = run_survey_loop(
        workdir, game_name, parser_dir, display, env, total_planets, max_turns
    )

    return {
        "bbs_play": cfg["options"]["bbs_play"],
        "total_planets": total_planets,
        "scanned_planets": len(mineral_data),
        "minerals": {p["planet_name"]: p for p in mineral_data},
    }


def compare_results(bbs: dict, baseline: dict) -> None:
    """Print a summary comparing BBS vs baseline mineral concentrations."""
    bbs_planets = bbs.get("minerals", {})
    base_planets = baseline.get("minerals", {})
    common = set(bbs_planets) & set(base_planets)

    if not common:
        print("\n[compare] no common planets to compare")
        return

    print(f"\n[compare] {len(common)} planets with data in both games")
    iron_ratios, bora_ratios, germ_ratios = [], [], []
    for name in sorted(common):
        b = bbs_planets[name]
        bl = base_planets[name]
        for ratios, key in [
            (iron_ratios, "iron_conc"),
            (bora_ratios, "bora_conc"),
            (germ_ratios, "germ_conc"),
        ]:
            if bl[key] > 0:
                ratios.append(b[key] / bl[key])

    def avg(lst):
        return sum(lst) / len(lst) if lst else float("nan")

    print("  Mean concentration ratio (BBS / baseline):")
    print(f"    Ironium:   {avg(iron_ratios):.4f}  (n={len(iron_ratios)})")
    print(f"    Boranium:  {avg(bora_ratios):.4f}  (n={len(bora_ratios)})")
    print(f"    Germanium: {avg(germ_ratios):.4f}  (n={len(germ_ratios)})")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--display", default=":99")
    ap.add_argument("--force", action="store_true", help="recreate /tmp/<name>/ dirs")
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument(
        "--timeout", type=int, default=120, help="seconds for game creation (default 120)"
    )
    args = ap.parse_args()

    parser_dir = str(DEFAULT_PARSER_DIR)

    xvfb_proc = ensure_xvfb(args.display)

    results: dict[str, dict] = {}
    for name in EXPERIMENTS:
        result = run_experiment(
            name=name,
            display=args.display,
            parser_dir=parser_dir,
            force=args.force,
            max_turns=args.max_turns,
            xvfb_proc=xvfb_proc,
        )
        results[name] = result or {}

    # Compare BBS vs baseline
    bbs_result = results.get("bbs_mineral_survey", {})
    base_result = results.get("baseline_mineral_survey", {})
    if bbs_result and base_result and "error" not in bbs_result and "error" not in base_result:
        compare_results(bbs_result, base_result)

    # Save results
    out_path = CONFIGS_DIR / "phase2_results.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\n[done] Results written to {out_path}")

    if xvfb_proc is not None:
        xvfb_proc.terminate()


if __name__ == "__main__":
    main()
