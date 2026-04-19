# stars_automator

Automation tools for driving **Stars!** (the 1995/1996 4X strategy game) under
Wine to gather research data for [Stars Reborn](https://github.com/szarta/stars-reborn-engine).

Capabilities:
- Create Stars! games headlessly from a JSON config (`stars.exe -a`)
- Generate turns (`stars.exe -gN`)
- Dump planet/fleet/universe data (`stars.exe -d`)
- Manage `Stars.ini` settings required for rich dump output
- Bulk-generate race files and game corpora for oracle experiments

---

## System requirements

| Dependency          | Purpose                                      |
|---------------------|----------------------------------------------|
| `wine` (32-bit)     | Run `stars.exe` on Linux                     |
| `Xvfb`              | Headless X display for Wine                  |
| `xdpyinfo`          | Detect whether Xvfb is already running       |
| `xdotool`           | UI automation (legacy `ui.py` only)          |
| `winepath`          | Convert Linux paths to Wine Windows paths    |
| `stars_file_parser` | Rust binaries: `json_to_r1`, `json_to_def`,  |
|                     | `m1_to_json` — see szarta/stars_file_parser  |

Python 3.11+ required. No third-party Python dependencies.

### Wine setup

```bash
WINEPREFIX=~/.wine32 WINEARCH=win32 winecfg   # first-time setup
```

Run `stars.exe` once manually so Wine creates `Stars.ini`, then run:

```bash
stars-create-ini    # or: python3 -m stars_automator.ini
```

---

## Installation

```bash
pip install -e .
```

This installs four CLI entry points: `stars-create-game`, `stars-generate-turn`,
`stars-dump-game`, `stars-create-ini`.

Or run without installing using `python3 -m stars_automator.<module>`.

---

## Environment variables

All tools respect these env vars (falling back to hardcoded defaults if unset):

| Variable             | Default                                              | Purpose                          |
|----------------------|------------------------------------------------------|----------------------------------|
| `STARS_EXE`          | `~/data/stars/stars-reborn-research/original/stars.exe` | Path to `stars.exe`           |
| `STARS_PARSER_DIR`   | `~/data/stars/stars_file_parser/target/debug`        | Directory of parser binaries     |
| `WINEPREFIX`         | `~/.wine32`                                          | Wine prefix (standard Wine var)  |
| `DISPLAY`            | `:99`                                                | X display for Wine               |
| `STARS_RESEARCH_DIR` | `~/data/stars/stars-reborn-research`                 | Research repo root (experiments) |

---

## Package modules

| Module                      | Description                                         |
|-----------------------------|-----------------------------------------------------|
| `stars_automator.game`      | Create a game from a JSON config (`stars.exe -a`)   |
| `stars_automator.turns`     | Generate turns (`stars.exe -gN`)                    |
| `stars_automator.dump`      | Dump planet/fleet/map data (`stars.exe -d`)         |
| `stars_automator.ini`       | Ensure `Stars.ini` has required settings            |
| `stars_automator.wine`      | Shared helpers: `ensure_xvfb`, `make_wine_env`, `wine_path` |
| `stars_automator.ui`        | Legacy xdotool UI automation (pre-headless era)     |

---

## Creating a game

```bash
stars-create-game my_game.json --start-xvfb
```

Config file schema (`my_game.json`):

```json
{
  "experiment_name": "my_run",
  "universe": {
    "map_size": "small",
    "density": "normal",
    "player_positions": "farther",
    "seed": 12345
  },
  "human_races": [
    "path/to/my_race.json"
  ],
  "ai_players": [
    {"difficulty": 2, "param": 1}
  ]
}
```

Race entries can be a path to a `.json` race file, a path to a pre-built `.r1`
binary, or an inline race JSON object.  See `stars_automator/game.py` for the
full config schema.

Outputs land in `/tmp/<experiment_name>/`.

---

## Generating turns

```bash
stars-generate-turn /tmp/my_run Game --turns 3
```

---

## Dumping game data

```bash
stars-dump-game /tmp/my_run Game.m1
```

---

## Experiments

The `experiments/` directory contains research-specific scripts that drive the
tools above to build oracle corpora for Stars Reborn reverse engineering.

| Script                           | Purpose                                         |
|----------------------------------|-------------------------------------------------|
| `oracle_starting_state.py`       | R2.1/R2.2/R4.1: pop, tech, AI difficulty oracles |
| `run_bbs_phase1.py`              | R2.6 Phase 1: BBS population formula            |
| `generate_ship_experiment_races.py` | Generate 61,440 race files for R2.3 corpus   |
| `setup_fleet_experiment.py`      | Set up R2.3 game directory structure            |
| `generate_fleet_games.py`        | Run Stars! for all R2.3 games (resumable)       |
| `bulk_decode_fleets.py`          | Decode R2.3 fleet corpus to JSONL               |
| `decode_ai_starting_fleets.py`   | Decode AI starting fleets from initial_maps corpus |
| `map_generator.py`               | Legacy: generate maps via xdotool UI            |
| `oracle_configs/r2_6/`           | Game config JSONs for R2.6 BBS experiments      |

All experiment scripts use `STARS_RESEARCH_DIR` to locate the corpus data.
