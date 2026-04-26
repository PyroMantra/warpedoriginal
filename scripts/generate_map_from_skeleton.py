import json
import random
import sys
from pathlib import Path

DEFAULT_TEXTURES = {
    "desert": ["desert_01", "desert_02"],
    "grass": ["grass_01", "grass_02"],
    "forest": ["forest_01"],
    "sundune": ["sundune_01"],
    "corruption": ["corruption_01"],
    "frostreach": ["frostreach_01"],
}

ENTITY_POOL_OUTER = ["bandit", "beast", "undead"]
ENTITY_POOL_CORE = ["bandit_elite", "corruption_spawn", "legion_elite", "undead_elite"]

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def clamp01(x):
    return max(0.0, min(1.0, float(x)))

def assign_region_biomes(skeleton, params, rng):
    regions = {}
    outer_pool = params.get("biome_pool_outer", ["desert", "grass", "forest"])
    core_pool = params.get("biome_pool_core", ["grass", "corruption"])
    for cell in skeleton["cells"]:
        if not cell["active"] or not cell.get("allow_biomes", False):
            continue
        region = cell["region"]
        if region in regions:
            continue
        role = cell["role"]
        if role == "core_area":
            regions[region] = rng.choice(core_pool)
        elif role in {"center_ring", "center_core"}:
            regions[region] = rng.choice(core_pool)
        else:
            regions[region] = rng.choice(outer_pool)
    return regions

def choose_cells(cells, n, rng):
    if n <= 0 or not cells:
        return []
    if n >= len(cells):
        return list(cells)
    return rng.sample(cells, n)

def generate_map(skeleton, params):
    rng = random.Random(int(params.get("seed", 12345)))
    region_biomes = assign_region_biomes(skeleton, params, rng)

    out = {
        "name": f'{skeleton["name"]}_seed_{params.get("seed", 12345)}',
        "seed": int(params.get("seed", 12345)),
        "skeleton": skeleton["name"],
        "cells": [],
    }

    # candidate pools
    active_cells = [c for c in skeleton["cells"] if c["active"]]
    outer_cells = [c for c in active_cells if c["role"] in {"outer_area", "connector"} and not c["spawn"]]
    core_cells = [c for c in active_cells if c["role"] in {"core_area", "center_ring", "center_core"} and not c["spawn"]]

    outer_landmark_candidates = [c for c in outer_cells if c.get("allow_landmarks")]
    core_landmark_candidates = [c for c in core_cells if c.get("allow_landmarks")]
    outer_entity_candidates = [c for c in outer_cells if c.get("allow_entities")]
    core_entity_candidates = [c for c in core_cells if c.get("allow_entities")]

    landmark_marks = {}
    counts = params.get("landmark_counts", {})
    all_landmark_candidates = outer_landmark_candidates + core_landmark_candidates
    used_ids = set()
    for landmark, cfg in counts.items():
        lo = int(cfg.get("min", 0))
        hi = int(cfg.get("max", lo))
        n = rng.randint(lo, hi)
        available = [c for c in all_landmark_candidates if (c["row"], c["col"]) not in used_ids]
        for c in choose_cells(available, n, rng):
            key = (c["row"], c["col"])
            used_ids.add(key)
            landmark_marks[key] = landmark

    outer_entity_density = params.get("entity_density_outer", params.get("enemy_density_outer", 0.12))
    core_entity_density = params.get("entity_density_core", params.get("enemy_density_core", 0.18))
    outer_entity_count = int(len(outer_entity_candidates) * clamp01(outer_entity_density))
    core_entity_count = int(len(core_entity_candidates) * clamp01(core_entity_density))
    entity_marks = {}
    for c in choose_cells(outer_entity_candidates, outer_entity_count, rng):
        entity_marks[(c["row"], c["col"])] = rng.choice(ENTITY_POOL_OUTER)
    for c in choose_cells(core_entity_candidates, core_entity_count, rng):
        entity_marks[(c["row"], c["col"])] = rng.choice(ENTITY_POOL_CORE)

    outer_loot_count = int(len(outer_landmark_candidates) * clamp01(params.get("loot_density_outer", 0.10)))
    core_loot_count = int(len(core_landmark_candidates) * clamp01(params.get("loot_density_core", 0.14)))
    loot_marks = {}
    for c in choose_cells([c for c in outer_landmark_candidates if (c["row"], c["col"]) not in landmark_marks], outer_loot_count, rng):
        loot_marks[(c["row"], c["col"])] = "loot"
    for c in choose_cells([c for c in core_landmark_candidates if (c["row"], c["col"]) not in landmark_marks], core_loot_count, rng):
        loot_marks[(c["row"], c["col"])] = "loot"

    for cell in skeleton["cells"]:
        role = cell["role"]
        key = (cell["row"], cell["col"])

        biome = region_biomes.get(cell["region"])
        if role == "void":
            biome = None

        if role == "center_core":
            landmark = cell.get("special") or "boss"
        else:
            landmark = landmark_marks.get(key)

        if cell["spawn"]:
            landmark = None

        entity = entity_marks.get(key)
        if cell["spawn"]:
            entity = None

        loot_type = loot_marks.get(key)
        defended = False
        if landmark or loot_type:
            if role in {"center_ring", "center_core", "core_area"}:
                defended = rng.random() < clamp01(params.get("defended_chance_core", 0.4))
            else:
                defended = rng.random() < clamp01(params.get("defended_chance_outer", 0.15))

        texture = None
        if biome:
            texture = rng.choice(DEFAULT_TEXTURES.get(biome, [biome]))

        zone = None
        if role == "spawn":
            zone = "spawn"
        elif role == "center_core":
            zone = "objective"

        out["cells"].append({
            "row": cell["row"],
            "col": cell["col"],
            "active": cell["active"],
            "role": role,
            "region": cell["region"],
            "spawn": cell["spawn"],
            "special": cell.get("special"),
            "biome": biome,
            "texture": texture,
            "zone": zone,
            "landmark": landmark,
            "entity": entity,
            "hero": None,
            "loot": loot_type,
            "defended": defended,
        })

    return out

def main():
    if len(sys.argv) < 4:
        print("Usage: py scripts/generate_map_from_skeleton.py data/map_skeletons/8p_cross_01.json data/mapgen/example_params.json data/generated_maps/8p_cross_01_seed_12345.json")
        raise SystemExit(1)

    skeleton = load_json(sys.argv[1])
    params = load_json(sys.argv[2])
    result = generate_map(skeleton, params)

    out_path = Path(sys.argv[3])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
