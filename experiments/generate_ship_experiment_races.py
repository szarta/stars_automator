#!/usr/bin/env python3
"""Generate race JSON files for the R2.3 starting fleet composition oracle experiment.

Cross product:
  X: 10 PRTs
  Y: 96 LRT combos — IFE×2, ARM/OBRM×3 (none|ARM|OBRM), NAS×2, CE×2, NRE×2, ISB×2
  Z: 64 tech subsets — all subsets of {energy,weapons,propulsion,construction,electronics,
     biotechnology} set to Expensive; EB flag on for non-empty subsets (start at Tech 4)

Total: 10 × 96 × 64 = 61,440 files.

Naming: {prt}_{lrt_combo}_{tech_combo}.json
  lrt_combo: dot-separated LRT names in canonical order, or "none"
  tech_combo: dot-separated 2-char tech abbreviations in canonical order, or "none"

Race JSON key is expensive_tech_start_at_4 (confirmed 2026-04-16).
"""

import json
import itertools
import sys
from pathlib import Path

PRTS = ["HE", "SS", "WM", "CA", "IS", "SD", "PP", "IT", "AR", "JOAT"]

LRT_BINARY = ["IFE", "NAS", "CE", "NRE", "ISB"]
ARM_OBRM_STATES = [
    [],          # neither
    ["ARM"],     # ARM only
    ["OBRM"],    # OBRM (ARM+OBRM = OBRM, so we only generate OBRM alone)
]

TECH_FIELDS = ["energy", "weapons", "propulsion", "construction", "electronics", "biotechnology"]
TECH_ABBREV = {
    "energy":       "en",
    "weapons":      "we",
    "propulsion":   "pr",
    "construction": "co",
    "electronics":  "el",
    "biotechnology":"bi",
}

# Canonical order for LRT naming
LRT_ORDER = ["IFE", "ARM", "OBRM", "NAS", "CE", "NRE", "ISB"]


def lrt_combo_name(lrts: list[str]) -> str:
    parts = [l.lower() for l in LRT_ORDER if l in lrts]
    return ".".join(parts) if parts else "none"


def tech_combo_name(expensive: list[str]) -> str:
    parts = [TECH_ABBREV[t] for t in TECH_FIELDS if t in expensive]
    return ".".join(parts) if parts else "none"


def make_race(prt: str, lrts: list[str], expensive: list[str]) -> dict:
    eb = bool(expensive)
    rc = {f: ("expensive" if f in expensive else "normal") for f in TECH_FIELDS}
    rc["expensive_tech_start_at_4"] = eb

    # Compact name for Stars! display (≤30 chars).
    # Initials: LRTs — I=IFE A=ARM O=OBRM N=NAS C=CE R=NRE S=ISB
    # Techs    — E=energy W=weapons P=propulsion K=construction L=electronics B=bio
    LRT_INIT  = {"IFE":"I","ARM":"A","OBRM":"O","NAS":"N","CE":"C","NRE":"R","ISB":"S"}
    TECH_INIT = {"energy":"E","weapons":"W","propulsion":"P",
                 "construction":"K","electronics":"L","biotechnology":"B"}
    lrt_code  = "".join(LRT_INIT[l] for l in LRT_ORDER if l in lrts) or "x"
    tech_code = "".join(TECH_INIT[t] for t in TECH_FIELDS if t in expensive) or "x"
    name = f"{prt}_{lrt_code}_{tech_code}"

    return {
        "format_version": 1,
        "name": "Humanoid",
        "plural_name": "Humanoids",
        "prt": prt,
        "lrts": lrts,
        "hab": {
            "gravity":     {"immune": False, "min": 0.22,  "max": 4.4},
            "temperature": {"immune": False, "min": -140.0,"max": 140.0},
            "radiation":   {"immune": False, "min": 0.0,   "max": 100.0},
        },
        "economy": {
            "resource_production":       1000,
            "factory_production":        10,
            "factory_cost":              10,
            "factory_cheap_germanium":   False,
            "colonists_operate_factories": 10,
            "mine_production":           10,
            "mine_cost":                 5,
            "colonists_operate_mines":   10,
            "growth_rate":               1,
        },
        "research_costs": rc,
        "leftover_spend": "surface_minerals",
        "icon_index": 0,
    }


def generate(output_dir: str) -> int:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    count = 0
    for prt in PRTS:
        for arm_obrm in ARM_OBRM_STATES:
            for bits in itertools.product([False, True], repeat=len(LRT_BINARY)):
                lrts = arm_obrm + [l for l, b in zip(LRT_BINARY, bits) if b]

                for tech_bits in range(1 << len(TECH_FIELDS)):  # 0..63
                    expensive = [TECH_FIELDS[i] for i in range(len(TECH_FIELDS))
                                 if tech_bits & (1 << i)]

                    la = lrt_combo_name(lrts)
                    ta = tech_combo_name(expensive)
                    stem = f"{prt.lower()}_{la}_{ta}"

                    race = make_race(prt, lrts, expensive)
                    with open(out / f"{stem}.json", "w") as f:
                        json.dump(race, f, indent=2)
                    count += 1

    return count


if __name__ == "__main__":
    from stars_automator.config import DEFAULT_RESEARCH_DIR
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else str(Path(DEFAULT_RESEARCH_DIR) / "original" / "race_ship_permutations"))
    n = generate(out_dir)
    print(f"Generated {n} race files → {out_dir}")
