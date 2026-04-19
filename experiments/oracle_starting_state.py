#!/usr/bin/env python3
"""
oracle_starting_state.py — Confirm starting-state unknowns via stars.exe -a.

Tests run:
  1. Starting population formula (R2.1)
       — Vary growth_rate at fixed PRT/no-LSP → confirm pop is flat or GR-dependent
       — Vary LSP flag → confirm 70% reduction
       — All PRTs at GR=15% no-LSP (now includes IT, SS, PP)
       — IS/CA with/without LSP (cross-check 70% rule)
       — PP on Small map (2 starting worlds)
       — AR growth-rate variation (explain 27.5k vs 50.6k corpus gap)
  2. Starting tech levels per PRT (R2.2) — oracle-verify IT/WM/SD/PP for human races
  3. AI difficulty code mapping (R4.1 / game.def format)
       — Run # 0 / 1 / 2 / 3 with different seeds → identify AI template PRT+LRT+GR

Usage:
    python3 oracle_starting_state.py [--tests pop|tech|ai|all]

Requires:
    - Xvfb running on :99 (or set DISPLAY env var to a live X display)
    - WINEPREFIX=~/.wine32 configured
    - stars.exe at $STARS_EXE (or STARS_RESEARCH_DIR/original/stars.exe)
    - stars_file_parser binaries built (cargo build)

Environment variables:
    STARS_RESEARCH_DIR  Root of the stars-reborn-research repo
                        (default: ~/data/stars/stars-reborn-research)
    STARS_PARSER_DIR    Directory of stars_file_parser binaries
                        (default: ~/data/stars/stars_file_parser/target/debug)
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import tempfile

from stars_automator.config import (
    DEFAULT_DISPLAY,
    DEFAULT_PARSER_DIR,
    DEFAULT_RESEARCH_DIR,
    DEFAULT_STARS_EXE,
    DEFAULT_WINEPREFIX,
)

# ── Configuration ─────────────────────────────────────────────────────────────

RESEARCH = DEFAULT_RESEARCH_DIR
PARSER_DIR = DEFAULT_PARSER_DIR

STARS_EXE = DEFAULT_STARS_EXE
JSON_TO_R1 = os.path.join(PARSER_DIR, "json_to_r1")
JSON_TO_DEF = os.path.join(PARSER_DIR, "json_to_def")
M1_TO_JSON = os.path.join(PARSER_DIR, "m1_to_json")

WINE_ENV = {
    **os.environ,
    "WINEPREFIX": DEFAULT_WINEPREFIX,
    "WINEARCH": "win32",
    "DISPLAY": DEFAULT_DISPLAY,
}

# ── Base race template ────────────────────────────────────────────────────────
# JOAT, broad hab, standard economy — a clean baseline with no side effects.

BASE_RACE = {
    "format_version": 1,
    "name": "Humanoid",
    "plural_name": "Humanoids",
    "prt": "JOAT",
    "lrts": [],
    "hab": {
        "gravity": {"immune": False, "min": 0.22, "max": 4.40},
        "temperature": {"immune": False, "min": -140.0, "max": 140.0},
        "radiation": {"immune": False, "min": 15.0, "max": 85.0},
    },
    "economy": {
        "resource_production": 1000,
        "factory_production": 10,
        "factory_cost": 10,
        "factory_cheap_germanium": False,
        "colonists_operate_factories": 10,
        "mine_production": 10,
        "mine_cost": 5,
        "colonists_operate_mines": 10,
        "growth_rate": 15,
    },
    "research_costs": {
        "energy": "normal",
        "weapons": "normal",
        "propulsion": "normal",
        "construction": "normal",
        "electronics": "normal",
        "biotechnology": "normal",
        "expensive_tech_start_at_4": False,
    },
    "leftover_spend": "surface_minerals",
    "icon_index": 0,
}

# ── Oracle runner ─────────────────────────────────────────────────────────────


def wine_path(linux_path):
    return subprocess.check_output(["winepath", "-w", linux_path], env=WINE_ENV).decode().strip()


def run_oracle(race_json, map_size="tiny", ai_difficulty=2, seed=42, num_ai=1):
    """
    Create a universe with the given race, generate turn 1, and return the
    parsed .m1 turn data for the human player (player 1).

    Returns (m1_data_dict, error_string).  On success error_string is None.
    """
    with tempfile.TemporaryDirectory() as workdir:
        race_json_path = os.path.join(workdir, "race.json")
        r1_path = os.path.join(workdir, "race.r1")
        with open(race_json_path, "w") as f:
            json.dump(race_json, f)
        result = subprocess.run([JSON_TO_R1, race_json_path, r1_path], capture_output=True)
        if result.returncode != 0:
            return None, f"json_to_r1 failed: {result.stderr.decode()}"

        r1_wine = wine_path(r1_path)
        xy_wine = wine_path(os.path.join(workdir, "Game.xy"))

        players = [{"human": {"race_file": r1_wine}}]
        for _ in range(num_ai):
            players.append({"ai": {"difficulty": ai_difficulty, "param": 1}})

        game_def = {
            "game_name": "Game",
            "universe": {
                "map_size": map_size,
                "density": "normal",
                "player_positions": "farther",
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
            "output_xy": xy_wine,
        }

        def_json_path = os.path.join(workdir, "game.json")
        def_path = os.path.join(workdir, "game.def")
        with open(def_json_path, "w") as f:
            json.dump(game_def, f)
        result = subprocess.run([JSON_TO_DEF, def_json_path, def_path], capture_output=True)
        if result.returncode != 0:
            return None, f"json_to_def failed: {result.stderr.decode()}"

        # stars.exe requires relative paths; absolute Linux paths cause silent no-op.
        shutil.copy2(STARS_EXE, os.path.join(workdir, "stars.exe"))

        with open(os.devnull, "w") as devnull:
            subprocess.run(
                ["wine", "stars.exe", "-a", "game.def"],
                cwd=workdir,
                env=WINE_ENV,
                stdout=devnull,
                stderr=devnull,
            )

        m1_path = os.path.join(workdir, "Game.m1")
        if not os.path.exists(m1_path):
            return None, "Game.m1 not created (def parse failure or wine error)"

        result = subprocess.run([M1_TO_JSON, m1_path], capture_output=True)
        if result.returncode != 0:
            return None, f"m1_to_json failed: {result.stderr.decode()}"

        data = json.loads(result.stdout)

        for i in range(num_ai):
            mn_path = os.path.join(workdir, f"Game.m{i + 2}")
            if os.path.exists(mn_path):
                result2 = subprocess.run([M1_TO_JSON, mn_path], capture_output=True)
                if result2.returncode == 0:
                    data[f"ai_player_{i + 1}"] = json.loads(result2.stdout)

        return data, None


def homeworld_pop(m1_data):
    """Return homeworld population in units of 100 colonists."""
    hw_idx = m1_data["player"]["homeworld_planet_idx"]
    for p in m1_data["planets"]:
        if p["planet_index"] == hw_idx:
            return p.get("population")
    return None


def all_planet_pops(m1_data):
    """Return list of (planet_index, population) for all colonised planets."""
    return [
        (p["planet_index"], p.get("population")) for p in m1_data["planets"] if p.get("colonized")
    ]


# ── Test suite 1: Starting population formula (R2.1) ─────────────────────────


def test_starting_population():
    print("=" * 60)
    print("R2.1 — Starting population formula")
    print("=" * 60)

    print("\n--- A. Growth rate variation (JOAT, no LSP, Tiny map) ---")
    print(f"{'Test':<30s}  {'pop×100':>7s}  {'colonists':>10s}")
    for gr in [1, 5, 10, 15, 19]:
        race = copy.deepcopy(BASE_RACE)
        race["economy"]["growth_rate"] = gr
        data, err = run_oracle(race, map_size="tiny", seed=100 + gr)
        if err:
            print(f"  JOAT GR={gr:2d}% no-LSP          ERROR: {err}")
        else:
            pop = homeworld_pop(data)
            print(f"  JOAT GR={gr:2d}% no-LSP          {pop:>7d}  {pop * 100:>10d}")

    print("\n--- B. LSP effect (JOAT GR=15%, Tiny map) ---")
    for lrts, label in [([], "no LSP"), (["LSP"], "+LSP")]:
        race = copy.deepcopy(BASE_RACE)
        race["lrts"] = lrts
        data, err = run_oracle(race, map_size="tiny", seed=200)
        if err:
            print(f"  JOAT GR=15% {label:<8s}  ERROR: {err}")
        else:
            pop = homeworld_pop(data)
            print(f"  JOAT GR=15% {label:<8s}  pop={pop} ({pop * 100} colonists)")

    print("\n--- C. PRT variation (GR=15%, no LSP, Tiny map) ---")
    for prt in ["JOAT", "HE", "SS", "WM", "CA", "IS", "SD", "IT", "AR"]:
        race = copy.deepcopy(BASE_RACE)
        race["prt"] = prt
        data, err = run_oracle(race, map_size="tiny", seed=300)
        if err:
            print(f"  {prt:<6s} GR=15% no-LSP    ERROR: {err}")
        else:
            pop = homeworld_pop(data)
            print(f"  {prt:<6s} GR=15% no-LSP    pop={pop} ({pop * 100} colonists)")

    print("\n--- D. IS/CA with LSP (GR=15%, Tiny map) ---")
    for prt in ["IS", "CA"]:
        for lrts, label in [([], "no LSP"), (["LSP"], "+LSP")]:
            race = copy.deepcopy(BASE_RACE)
            race["prt"] = prt
            race["lrts"] = lrts
            data, err = run_oracle(race, map_size="tiny", seed=400)
            if err:
                print(f"  {prt} GR=15% {label:<8s}  ERROR: {err}")
            else:
                pop = homeworld_pop(data)
                print(f"  {prt} GR=15% {label:<8s}  pop={pop} ({pop * 100} colonists)")

    print("\n--- E. PP with LSP (GR=15%, Small map — 2 starting worlds) ---")
    for lrts, label in [([], "no LSP"), (["LSP"], "+LSP")]:
        race = copy.deepcopy(BASE_RACE)
        race["prt"] = "PP"
        race["lrts"] = lrts
        data, err = run_oracle(race, map_size="small", seed=500)
        if err:
            print(f"  PP GR=15% {label:<8s}  ERROR: {err}")
        else:
            planets = all_planet_pops(data)
            hw_pop = homeworld_pop(data)
            print(
                f"  PP GR=15% {label:<8s}  homeworld={hw_pop} ({hw_pop * 100} col)  "
                f"all colonised planets: {planets}"
            )

    print("\n--- F. AR growth-rate variation (no LSP, Tiny map) ---")
    for gr in [1, 5, 10, 15, 17, 19, 20]:
        race = copy.deepcopy(BASE_RACE)
        race["prt"] = "AR"
        race["economy"]["growth_rate"] = gr
        data, err = run_oracle(race, map_size="tiny", seed=600 + gr)
        if err:
            print(f"  AR GR={gr:2d}% no-LSP          ERROR: {err}")
        else:
            pop = homeworld_pop(data)
            print(
                f"  AR GR={gr:2d}% no-LSP          {pop:>7d}  ({pop * 100 if pop else '?'} colonists)"
            )


# ── Test suite 2: Starting tech levels per PRT (R2.2 verification) ───────────


def test_starting_tech():
    print("\n" + "=" * 60)
    print("R2.2 — Starting tech levels per PRT (human races)")
    print("=" * 60)

    known = {
        "JOAT": dict(energy=3, weapons=3, propulsion=3, construction=3, electronics=3, biology=3),
        "SS": dict(electronics=5),
        "CA": dict(biology=6),
        "IT": dict(propulsion=5, construction=5),
    }

    header = f"{'PRT':<6s}  {'en':>3s}  {'we':>3s}  {'pr':>3s}  {'co':>3s}  {'el':>3s}  {'bi':>3s}  notes"
    print(f"\n{header}")
    print("-" * 60)
    for prt in ["JOAT", "HE", "SS", "WM", "CA", "IS", "SD", "IT", "PP", "AR"]:
        race = copy.deepcopy(BASE_RACE)
        race["prt"] = prt
        data, err = run_oracle(race, map_size="tiny", seed=700)
        if err:
            print(f"  {prt:<6s}  ERROR: {err}")
            continue
        p = data["player"]
        en = p["tech_energy"]
        we = p["tech_weapons"]
        pr = p["tech_propulsion"]
        co = p["tech_construction"]
        el = p["tech_electronics"]
        bi = p["tech_biology"]
        notes = []
        exp = known.get(prt, {})
        for field, val, label in [
            (en, exp.get("energy", 0), "en"),
            (we, exp.get("weapons", 0), "we"),
            (pr, exp.get("propulsion", 0), "pr"),
            (co, exp.get("construction", 0), "co"),
            (el, exp.get("electronics", 0), "el"),
            (bi, exp.get("biology", 0), "bi"),
        ]:
            if field < val:
                notes.append(f"BELOW_EXPECTED({label}≥{val})")
        print(
            f"  {prt:<6s}  {en:>3d}  {we:>3d}  {pr:>3d}  {co:>3d}  {el:>3d}  {bi:>3d}  {', '.join(notes) or 'ok'}"
        )


# ── Test suite 3: AI difficulty code mapping ──────────────────────────────────


def test_ai_difficulty():
    print("\n" + "=" * 60)
    print("AI difficulty code mapping (game.def '# N 1')")
    print("=" * 60)

    for diff in [0, 1, 2, 3]:
        label = {0: "easy", 1: "standard", 2: "harder", 3: "expert"}[diff]
        templates_seen = []
        for seed in [10, 20, 30]:
            race = copy.deepcopy(BASE_RACE)
            data, err = run_oracle(race, map_size="tiny", ai_difficulty=diff, seed=seed, num_ai=1)
            if err:
                templates_seen.append(f"ERROR({err})")
                continue
            ai = data.get("ai_player_1")
            if ai is None:
                templates_seen.append("NO_AI_DATA")
                continue
            ai_race = ai["player"]["race"]
            prt = ai_race["prt"]
            lrts = ",".join(ai_race["lrts"]) or "none"
            gr = ai_race["economy"]["growth_rate"]
            templates_seen.append(f"{prt} [{lrts}] GR={gr}%")

        print(f"\n  difficulty {diff} ({label}):")
        for i, t in enumerate(templates_seen, 1):
            print(f"    seed {i * 10:2d}: {t}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tests",
        choices=["pop", "tech", "ai", "all"],
        default="all",
        help="Which test suites to run (default: all)",
    )
    args = parser.parse_args()

    if args.tests in ("pop", "all"):
        test_starting_population()
    if args.tests in ("tech", "all"):
        test_starting_tech()
    if args.tests in ("ai", "all"):
        test_ai_difficulty()


if __name__ == "__main__":
    main()
