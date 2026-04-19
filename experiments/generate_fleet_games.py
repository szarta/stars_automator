#!/usr/bin/env python3
"""
Generate Stars! games for the R2.3 starting fleet oracle experiment.

Reads _meta.json files written by setup_fleet_experiment.py and runs
stars.exe -a for each game that does not yet have a .hst file.
Supports parallel workers and is fully resumable.

Usage:
  python3 generate_fleet_games.py [--workers N] [--display :99]
                                   [--start-xvfb] [--prt PRT]
                                   [--dry-run]

Completed games are skipped automatically.  Failures are logged to
  $STARS_RESEARCH_DIR/original/race_fleet_permutation_games/_errors.log
and can be retried by re-running the script.

Environment variables:
  STARS_RESEARCH_DIR  Root of the stars-reborn-research repo
                      (default: ~/data/stars/stars-reborn-research)
  STARS_PARSER_DIR    Directory of stars_file_parser binaries
                      (default: ~/data/stars/stars_file_parser/target/debug)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_RESEARCH  = Path(
    os.environ.get("STARS_RESEARCH_DIR", "~/data/stars/stars-reborn-research")
).expanduser()
_PARSER    = Path(
    os.environ.get("STARS_PARSER_DIR", "~/data/stars/stars_file_parser/target/debug")
).expanduser()

BASE_DIR   = _RESEARCH / "original" / "race_fleet_permutation_games"
RACES_DIR  = _RESEARCH / "original" / "race_ship_permutations"
PARSER_DIR = _PARSER
JSON_TO_R1  = PARSER_DIR / "json_to_r1"
JSON_TO_DEF = PARSER_DIR / "json_to_def"

PRTS = ["HE", "SS", "WM", "CA", "IS", "SD", "PP", "IT", "AR", "JOAT"]

DEFAULT_OPTIONS = {
    "max_minerals":       False,
    "slow_tech":          False,
    "bbs_play":           False,
    "galaxy_clumping":    False,
    "computer_alliances": False,
    "no_random_events":   False,
    "public_scores":      False,
}

DEFAULT_VICTORY = {
    "planets":         {"enabled": True,  "percent": 60},
    "tech":            {"enabled": True,  "level": 26, "fields": 4},
    "score":           {"enabled": False, "score": 5000},
    "exceeds_nearest": {"enabled": False, "percent": 150},
    "production":      {"enabled": False, "capacity": 100},
    "capital_ships":   {"enabled": False, "number": 100},
    "turns":           {"enabled": False, "years": 100},
    "must_meet": 1,
    "min_years": 50,
}


def wine_env(display: str) -> dict:
    return {
        **os.environ,
        "WINEPREFIX": os.path.expanduser("~/.wine32"),
        "WINEARCH":   "win32",
        "DISPLAY":    display,
    }


def to_wine_path(p: Path) -> str:
    """Convert an absolute Linux path to Wine Z: Windows notation."""
    return "Z:" + str(p.resolve()).replace("/", "\\")


def generate_game(game_dir: Path, display: str) -> tuple[bool, str]:
    """
    Create one Stars! game from a pre-populated game directory.
    Returns (success, message).
    """
    meta_path = game_dir / "_meta.json"
    if not meta_path.exists():
        return False, f"missing _meta.json in {game_dir}"

    meta = json.loads(meta_path.read_text())
    game_name  = meta["game_name"]
    uparams    = meta["universe"]
    race_stems = meta["races"]

    if (game_dir / f"{game_name}.hst").exists():
        return True, f"skip (done): {game_dir.name}"

    env = wine_env(display)

    r1_wine_paths = []
    for player_idx, stem in enumerate(race_stems, start=1):
        json_path = RACES_DIR / f"{stem}.json"
        r1_path   = game_dir / f"player{player_idx}.r1"
        result = subprocess.run(
            [str(JSON_TO_R1), str(json_path), str(r1_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            return False, (f"json_to_r1 failed for {stem}: "
                           f"{result.stderr.decode().strip()}")
        r1_wine_paths.append(to_wine_path(r1_path))

    options = {
        **DEFAULT_OPTIONS,
        "galaxy_clumping": uparams["galaxy_clumping"],
        "bbs_play":        uparams["accelerated_bbs"],
    }
    game_def = {
        "game_name": game_name,
        "universe":  {
            "map_size":         uparams["map_size"],
            "density":          uparams["density"],
            "player_positions": uparams["player_positions"],
            "seed":             uparams["seed"],
        },
        "options": options,
        "players": [{"human": {"race_file": wp}} for wp in r1_wine_paths],
        "victory": DEFAULT_VICTORY,
        "output_xy": to_wine_path(game_dir / f"{game_name}.xy"),
    }

    def_json_path = game_dir / "game.json"
    def_json_path.write_text(json.dumps(game_def, indent=2) + "\n")

    def_path = game_dir / "game.def"
    result = subprocess.run(
        [str(JSON_TO_DEF), str(def_json_path), str(def_path)],
        capture_output=True,
    )
    if result.returncode != 0:
        return False, f"json_to_def failed: {result.stderr.decode().strip()}"

    try:
        with open(os.devnull, "w") as devnull:
            result = subprocess.run(
                ["wine", "stars.exe", "-a", "game.def"],
                cwd=game_dir, env=env,
                stdout=devnull, stderr=devnull,
                timeout=60,
            )
    except subprocess.TimeoutExpired:
        return False, "stars.exe timed out after 60s"
    if result.returncode != 0:
        return False, f"stars.exe exited {result.returncode}"

    hst = game_dir / f"{game_name}.hst"
    if not hst.exists():
        return False, f"{game_name}.hst not created (stars.exe may have silently failed)"

    created = sum(1 for n in range(1, len(race_stems) + 1)
                  if (game_dir / f"{game_name}.m{n}").exists())
    if created < len(race_stems):
        return True, (f"partial: {created}/{len(race_stems)} players placed "
                      f"({game_dir.name})")

    return True, f"ok: {game_dir.name}"


def find_pending(base_dir: Path, prt_filter: str | None) -> list[Path]:
    """Return all game dirs without a .hst file, optionally filtered by PRT."""
    pending = []
    prts = [prt_filter.upper()] if prt_filter else PRTS
    for prt in prts:
        prt_dir = base_dir / prt
        if not prt_dir.is_dir():
            continue
        for game_dir in sorted(prt_dir.glob("game_*")):
            meta = game_dir / "_meta.json"
            if not meta.exists():
                continue
            gname = json.loads(meta.read_text())["game_name"]
            if not (game_dir / f"{gname}.hst").exists():
                pending.append(game_dir)
    return pending


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers",    type=int, default=2,
                        help="Parallel Wine processes (default: 2; try 4 if stable)")
    parser.add_argument("--display",    default=":99",
                        help="X display for Wine (default: :99)")
    parser.add_argument("--start-xvfb", action="store_true",
                        help="Start Xvfb on --display if not already running")
    parser.add_argument("--prt",        help="Only process one PRT (e.g. IT)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="List pending games without generating them")
    args = parser.parse_args()

    for tool in [JSON_TO_R1, JSON_TO_DEF]:
        if not tool.exists():
            print(f"error: tool not found: {tool}\n"
                  f"  Run `cargo build` in stars_file_parser/", file=sys.stderr)
            sys.exit(1)
    if not BASE_DIR.exists():
        print(f"error: experiment dir not found: {BASE_DIR}\n"
              f"  Run setup_fleet_experiment.py first.", file=sys.stderr)
        sys.exit(1)

    if args.start_xvfb:
        probe = subprocess.run(["xdpyinfo", "-display", args.display],
                               capture_output=True)
        if probe.returncode != 0:
            print(f"Starting Xvfb on {args.display}…")
            subprocess.Popen(
                ["Xvfb", args.display, "-screen", "0", "1024x768x24"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1)

    pending = find_pending(BASE_DIR, args.prt)
    total   = len(pending)
    print(f"Pending games: {total}")

    if args.dry_run:
        for g in pending[:20]:
            print(f"  {g.relative_to(BASE_DIR)}")
        if total > 20:
            print(f"  … and {total - 20} more")
        return

    if total == 0:
        print("Nothing to do.")
        return

    errors_log = BASE_DIR / "_errors.log"
    done = failed = partial = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(generate_game, g, args.display): g for g in pending}
        for fut in as_completed(futures):
            success, msg = fut.result()
            if not success:
                failed += 1
                line = f"FAIL {futures[fut]}: {msg}\n"
                sys.stderr.write(line)
                with open(errors_log, "a") as ef:
                    ef.write(line)
            elif msg.startswith("partial"):
                partial += 1
                done += 1
            else:
                done += 1

            completed = done + failed
            if completed % 50 == 0 or completed == total:
                elapsed = time.time() - t0
                rate    = completed / elapsed if elapsed > 0 else 0
                eta     = (total - completed) / rate if rate > 0 else 0
                print(f"  [{completed}/{total}]  done={done}  partial={partial}"
                      f"  failed={failed}  {rate:.1f}/s  ETA {eta/60:.0f}m",
                      flush=True)

    print(f"\nFinished: {done} generated ({partial} partial), {failed} failed")
    if failed:
        print(f"See {errors_log}")
    if partial:
        print(f"Partial games (homeworld placement cut on small maps) are normal.")


if __name__ == "__main__":
    main()
