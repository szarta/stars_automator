#!/usr/bin/env python3
"""
bulk_decode_fleets.py — Bulk-decode starting fleet compositions from the R2.3 corpus.

Reads every generated game in race_fleet_permutation_games/{PRT}/game_NNNN/,
runs m1_to_json on each player file, and writes one JSONL record per player.

No wine required — the DesignBlock is now decoded by m1_to_json (R0.4 resolved
2026-04-17), so design names are available directly from the binary .mN file.

Output (JSONL, one record per player):
  {
    "race_stem":        "it_arm.ce.isb_bi",
    "prt":              "IT",
    "lrts":             ["ARM", "CE", "ISB"],
    "expensive_start4": ["bi"],
    "accelerated_bbs":  false,
    "tech": {"en": 0, "we": 0, "pr": 6, "co": 5, "el": 0, "bi": 3},
    "game_dir":         "IT/game_0001",
    "player":           1,
    "designs": [
      {
        "hull_id":    4,
        "hull_name":  "Scout",
        "name":       "Smaugarian Peeping Tom",
        "count":      2,
        "components": ["Daddy Long Legs 7", "Bat Scanner", "Fuel Tank"]
      },
      ...
    ]
  }

expensive_start4: tech fields that are both marked "Costs 75% extra" AND have the
  "Costs 75% extra fields start at Tech 4" checkbox checked in the race designer.
  This is a standalone race design option on the Technology page — NOT the BET LRT.
  Fields: en=Energy, we=Weapons, pr=Propulsion, co=Construction, el=Electronics, bi=Biology.

tech: actual starting tech levels read from the player block of the .mN file.
  These are the authoritative values the game engine uses for component selection.
  They already incorporate PRT minimums, IFE/CE +1 propulsion bonuses, and
  expensive_start4 boosts — no further derivation needed.

Skips games without a .hst (not yet generated).
Starbases are excluded from designs.
Component counts > 1 are prefixed, e.g. "2x Crobmnium".

Usage:
  python3 bulk_decode_fleets.py [--prt PRT] [--workers N] [--out FILE]

Options:
  --prt PRT      Process only this PRT (e.g. IT); default: all 10
  --workers N    Parallel processes (default: 4)
  --out FILE     Output path (default: $STARS_RESEARCH_DIR/docs/findings/fleet_corpus.jsonl)
  --dry-run      Count work items without processing

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
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from stars_automator.config import DEFAULT_PARSER_DIR, DEFAULT_RESEARCH_DIR

BASE_DIR = Path(DEFAULT_RESEARCH_DIR) / "original" / "race_fleet_permutation_games"
M1_TO_JSON = Path(DEFAULT_PARSER_DIR) / "m1_to_json"

PRTS = ["HE", "SS", "WM", "CA", "IS", "SD", "PP", "IT", "AR", "JOAT"]


def parse_race_stem(stem: str) -> tuple[str, list[str], list[str]]:
    """
    Parse '{prt}_{lrts}_{expensive_start4_fields}' stem.
    Returns (prt_upper, lrts_upper_list, expensive_start4_list).
    The third section is which tech fields are expensive AND have start-at-4 checked
    — this is NOT the BET LRT.
    """
    parts = stem.split("_", 2)
    prt = parts[0].upper()
    lrts = [x.upper() for x in parts[1].split(".") if x] if len(parts) >= 2 else []
    expensive_start4 = [x for x in parts[2].split(".") if x] if len(parts) >= 3 else []
    return prt, lrts, expensive_start4


def decode_game(game_dir: Path) -> list[dict]:
    """
    Decode all player files in one game directory.
    Returns a list of per-player records (skips missing .mN files silently).
    Raises RuntimeError on m1_to_json failures.
    """
    meta = json.loads((game_dir / "_meta.json").read_text())
    game_name = meta["game_name"]
    races = meta["races"]
    accel_bbs = meta["universe"]["accelerated_bbs"]
    rel_dir = str(game_dir.relative_to(BASE_DIR))

    records = []
    for idx, race_stem in enumerate(races):
        player_num = idx + 1
        mfile = game_dir / f"{game_name}.m{player_num}"
        if not mfile.exists():
            continue  # homeworld placement cut on this player (small/tiny maps)

        result = subprocess.run(
            [str(M1_TO_JSON), str(mfile)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"m1_to_json failed on {mfile}: {result.stderr.decode().strip()}")

        data = json.loads(result.stdout)
        prt, lrts, expensive_start4 = parse_race_stem(race_stem)

        p = data.get("player", {})
        tech = {
            "en": p.get("tech_energy", 0),
            "we": p.get("tech_weapons", 0),
            "pr": p.get("tech_propulsion", 0),
            "co": p.get("tech_construction", 0),
            "el": p.get("tech_electronics", 0),
            "bi": p.get("tech_biology", 0),
        }

        designs = []
        starbases = []
        for d in data.get("designs", []):
            components = []
            for s in d.get("slots", []):
                cnt = s.get("count", 1)
                name = s.get("component", "?")
                components.append(f"{cnt}x {name}" if cnt > 1 else name)

            entry = {
                "hull_id": d["hull_id"],
                "hull_name": d["hull_name"],
                "name": d["name"],
                "count": d.get("total_remaining", 0),
                "components": components,
            }
            if d.get("is_starbase"):
                starbases.append(entry)
            else:
                designs.append(entry)

        records.append(
            {
                "race_stem": race_stem,
                "prt": prt,
                "lrts": lrts,
                "expensive_start4": expensive_start4,
                "accelerated_bbs": accel_bbs,
                "tech": tech,
                "game_dir": rel_dir,
                "player": player_num,
                "designs": designs,
                "starbases": starbases,
            }
        )

    return records


def find_game_dirs(prt_filter: str | None) -> list[Path]:
    """Return all game dirs that have a .hst file, sorted."""
    prts = [prt_filter.upper()] if prt_filter else PRTS
    dirs = []
    for prt in prts:
        prt_dir = BASE_DIR / prt
        if not prt_dir.is_dir():
            continue
        for gd in sorted(prt_dir.glob("game_*")):
            meta = gd / "_meta.json"
            if not meta.exists():
                continue
            gname = json.loads(meta.read_text())["game_name"]
            if (gd / f"{gname}.hst").exists():
                dirs.append(gd)
    return dirs


def _worker(game_dir: Path) -> tuple[Path, list[dict] | None, str]:
    """Top-level worker (must be importable for multiprocessing)."""
    try:
        records = decode_game(game_dir)
        return game_dir, records, ""
    except Exception as exc:
        return game_dir, None, str(exc)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--prt", help="Process only this PRT (e.g. IT)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel processes (default: 4)")
    parser.add_argument("--out", default=None, help="Output JSONL path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count work items without processing"
    )
    args = parser.parse_args()

    if not M1_TO_JSON.exists():
        print(
            f"error: m1_to_json not found at {M1_TO_JSON}\n"
            f"  Run `cargo build` in stars_file_parser/",
            file=sys.stderr,
        )
        sys.exit(1)

    out_path = (
        Path(args.out)
        if args.out
        else (Path(DEFAULT_RESEARCH_DIR) / "docs" / "findings" / "fleet_corpus.jsonl")
    )

    game_dirs = find_game_dirs(args.prt)
    print(f"Games to process: {len(game_dirs)}")

    if args.dry_run:
        for gd in game_dirs[:10]:
            print(f"  {gd.relative_to(BASE_DIR)}")
        if len(game_dirs) > 10:
            print(f"  … and {len(game_dirs) - 10} more")
        return

    if not game_dirs:
        print("Nothing to process.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = failed = players = 0

    with open(out_path, "w") as out_f, ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_worker, gd): gd for gd in game_dirs}

        for fut in as_completed(futures):
            gd, records, err = fut.result()
            done += 1

            if records is None:
                failed += 1
                print(f"  FAIL {gd.relative_to(BASE_DIR)}: {err}", file=sys.stderr)
            else:
                for rec in records:
                    out_f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                players += len(records)

            if done % 100 == 0 or done == len(game_dirs):
                pct = 100 * done / len(game_dirs)
                print(
                    f"  [{done}/{len(game_dirs)}] {pct:.0f}%  players={players}  failed={failed}",
                    flush=True,
                )

    print(f"\nDone. {players} player records written to {out_path}")
    if failed:
        print(f"  {failed} games failed — check stderr for details")


if __name__ == "__main__":
    main()
