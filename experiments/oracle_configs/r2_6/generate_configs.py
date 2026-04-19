#!/usr/bin/env python3
"""Generate game config JSON files for R2.6 Phase 1 (Accelerated BBS population oracle).

JOAT+IFE with standard wide hab is valid up to GR=14% (GR=15+ goes over budget).
Variant races (LSP, PP, IT) use GR=10% to stay comfortably in budget.
IFE is included in all races: Phase 1 needs it to be consistent with Phase 2
(same race design), and it gives Fuel Mizer scouts (warp-4 free fuel) for Phase 2
exploration.  IFE does NOT affect starting population.

Environment variables:
    STARS_RESEARCH_DIR  Root of the stars-reborn-research repo
                        (default: ~/data/stars/stars-reborn-research)
"""
import copy, json, os, pathlib

HERE = pathlib.Path(__file__).parent
BASE_RACE = json.loads((HERE / "_base_race_joat_ife.json").read_text())

SEED = 12345  # fixed across all experiments for reproducibility

_RESEARCH = pathlib.Path(
    os.environ.get("STARS_RESEARCH_DIR", "~/data/stars/stars-reborn-research")
).expanduser()

# Second player — only present so Stars! accepts the game; never read for results.
FILLER_RACE = str(_RESEARCH / "original" / "stars.r1")


def make_race(gr, lrts=None, prt="JOAT"):
    r = copy.deepcopy(BASE_RACE)
    r["prt"] = prt
    r["economy"]["growth_rate"] = gr
    r["lrts"] = sorted(lrts if lrts is not None else ["IFE"])
    return r


def make_config(name, race):
    return {
        "experiment_name": name,
        "game_name": "BBSTest",
        "universe": {
            "map_size":         "small",
            "density":          "normal",
            "player_positions": "moderate",
            "seed":             SEED,
        },
        "options": {
            "max_minerals":       False,
            "slow_tech":          False,
            "bbs_play":           True,
            "galaxy_clumping":    False,
            "computer_alliances": False,
            "no_random_events":   True,
            "public_scores":      False,
        },
        "victory": {
            "planets":         {"enabled": True,  "percent": 60},
            "tech":            {"enabled": False, "level": 26, "fields": 4},
            "score":           {"enabled": False, "score": 5000},
            "exceeds_nearest": {"enabled": False, "percent": 150},
            "production":      {"enabled": False, "capacity": 100},
            "capital_ships":   {"enabled": False, "number": 100},
            "turns":           {"enabled": False, "years": 100},
            "must_meet": 1,
            "min_years": 50,
        },
        # Two human players: Stars! requires ≥2 players, and humans don't
        # auto-move, so the second player's homeworld concentrations stay
        # untouched (no turn processing without submitted .x files).
        "human_races": [race, FILLER_RACE],
        "ai_players": [],
    }


# GR scaling tests: 5/10/14 span the formula; 14 is max valid for JOAT+IFE.
# Expected BBS pop: 25000 + 5000*GR
#   gr05 → 50000   gr10 → 75000   gr14 → 95000
#
# Variant tests use GR=10 (valid for all PRTs+IFE+extra LRTs).
EXPERIMENTS = [
    ("bbs_joat_gr05",     make_race(5)),
    ("bbs_joat_gr10",     make_race(10)),
    ("bbs_joat_gr14",     make_race(14)),
    ("bbs_joat_gr10_lsp", make_race(10, lrts=["IFE", "LSP"])),
    ("bbs_pp_gr10",       make_race(10, prt="PP")),
    ("bbs_it_gr10",       make_race(10, prt="IT")),
    # PP/IT formula disambiguation: need 2 GR values to distinguish hypotheses.
    # A: (25k+5k×GR)×0.8 → gr05=40k  gr14=76k
    # B:  10k+5k×GR      → gr05=35k  gr14=80k
    ("bbs_pp_gr05",       make_race(5,  prt="PP")),
    ("bbs_pp_gr14",       make_race(14, prt="PP")),
]

for name, race in EXPERIMENTS:
    cfg = make_config(name, race)
    out = HERE / f"{name}.json"
    out.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"wrote {out.name}")
