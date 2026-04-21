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

## Configuration

Paths are resolved in priority order (highest to lowest):

1. **Environment variable** — always wins if set
2. **`stars_automator.local.cfg`** — your machine-specific overrides (gitignored)
3. **`stars_automator.cfg`** — committed placeholder defaults

To configure for your machine:

```bash
cp stars_automator.cfg stars_automator.local.cfg
# edit stars_automator.local.cfg with real paths
```

### Settings reference

| Config key (`[section]`)         | Env var              | Purpose                          |
|----------------------------------|----------------------|----------------------------------|
| `[paths] stars_exe`              | `STARS_EXE`          | Path to `stars.exe`              |
| `[paths] stars_parser_dir`       | `STARS_PARSER_DIR`   | Directory of parser binaries     |
| `[paths] stars_research_dir`     | `STARS_RESEARCH_DIR` | Research repo root (experiments) |
| `[wine] wineprefix`              | `WINEPREFIX`         | Wine prefix (must be 32-bit)     |
| `[wine] display`                 | `DISPLAY`            | X display for Wine               |

---

## Package modules

| Module                      | Description                                         |
|-----------------------------|-----------------------------------------------------|
| `stars_automator.game`      | Create a game from a JSON config (`stars.exe -a`)   |
| `stars_automator.turns`     | Generate turns (`stars.exe -gN`)                    |
| `stars_automator.dump`      | Dump planet/fleet/map data (`stars.exe -d`)         |
| `stars_automator.ini`       | Ensure `Stars.ini` has required settings            |
| `stars_automator.wine`      | Shared helpers: `ensure_xvfb`, `make_wine_env`, `wine_path` |
| `stars_automator.x1`        | Write Stars! `.x1` player order files (WaypointAdd, ResearchChange) |
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

## Known Stars! headless behaviour

These quirks were confirmed through oracle experiments and apply to all headless
invocations via this library:

- **`density=packed` fails silently** — `stars.exe -a` exits 0 but produces no
  output files when the universe density is set to Packed.  Use `dense` for
  maximum planet coverage in single-game experiments.
- **Relative paths required** — `wine stars.exe` must be invoked from the game
  directory with relative paths (`wine stars.exe -a game.def`).  Absolute Linux
  paths cause Wine to exit 0 with no output.  All tools in this library handle
  this automatically via `cwd=workdir`.
- **stdout/stderr must be suppressed** — piping Wine output with
  `capture_output=True` causes silent failure.  Both streams are redirected to
  `/dev/null` in all tools here.
- **Corrupt x1 = blocking Win32 dialog, not a crash** — when Stars! rejects a
  `.x1` file (wrong cipher, wrong game fingerprint, etc.) it shows a
  `MessageBoxA` dialog and waits indefinitely for a click.  `subprocess.run()`
  with a short timeout will raise `TimeoutExpired`; the process does NOT exit
  with a non-zero code.  The dialog text is "Player log file `<name>.x1` appears
  to be corrupt, unable to load file."  Diagnose by checking the x1 type-8
  bytes 0–11 (must match the game's `.m1`/`.hst`) and byte[14] (must be
  `0x01` for x files, not `0x03` from a copied m1 header).

---

## Experiments

The `experiments/` directory contains research-specific scripts that drive the
tools above to build oracle corpora for Stars Reborn reverse engineering.

| Script                           | Purpose                                         |
|----------------------------------|-------------------------------------------------|
| `oracle_starting_state.py`       | R2.1/R2.2/R4.1: pop, tech, AI difficulty oracles |
| `run_bbs_phase1.py`              | R2.6 Phase 1: BBS population formula            |
| `run_bbs_phase2.py`              | R2.6 Phase 2: BBS mineral survey (see below)    |
| `generate_ship_experiment_races.py` | Generate 61,440 race files for R2.3 corpus   |
| `setup_fleet_experiment.py`      | Set up R2.3 game directory structure            |
| `generate_fleet_games.py`        | Run Stars! for all R2.3 games (resumable)       |
| `bulk_decode_fleets.py`          | Decode R2.3 fleet corpus to JSONL               |
| `decode_ai_starting_fleets.py`   | Decode AI starting fleets from initial_maps corpus |
| `map_generator.py`               | Legacy: generate maps via xdotool UI            |
| `oracle_configs/r2_6/`           | Game config JSONs for R2.6 BBS experiments      |

All experiment scripts use `STARS_RESEARCH_DIR` to locate the corpus data.

### R2.6 Phase 2 — BBS mineral survey

Creates two single-player games (BBS and baseline, same seed 12345), scouts the
entire universe with 6 starting fleets, then compares mineral concentrations
across all 160 planets.

```bash
cd /home/brandon/data/stars/stars_automator
python3 experiments/run_bbs_phase2.py [--force] [--max-turns 120] [--display :99]
```

Options:
- `--force` — delete and recreate `/tmp/bbs_mineral_survey/` and `/tmp/baseline_mineral_survey/`
- `--max-turns N` — turn-loop limit (default 60; use 120+ to reach all 160 planets)
- `--display` — Xvfb display (default `:99`)

Output: `experiments/oracle_configs/r2_6/phase2_results.json`

**Phase 2 result (2026-04-19):** BBS play does NOT affect mineral concentrations.
138/153 common planets were identical between BBS and baseline. The 15 differing
planets split into two categories:
1. **Homeworld artifact** (4–6 planets, large diffs): BBS and baseline assign the
   homeworld to *different* planets.  The homeworld gets boosted concentrations, so
   whichever planet becomes a homeworld in one game shows much higher values.
   These planets must be excluded from BBS/baseline comparisons.
2. **Remote-scan noise** (~11 planets, ±5–8 pts on one mineral): Stars! adds
   ~±15% jitter to concentrations reported by remote (non-owned) planetary scans.
   Normal variance; not a BBS effect.

---

## x1 order file generation

`stars_automator/x1.py` writes Stars! `.x1` player order files.  The `.x1`
format uses the same L'Ecuyer combined LCG cipher as `.m1`/`.hst` files, so
getting the cipher seeding exactly right is critical.

### Quick example

```python
from pathlib import Path
from stars_automator.x1 import ResearchChange, WaypointAdd, write_x1

write_x1(
    "Game.x1",
    waypoints=[WaypointAdd(fleet_num=0, wp_nr=1, dest_x=320, dest_y=480, target_idx=14)],
    game_file="Game.m1",           # any file from the same game
    research=[ResearchChange(current_field=4, next_field=4, research_percent=25)],
)
```

`write_x1` accepts:
- `waypoints` — list of `WaypointAdd` orders (each emits a type-4 + type-5 pair)
- `game_file` — **any** Stars! file from the same game (`.m1`, `.hst`, etc.)
- `research` — optional list of `ResearchChange` orders (type-34)

### Key format facts (hard-won)

**Type-8 header — game fingerprint (bytes 0–11) and file-type discriminator (byte 14)**

The 16-byte Type-8 payload is split:
- Bytes 0–11: game-specific fingerprint, identical across every file in the same
  game (`.hst`, `.m1`, `.x1`, etc.).  Stars! validates these on x1 import and
  **silently discards the entire file** if they don't match.
  → Always read them from an existing game file with `read_game_type8_prefix()`.
- Bytes 12–15: file-type-specific, NOT a copy of the `.m1` bytes 12–15.
  Byte 14 is a **file-type discriminator**: `0x01`=x order files, `0x02`=hst,
  `0x03`=m player files, `0x04`=archived h files.  A `.x1` built by copying
  all 16 bytes from `.m1` will have `0x03` at byte 14, which Stars! detects
  as the wrong file type and rejects with a corrupt-file dialog.
  Bytes 12–13 (`seed_word`) determine the LCG seeds via `derive_seeds()`;
  bytes 14–15 also contribute to `pre_advance`.  The correct fixed constant
  for turn-1 single-player x files is `_TYPE8_SEED_BYTES = c0dd0100`.

**Cipher seeding**

Seeds s1 and s2 are *not* raw bytes from the header.  They are looked up in a
64-prime `SEED_TABLE` using indices derived from `seed_word >> 5`.  `pre_advance`
is also derived from several header fields, not just one byte.  See `cipher.rs` in
`stars_file_parser` for the authoritative algorithm.

**Type-9 `following_bytes` field**

The 2-byte `LengthOfFollowingBlocks` in the Type-9 payload must equal the total
byte count of all records *after* Type-9, **excluding the Type-0 end marker**.
- Each WaypointAdd pair (type-4 + type-5): 2 × (2 header + 12 payload) = **28 bytes**
- Each ResearchChange (type-34): 2 header + 2 payload = **4 bytes**

**Type-4 + type-5 pairing**

Stars! always writes WaypointAdd as a type-4/type-5 pair with identical payloads.
Sending only type-4 (without the paired type-5) causes the fleet to **silently
ignore the order**.

**Machine hash (Type-9 bytes 2–16)**

The 15-byte hash in the Type-9 payload (`_TYPE9_HASH`) is constant per Stars!
installation.  It is **not** game-specific and does not need to be extracted from
the game file.  The value in `x1.py` was confirmed from multiple reference x1
files from this installation.

### ResearchChange fields

Field index → tech field:
0=Energy, 1=Weapons, 2=Propulsion, 3=Construction, 4=Electronics, 5=Biology,
6=SameField (continue current)

`research_percent` is the percentage of gross resources allocated to research
(Stars! slider values: 0, 15, 25, 35, 45, 55, 65, 75, 100).  Set `next_field=6`
to stay on the same field indefinitely, or `next_field=4` when directing
Electronics indefinitely.

### ManualLoadUnload — immediate cargo transfer

```python
from stars_automator.x1 import ManualLoadUnload, LOAD_OPCODE, UNLOAD_OPCODE, write_x1

write_x1(
    "Game.x1",
    waypoints=[],
    game_file="Game.m1",
    load_unloads=[
        ManualLoadUnload(fleet_num=2, planet_id=8, opcode=LOAD_OPCODE,   cargo={0: 50}),
        ManualLoadUnload(fleet_num=3, planet_id=8, opcode=UNLOAD_OPCODE, cargo={0: 25}),
    ],
)
```

Payload format (type-1 ManualSmallLoadUnloadTaskBlock, confirmed 2026-04-20/21):

| Bytes | Field         | Notes                                            |
|-------|---------------|--------------------------------------------------|
| 0–1   | fleet_num     | LE uint16, 9-bit (matches type-16 fleet record)  |
| 2–3   | planet_id     | LE uint16 (matches orbit-planet field in type-16)|
| 4     | opcode        | `LOAD_OPCODE=0x12`, `UNLOAD_OPCODE=0x02`         |
| 5     | resource_mask | bit 0=ironium, 1=boranium, 2=germanium, 3=col    |
| 6+    | amounts       | 1 byte per set bit, ascending resource order     |

Opcodes 0x12 (load) and 0x02 (unload) differ by bit 4.  `cargo` is a dict of
`{bit_position: amount_kT}` where amounts must fit in one byte (0–255).

**Oracle design note:** Stars! maintains a type-12 m1 record that registers
which fleet is eligible for manual cargo operations at each planet.  This
registration is set at game creation for fleets with initial cargo, and is not
automatically updated when cargo is loaded via `ManualLoadUnload`.  Oracles that
load cargo in turn 1 then test unload in turn 2 will find the unload silently
ignored; use a game configuration where the target fleet starts with cargo.
