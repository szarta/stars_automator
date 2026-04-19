#!/usr/bin/env python3
"""
decode_ai_starting_fleets.py — Extract AI starting fleet design names from the
initial_maps corpus.

Iterates original/initial_maps/<difficulty>_<size>/<run>/ (all 260 games),
runs m1_to_json on each AI player file (players 2+; player 1 is the human),
and writes one JSONL record per AI player.

Output record:
  {
    "difficulty":  "easy",
    "map_size":    "medium",
    "run":         1,
    "player":      2,
    "prt":         "CA",
    "lrts":        ["TT", "CE", "OBRM", "NAS", "LSP", "BET"],
    "designs":     [
      {"name": "Smaugarian Peeping Tom", "hull_name": "Scout",
       "hull_id": 4, "is_starbase": false, "count": 1,
       "components": ["Daddy Long Legs 7", "Bat Scanner"]},
      ...
    ]
  }

Usage:
  python3 decode_ai_starting_fleets.py [--workers N] [--out FILE] [--dry-run]
  python3 decode_ai_starting_fleets.py --report        # print summary only

Options:
  --workers N    Parallel processes (default: 4)
  --out FILE     JSONL output path
  --dry-run      Count work items without processing
  --report       Read existing JSONL and print summary table (no decoding)

Environment variables:
  STARS_RESEARCH_DIR  Root of the stars-reborn-research repo
                      (default: ~/data/stars/stars-reborn-research)
  STARS_PARSER_DIR    Directory of stars_file_parser binaries
                      (default: ~/data/stars/stars_file_parser/target/debug)
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from stars_automator.config import DEFAULT_PARSER_DIR, DEFAULT_RESEARCH_DIR

RESEARCH = Path(DEFAULT_RESEARCH_DIR)
BASE_DIR = RESEARCH / "original" / "initial_maps"
M1_TO_JSON = Path(DEFAULT_PARSER_DIR) / "m1_to_json"

DIFFICULTIES = ["easy", "standard", "harder", "expert"]
SIZES = ["tiny", "small", "medium", "large", "huge"]
GAME_NAME = "Game"


def decode_game(game_dir: Path, difficulty: str, map_size: str, run: int) -> list[dict]:
    """
    Decode all AI player files (m2, m3, …) in one game directory.
    Player 1 (m1) is the human player — skipped.
    Returns list of per-player records.
    """
    records = []
    player_num = 2
    while True:
        mfile = game_dir / f"{GAME_NAME}.m{player_num}"
        if not mfile.exists():
            break

        result = subprocess.run(
            [str(M1_TO_JSON), str(mfile)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"m1_to_json failed on {mfile}: {result.stderr.decode().strip()}")

        data = json.loads(result.stdout)
        race = data.get("player", {}).get("race", {})
        prt = race.get("prt", "?")
        lrts = race.get("lrts", [])

        designs = []
        for d in data.get("designs", []):
            components = []
            for s in d.get("slots", []):
                cnt = s.get("count", 1)
                name = s.get("component", "?")
                components.append(f"{cnt}x {name}" if cnt > 1 else name)

            designs.append(
                {
                    "name": d["name"],
                    "hull_name": d["hull_name"],
                    "hull_id": d["hull_id"],
                    "is_starbase": d.get("is_starbase", False),
                    "count": d.get("total_remaining", 0),
                    "components": components,
                }
            )

        records.append(
            {
                "difficulty": difficulty,
                "map_size": map_size,
                "run": run,
                "player": player_num,
                "prt": prt,
                "lrts": lrts,
                "designs": designs,
            }
        )
        player_num += 1

    return records


def find_game_dirs() -> list[tuple[Path, str, str, int]]:
    """Return all game dirs as (path, difficulty, map_size, run)."""
    items = []
    for diff in DIFFICULTIES:
        for size in SIZES:
            parent = BASE_DIR / f"{diff}_{size}"
            if not parent.is_dir():
                continue
            for run_dir in sorted(parent.iterdir(), key=lambda p: int(p.name)):
                if not run_dir.is_dir():
                    continue
                hst = run_dir / f"{GAME_NAME}.hst"
                if not hst.exists():
                    continue
                try:
                    run = int(run_dir.name)
                except ValueError:
                    continue
                items.append((run_dir, diff, size, run))
    return items


def _worker(args: tuple) -> tuple[Path, list[dict] | None, str]:
    game_dir, difficulty, map_size, run = args
    try:
        records = decode_game(game_dir, difficulty, map_size, run)
        return game_dir, records, ""
    except Exception as exc:
        return game_dir, None, str(exc)


def summarise(jsonl_path: Path) -> None:
    """Read JSONL and print a structured summary of AI design names per PRT."""
    records = []
    with open(jsonl_path) as f:
        for line in f:
            records.append(json.loads(line))

    prt_designs: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    name_by_diff: dict[tuple, set] = defaultdict(set)
    name_hull: dict[tuple, str] = {}

    for rec in records:
        prt = rec["prt"]
        diff = rec["difficulty"]
        for d in rec["designs"]:
            key = (prt, d["name"])
            prt_designs[prt][d["name"]].add(d["hull_name"])
            name_by_diff[key].add(diff)
            name_hull[key] = d["hull_name"]

    inconsistencies = []
    for prt, name_hulls in prt_designs.items():
        for name, hulls in name_hulls.items():
            if len(hulls) > 1:
                inconsistencies.append(f"  {prt} '{name}' → {hulls}")

    print(f"Records: {len(records)} AI players")
    print(f"PRTs observed: {sorted(prt_designs)}")
    print()

    if inconsistencies:
        print("WARNING: name/hull inconsistencies:")
        for x in inconsistencies:
            print(x)
        print()

    varies = [
        (prt, name)
        for (prt, name), diffs in name_by_diff.items()
        if len(diffs) < 4 and len(diffs) > 0
    ]
    if varies:
        print("Names NOT present in all 4 difficulties:")
        for prt, name in sorted(varies):
            diffs = name_by_diff[(prt, name)]
            hull = name_hull[(prt, name)]
            print(f"  {prt} '{name}' ({hull}): only in {sorted(diffs)}")
        print()

    print("AI design names per PRT")
    print("=" * 70)
    for prt in sorted(prt_designs):
        print(f"\n{prt}")
        ships = [
            (n, h) for n, hs in prt_designs[prt].items() for h in hs if not _is_starbase_hull(h)
        ]
        starbases = [
            (n, h) for n, hs in prt_designs[prt].items() for h in hs if _is_starbase_hull(h)
        ]
        print("  Ships:")
        for name, hull in sorted(ships, key=lambda x: x[1]):
            diffs = sorted(name_by_diff[(prt, name)])
            diff_note = "" if len(diffs) == 4 else f"  [diffs: {diffs}]"
            print(f"    {name:<35s}  {hull}{diff_note}")
        print("  Starbases:")
        for name, hull in sorted(starbases, key=lambda x: x[1]):
            print(f"    {name:<35s}  {hull}")


STARBASE_HULLS = {
    "Space Station",
    "Ultra Station",
    "Death Star",
    "Orbital Fort",
    "Space Dock",
    "Star Base",
}


def _is_starbase_hull(hull_name: str) -> bool:
    return hull_name in STARBASE_HULLS


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel processes (default: 4)")
    parser.add_argument("--out", default=None, help="JSONL output path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count work items without processing"
    )
    parser.add_argument("--report", action="store_true", help="Print summary from existing JSONL")
    args = parser.parse_args()

    out_path = (
        Path(args.out)
        if args.out
        else (Path(DEFAULT_RESEARCH_DIR) / "docs" / "findings" / "ai_fleet_corpus.jsonl")
    )

    if args.report:
        if not out_path.exists():
            print(f"error: {out_path} not found — run without --report first", file=sys.stderr)
            sys.exit(1)
        summarise(out_path)
        return

    if not M1_TO_JSON.exists():
        print(
            f"error: m1_to_json not found at {M1_TO_JSON}\n"
            f"  Run `cargo build` in stars_file_parser/",
            file=sys.stderr,
        )
        sys.exit(1)

    game_items = find_game_dirs()
    print(f"Games to process: {len(game_items)}")

    if args.dry_run:
        for item in game_items[:10]:
            gd, diff, size, run = item
            print(f"  {diff}_{size}/{run}/")
        if len(game_items) > 10:
            print(f"  … and {len(game_items) - 10} more")
        return

    if not game_items:
        print("Nothing to process.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = failed = players = 0

    with open(out_path, "w") as out_f, ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_worker, item): item for item in game_items}

        for fut in as_completed(futures):
            gd, records, err = fut.result()
            done += 1

            if records is None:
                failed += 1
                print(f"  FAIL {gd}: {err}", file=sys.stderr)
            else:
                for rec in records:
                    out_f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                players += len(records)

            if done % 50 == 0 or done == len(game_items):
                pct = 100 * done / len(game_items)
                print(
                    f"  [{done}/{len(game_items)}] {pct:.0f}%  players={players}  failed={failed}",
                    flush=True,
                )

    print(f"\nDone. {players} AI player records written to {out_path}")
    if failed:
        print(f"  {failed} games failed — check stderr for details")

    print("\n--- Summary ---")
    summarise(out_path)


if __name__ == "__main__":
    main()
