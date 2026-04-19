#!/usr/bin/env python3
"""Run all R2.6 Phase 1 BBS oracle games and dump homeworld populations.

Calls stars_automator.game for each experiment config, then m1_to_json to read
the player-1 homeworld population from the resulting .m1 file.

Usage:
    python3 run_bbs_phase1.py [--display :99] [--timeout 120] [--force]

Options:
    --display  X display for Xvfb (default: :99)
    --timeout  seconds to wait for stars.exe -a before killing it (default: 120)
    --force    delete existing /tmp/<name>/ dirs and recreate from scratch

Environment variables:
    STARS_PARSER_DIR    Directory of stars_file_parser binaries
                        (default: ~/data/stars/stars_file_parser/target/debug)
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, time

HERE        = pathlib.Path(__file__).parent
CONFIGS_DIR = HERE / "oracle_configs" / "r2_6"
EXPERIMENTS = [
    "bbs_joat_gr05",
    "bbs_joat_gr10",
    "bbs_joat_gr14",
    "bbs_joat_gr10_lsp",
    "bbs_pp_gr10",
    "bbs_it_gr10",
    "bbs_pp_gr05",
    "bbs_pp_gr14",
]

DEFAULT_PARSER_DIR = os.path.expanduser(
    os.environ.get("STARS_PARSER_DIR", "~/data/stars/stars_file_parser/target/debug")
)


def run_create_game(cfg_path: pathlib.Path, display: str, timeout: int) -> bool:
    """Run stars_automator.game with a timeout on the wine subprocess.

    Returns True on success, False on timeout or error.
    """
    cmd = [
        sys.executable, "-m", "stars_automator.game",
        str(cfg_path),
        "--display", display,
    ]
    print(f"  [create_game] {cfg_path.name}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    deadline = time.monotonic() + timeout
    output_lines = []
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait()
                print(f"  [TIMEOUT after {timeout}s] killed")
                for line in output_lines[-10:]:
                    print(f"    {line}", end="")
                return False
            try:
                line = proc.stdout.readline()
            except Exception:
                break
            if not line:
                break
            output_lines.append(line)
            print(f"    {line}", end="", flush=True)
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        print(f"  [ERROR] stars_automator.game exited {proc.returncode}")
        return False
    return True


def read_homeworld_pop(workdir: pathlib.Path, game_name: str,
                       parser_dir: str) -> int | None:
    """Read player-1 homeworld population from .m1 file."""
    m1 = workdir / f"{game_name}.m1"
    if not m1.exists():
        return None
    m1_to_json = os.path.join(parser_dir, "m1_to_json")
    result = subprocess.run([m1_to_json, str(m1)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [m1_to_json error] {result.stderr[:200]}")
        return None
    data = json.loads(result.stdout)
    planets = data.get("planets", [])
    for pl in planets:
        if pl.get("homeworld"):
            return pl.get("population")
    for pl in planets:
        pop = pl.get("population")
        if pop and pop > 0:
            return pop
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--display",  default=":99")
    ap.add_argument("--timeout",  type=int, default=120,
                    help="seconds before killing a stalled stars.exe (default 120)")
    ap.add_argument("--force",    action="store_true",
                    help="delete existing /tmp/<name>/ and recreate")
    args = ap.parse_args()

    parser_dir = DEFAULT_PARSER_DIR

    results = {}
    for name in EXPERIMENTS:
        cfg_path = CONFIGS_DIR / f"{name}.json"
        workdir  = pathlib.Path(f"/tmp/{name}")
        cfg      = json.loads(cfg_path.read_text())
        game_name = cfg.get("game_name", "Game")

        print(f"\n{'='*60}")
        print(f"Experiment: {name}")
        print(f"{'='*60}")

        if args.force and workdir.exists():
            print(f"  [force] removing {workdir}")
            shutil.rmtree(workdir)

        hst = workdir / f"{game_name}.hst"
        if hst.exists():
            print(f"  [skip] {game_name}.hst already exists")
        else:
            ok = run_create_game(cfg_path, args.display, args.timeout)
            if not ok:
                results[name] = {"error": "create_game failed or timed out"}
                continue

        pop_raw = read_homeworld_pop(workdir, game_name, parser_dir)
        if pop_raw is None:
            results[name] = {"error": "could not read homeworld population"}
        else:
            pop = pop_raw * 100  # m1 stores population in units of 100 colonists
            gr = cfg["human_races"][0]["economy"]["growth_rate"]
            prt = cfg["human_races"][0].get("prt", "?")
            lrts = cfg["human_races"][0].get("lrts", [])
            expected = 25000 + 5000 * gr
            match = "✓" if pop == expected else f"✗ (got {pop:,})"
            results[name] = {
                "prt": prt, "lrts": lrts, "gr": gr,
                "population": pop, "population_raw": pop_raw,
                "expected": expected, "match": match,
            }
            print(f"  homeworld pop = {pop:,}  expected {expected:,}  {match}")

    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"{'Experiment':<25} {'PRT':<6} {'GR':>4} {'LRTs':<12} {'Pop':>8}  {'Expected':>8}  Match")
    print("-" * 80)
    for name, r in results.items():
        if "error" in r:
            print(f"{name:<25}  ERROR: {r['error']}")
        else:
            lrt_str = "+".join(r["lrts"]) or "—"
            print(f"{name:<25} {r['prt']:<6} {r['gr']:>4}  {lrt_str:<12} "
                  f"{r['population']:>8,}  {r['expected']:>8,}  {r['match']}")

    results_path = CONFIGS_DIR / "phase1_results.json"
    results_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nResults written to {results_path}")


if __name__ == "__main__":
    main()
