#!/usr/bin/env python3
"""
R0.7 Oracle: ManualSmallLoadUnloadTask unload opcode — RESULT: 0x02

UNLOAD_OPCODE = 0x02, confirmed 2026-04-21.
LOAD_OPCODE   = 0x12 (confirmed by this oracle).
They differ by bit 4 (0x10).

Confirmation method: research archive
  stars-reborn-research/original/r0_7_unload_oracle/Game.x1 contains a real
  Stars! client-generated x1 with a type-1 record using opcode=0x02 for a
  fleet that had 5kT ironium in Game.m1.  That fleet is absent from Game.m2
  (0kT + no waypoints → Stars! omits it), confirming the unload executed.

Why the direct oracle sweep below did NOT confirm it:
  The 256-opcode sweep ran cleanly (no timeouts, all 256 opcodes completed),
  but fleet ironium never changed.  Root cause: Stars! maintains a type-12
  m1 record that registers which fleet is eligible for manual cargo operations
  at each planet.  This registration is set at game creation for fleets with
  initial cargo; it is NOT updated when cargo is loaded via ManualLoadUnload.
  Fleet 2 (loaded in turn 1 to 5kT) was not registered in type-12 for
  planet 8, so all unload orders targeting it were silently ignored.

  To design a working direct oracle: configure the game so the target fleet
  starts with minerals (initial cargo), then test unload in turn 1.

Run from stars_automator repo root:
    python3 experiments/r0_7_unload_oracle.py
"""

import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from stars_automator.wine import ensure_xvfb, make_wine_env
from stars_automator.x1 import LOAD_OPCODE, ManualLoadUnload, build_x1

RESEARCH = Path("/home/brandon/data/stars/stars-reborn-research")
ORACLE_CONFIG = RESEARCH / "original" / "oracle_configs" / "r0_7_unload_oracle.json"
ORACLE_DIR = Path("/tmp/r0_7_unload_v2")
GAME_NAME = "Oracle"
PARSE_SCRIPT = RESEARCH / "reverse-engineering" / "scripts" / "parse_m.py"
STARS_AUTOMATOR = Path(__file__).parent.parent

CARGO_IRONIUM_BIT = 0

# Full sweep: every possible byte value.  1-player game completes each host run
# in ~1 second, so 256 candidates ≈ 5 minutes total.
CANDIDATES = list(range(0x100))


def create_game(display: str = ":99") -> None:
    """Create the oracle game via stars_automator.game if not already done."""
    if (ORACLE_DIR / f"{GAME_NAME}.m1").exists():
        print("[setup] Game already exists in /tmp/r0_7_unload_v2")
        return
    print("[setup] Creating fresh 1-player oracle game...")
    result = subprocess.run(
        [sys.executable, "-m", "stars_automator.game", str(ORACLE_CONFIG), "--display", display],
        cwd=STARS_AUTOMATOR,
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(result.stdout.decode())
        print(result.stderr.decode())
        sys.exit(1)
    print(result.stdout.decode().strip())


def run_host(game_dir: Path, display: str = ":99") -> None:
    env = make_wine_env(display=display)
    result = subprocess.run(
        ["wine", "stars.exe", "-g1", f"{GAME_NAME}.hst"],
        cwd=game_dir,
        env=env,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  [WARN] stars.exe exited {result.returncode}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}")


def parse_fleet_cargo(m1_path: Path) -> dict[int, int]:
    """Return {fleet_id: ironium_kt} for all fleets in m1."""
    sys.path.insert(0, str(PARSE_SCRIPT.parent))
    import io

    from parse_m import parse_file

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        records = parse_file(m1_path)
    finally:
        sys.stdout = old_stdout

    fleet_iron = {}
    for rec in records:
        if rec["type"] != 16:
            continue
        d = rec["payload"]
        fleet_id = (d[0] | (d[1] << 8)) & 0x1FF
        flags = d[5]
        count_width = 1 if (flags & 0x08) else 2
        bitmap = struct.unpack_from("<H", d, 12)[0]
        num_designs = bin(bitmap).count("1")
        pos = 14 + num_designs * count_width
        if pos + 2 > len(d):
            fleet_iron[fleet_id] = 0
            continue
        cargo_bmp = struct.unpack_from("<H", d, pos)[0]
        pos += 2
        iron_code = cargo_bmp & 0x3
        iron_kt = 0
        if iron_code == 1:
            iron_kt = d[pos]
        elif iron_code == 2:
            iron_kt = struct.unpack_from("<H", d, pos)[0]
        elif iron_code == 3:
            iron_kt = struct.unpack_from("<I", d, pos)[0]
        fleet_iron[fleet_id] = iron_kt
    return fleet_iron


def get_fleet_planets(m1_path: Path) -> dict[int, int]:
    """Return {fleet_id: planet_id} for all fleets orbiting a planet."""
    sys.path.insert(0, str(PARSE_SCRIPT.parent))
    import io

    from parse_m import parse_file

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        records = parse_file(m1_path)
    finally:
        sys.stdout = old_stdout

    fleet_planet = {}
    for rec in records:
        if rec["type"] != 16:
            continue
        d = rec["payload"]
        fleet_id = (d[0] | (d[1] << 8)) & 0x1FF
        planet_id = struct.unpack_from("<H", d, 6)[0]
        fleet_planet[fleet_id] = planet_id
    return fleet_planet


def write_load_x1(game_dir: Path, fleet_planet: dict[int, int]) -> None:
    """Submit load orders for all fleets: each loads 5kT ironium from its planet."""
    orders = [
        ManualLoadUnload(
            fleet_num=fid,
            planet_id=pid,
            opcode=LOAD_OPCODE,
            cargo={CARGO_IRONIUM_BIT: 5},
        )
        for fid, pid in fleet_planet.items()
    ]
    data = build_x1([], game_dir / f"{GAME_NAME}.m1", load_unloads=orders)
    (game_dir / f"{GAME_NAME}.x1").write_bytes(data)


def write_unload_x1(game_dir: Path, fleet_id: int, planet_id: int, opcode: int) -> None:
    lu = ManualLoadUnload(
        fleet_num=fleet_id,
        planet_id=planet_id,
        opcode=opcode,
        cargo={CARGO_IRONIUM_BIT: 5},
    )
    data = build_x1([], game_dir / f"{GAME_NAME}.m1", load_unloads=[lu])
    (game_dir / f"{GAME_NAME}.x1").write_bytes(data)


def main():
    print("=== R0.7 Oracle: ManualSmallLoadUnloadTask unload opcode ===\n")

    xvfb = ensure_xvfb(":99")
    time.sleep(0.5)

    create_game()

    state_backup = ORACLE_DIR / "_state_after_t1"

    # --- Turn 1: LOAD onto all fleets, find which one gained ironium ---
    if not state_backup.exists():
        print("[turn 1] Loading 5kT ironium onto all starting fleets...")
        m1_before = ORACLE_DIR / f"{GAME_NAME}.m1"
        fleet_planet = get_fleet_planets(m1_before)
        print(
            f"  Fleets found: {sorted(fleet_planet.keys())} at planets {sorted(set(fleet_planet.values()))}"
        )

        write_load_x1(ORACLE_DIR, fleet_planet)
        run_host(ORACLE_DIR)

        cargo_t1 = parse_fleet_cargo(ORACLE_DIR / f"{GAME_NAME}.m1")
        loaded = {fid: kt for fid, kt in cargo_t1.items() if kt > 0}
        print(f"  Fleets with ironium after turn 1: {loaded}")

        if not loaded:
            print(
                "  ERROR: No fleet loaded ironium. Planet lacks surface ironium or all fleets lack cargo space."
            )
            if xvfb:
                xvfb.terminate()
            sys.exit(1)

        target_fleet = max(loaded, key=lambda f: loaded[f])
        iron_t1 = loaded[target_fleet]
        target_planet = fleet_planet[target_fleet]
        print(f"  Using fleet {target_fleet} at planet {target_planet:#06x}: {iron_t1} kT ironium.")

        state_backup.mkdir()
        for f in ORACLE_DIR.iterdir():
            if f.name != "stars.exe" and not f.name.startswith("_") and f.is_file():
                shutil.copy2(f, state_backup / f.name)
        (state_backup / "_oracle_meta.txt").write_text(
            f"fleet_id={target_fleet}\nplanet_id={target_planet}\niron_t1={iron_t1}\n"
        )
    else:
        print("[turn 1] Already run — reading saved state.")
        meta = dict(
            line.split("=", 1)
            for line in (state_backup / "_oracle_meta.txt").read_text().splitlines()
            if "=" in line
        )
        target_fleet = int(meta["fleet_id"])
        target_planet = int(meta["planet_id"])
        iron_t1 = int(meta["iron_t1"])
        print(f"  fleet {target_fleet} at planet {target_planet:#06x}: {iron_t1} kT ironium.")

    print()

    # --- Turn 2: Try each unload opcode candidate ---
    print("[turn 2] Testing unload opcode candidates...")
    results = {}
    for opcode in CANDIDATES:
        for f in state_backup.iterdir():
            if not f.name.startswith("_"):
                shutil.copy2(f, ORACLE_DIR / f.name)

        write_unload_x1(ORACLE_DIR, target_fleet, target_planet, opcode)
        run_host(ORACLE_DIR)

        cargo_t2 = parse_fleet_cargo(ORACLE_DIR / f"{GAME_NAME}.m1")
        iron_t2 = cargo_t2.get(target_fleet, 0)
        worked = iron_t2 < iron_t1
        results[opcode] = iron_t2
        status = "✓ UNLOADED" if worked else "✗ no change"
        print(f"  opcode=0x{opcode:02x}: fleet{target_fleet} ironium = {iron_t2} kT  {status}")

    print("\n=== Results ===")
    confirmed = [o for o, v in results.items() if v < iron_t1]
    if confirmed:
        print(f"Unload opcode(s) confirmed: {[hex(o) for o in confirmed]}")
    else:
        print("No candidate worked. Need to expand search.")

    if xvfb:
        xvfb.terminate()


if __name__ == "__main__":
    main()
