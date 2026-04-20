#!/usr/bin/env python3
"""
Set up the R2.3 starting fleet oracle experiment directory structure.

Creates 3,840 game directories (384 per PRT × 10 PRTs) under
  $STARS_RESEARCH_DIR/original/race_fleet_permutation_games/

Each game directory gets:
  stars.exe     — hardlink to original/stars.exe
  _meta.json    — universe params + 16 race stems assigned to this game

Also writes manifest.json at the base, mapping every race stem to its
{dir, player} so any race can be found in O(1).

Does NOT run Stars! — use generate_fleet_games.py for that step.

Universe cycling (period 480; 8 complete cycles across 3,840 games):
  size:     i % 5                  tiny/small/medium/large/huge
  density:  i % 4                  sparse/normal/dense/packed
  position: (i // 4) % 4           close/moderate/farther/distant  (independent from density)
  clumping: (i // 16) % 2 == 1     50% of games
  bbs:      (i // 32) % 3 == 2     33% of games (accelerated BBS)

Environment variables:
  STARS_RESEARCH_DIR  Root of the stars-reborn-research repo
                      (default: ~/data/stars/stars-reborn-research)
"""

import json
import os
import shutil
import sys
from pathlib import Path

from stars_automator.config import DEFAULT_RESEARCH_DIR, DEFAULT_STARS_EXE

_RESEARCH = Path(DEFAULT_RESEARCH_DIR)
BASE_DIR = _RESEARCH / "original" / "race_fleet_permutation_games"
RACES_DIR = _RESEARCH / "original" / "race_ship_permutations"
STARS_EXE = Path(DEFAULT_STARS_EXE)

PRTS = ["HE", "SS", "WM", "CA", "IS", "SD", "PP", "IT", "AR", "JOAT"]
SIZES = ["tiny", "small", "medium", "large", "huge"]
DENSITIES = [
    "sparse",
    "normal",
    "dense",
]  # "packed" omitted: stars.exe -a silently produces no output files in headless mode with density=packed
POSITIONS = ["close", "moderate", "farther", "distant"]
PLAYERS_PER_GAME = 16
EXPECTED_PER_PRT = 6144  # 96 LRT combos × 64 tech combos


def universe_params(global_idx: int) -> dict:
    return {
        "map_size": SIZES[global_idx % 5],
        "density": DENSITIES[global_idx % 4],
        "player_positions": POSITIONS[(global_idx // 4) % 4],
        "galaxy_clumping": (global_idx // 16) % 2 == 1,
        "accelerated_bbs": (global_idx // 32) % 3 == 2,
        "seed": global_idx + 1,
    }


def chunk(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def main():
    if not RACES_DIR.exists():
        print(f"error: races dir not found: {RACES_DIR}", file=sys.stderr)
        sys.exit(1)
    if not STARS_EXE.exists():
        print(f"error: stars.exe not found: {STARS_EXE}", file=sys.stderr)
        sys.exit(1)

    race_files = sorted(RACES_DIR.glob("*.json"))
    print(f"Found {len(race_files)} race files in {RACES_DIR.name}/")

    races_by_prt: dict[str, list[Path]] = {prt: [] for prt in PRTS}
    for f in race_files:
        prt = f.stem.split("_")[0].upper()
        if prt in races_by_prt:
            races_by_prt[prt].append(f)
        else:
            print(f"warning: unknown PRT prefix in {f.name!r}", file=sys.stderr)

    for prt in PRTS:
        n = len(races_by_prt[prt])
        if n != EXPECTED_PER_PRT:
            print(f"warning: {prt} has {n} races (expected {EXPECTED_PER_PRT})", file=sys.stderr)

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    total_games = 0

    for prt_idx, prt in enumerate(PRTS):
        prt_races = races_by_prt[prt]
        games = list(chunk(prt_races, PLAYERS_PER_GAME))
        prt_dir = BASE_DIR / prt
        prt_dir.mkdir(exist_ok=True)

        print(f"  {prt}: {len(prt_races)} races → {len(games)} games", flush=True)

        for local_idx, race_group in enumerate(games):
            global_idx = prt_idx * len(games) + local_idx
            game_num = local_idx + 1
            game_name = f"{prt}{game_num:04d}"
            game_dir = prt_dir / f"game_{game_num:04d}"
            game_dir.mkdir(exist_ok=True)

            stars_link = game_dir / "stars.exe"
            if not stars_link.exists():
                try:
                    os.link(STARS_EXE, stars_link)
                except OSError:
                    shutil.copy2(STARS_EXE, stars_link)

            uparams = universe_params(global_idx)
            race_stems = [f.stem for f in race_group]

            meta = {
                "game_name": game_name,
                "dir": f"{prt}/game_{game_num:04d}",
                "universe": uparams,
                "races": race_stems,
            }
            (game_dir / "_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

            for player_num, stem in enumerate(race_stems, start=1):
                manifest[stem] = {
                    "dir": f"{prt}/game_{game_num:04d}",
                    "player": player_num,
                }

            total_games += 1

    manifest_path = BASE_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print("\nSetup complete:")
    print(f"  {total_games} game directories under {BASE_DIR}/")
    print(f"  {len(manifest)} races indexed in manifest.json")
    print("\nNext: python3 experiments/generate_fleet_games.py [--workers N]")


if __name__ == "__main__":
    main()
