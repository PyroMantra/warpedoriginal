from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import jsonify, redirect, render_template, request, session, url_for
from flask_socketio import emit, join_room, leave_room

try:
    import redis as redis_lib
except Exception:
    redis_lib = None


ROLE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "empty": {
        "active": False,
        "spawn": False,
        "special": None,
        "allow_biomes": False,
        "allow_landmarks": False,
        "allow_entities": False,
    },
    "outer_area": {
        "active": True,
        "spawn": False,
        "special": None,
        "allow_biomes": True,
        "allow_landmarks": True,
        "allow_entities": True,
    },
    "connector": {
        "active": True,
        "spawn": False,
        "special": None,
        "allow_biomes": False,
        "allow_landmarks": False,
        "allow_entities": True,
    },
    "core_area": {
        "active": True,
        "spawn": False,
        "special": None,
        "allow_biomes": True,
        "allow_landmarks": True,
        "allow_entities": True,
    },
    "center_ring": {
        "active": True,
        "spawn": False,
        "special": None,
        "allow_biomes": True,
        "allow_landmarks": True,
        "allow_entities": True,
    },
    "center_core": {
        "active": True,
        "spawn": False,
        "special": None,
        "allow_biomes": False,
        "allow_landmarks": True,
        "allow_entities": True,
    },
    "spawn": {
        "active": True,
        "spawn": True,
        "special": "player_spawn",
        "allow_biomes": False,
        "allow_landmarks": False,
        "allow_entities": False,
    },
    "water": {
        "active": True,
        "spawn": False,
        "special": None,
        "allow_biomes": False,
        "allow_landmarks": False,
        "allow_entities": False,
    },
}

ROLE_COLORS: Dict[str, str] = {
    "empty": "#111827",
    "outer_area": "#facc15",
    "connector": "#b45309",
    "core_area": "#22c55e",
    "center_ring": "#06b6d4",
    "center_core": "#ef4444",
    "spawn": "#2563eb",
    "water": "#0f766e",
}

OUTER_BIOME_HINTS = ("grass", "sakura", "sundune", "elysian", "frostreach", "desolation")
CORE_BIOME_HINTS = ("blood", "grim", "under", "volcan", "corrupt", "desolat", "frost")
DISABLED_BIOMES = {"underspread"}
OUTER_ENTITY_HINTS = ("weakling", "companion", "questgiver", "hand")
CORE_ENTITY_HINTS = ("elite", "guardian")
BOSS_ENTITY_HINTS = ("boss", "god", "guardian")
SPAWN_ENTITY_HINTS = ("hero",)
DISABLED_LANDMARK_KEYS = {
    "ward",
    "gravestone",
    "kingdom",
    "pillagedarena",
    "pillagedblackmarket",
    "pillagedfoundry",
    "pillagedlibrary",
    "pillagedmarket",
    "pillagedport",
    "pillagedshrine",
    "pillagedtavern",
}
TERRAIN_VARIANT_WEIGHTS: Dict[str, Dict[str, int]] = {
    "outer_area": {"simple": 60, "forest": 20, "special": 15, "bonus": 5},
    "core_area": {"simple": 50, "forest": 20, "special": 20, "bonus": 10},
    "center_ring": {"simple": 40, "forest": 20, "special": 25, "bonus": 15},
}
TERRAIN_VARIANT_VARIANCE = 5
MOUNTAIN_BASE_CHANCE = 0.02
MOUNTAIN_ADJACENT_CHAIN_CHANCE = 0.10
CENTER_WATER_MAELSTROM_CHANCE = 0.08
MAELSTROM_MIN_DISTANCE = 20
CENTER_RING_LAVA_CHANCE = 0.08
CENTER_CORE_LAVA_CHANCE = 0.08
CENTER_CORE_VOID_CHANCE = 0.05
CENTER_CORE_MOUNTAIN_CHANCE = 0.15
ZONE_PORT_CHANCE = 0.30
ZONES_PER_REGION = 2
GUARDED_ELIGIBLE_LANDMARK_KEYS = {"chest", "treasurechest", "legendarychest", "gold"}
GUARDED_ELIGIBLE_ENTITY_KEYS = {"companion"}
NON_ZONE_LANDMARK_STACK_CHANCE = 0.14
OUTER_UNKNOWNSITE_DENSITY = 7
OUTER_WEAKLING_DENSITY = 10
OUTER_CHEST_PAIR_DENSITY = 14
OUTER_QUESTGIVER_MIN_HEXES = 10
OUTER_COMPANION_MIN_HEXES = 10
OUTER_LEGENDARY_MIN_HEXES = 12
OUTER_LEGENDARY_SPAWN_DISTANCE = 3
OUTER_COMPANION_SPAWN_DISTANCE = 2


def _parse_named_parts(stem: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in str(stem or "").split(","):
        part = raw.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _slugify_label(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower())
    return re.sub(r"_+", "_", s).strip("_") or "asset"


def _load_texture_assets() -> List[Dict[str, Any]]:
    base = Path(__file__).resolve().parent / "static" / "mapgen" / "textures"
    assets: List[Dict[str, Any]] = []
    if not base.exists():
        return assets
    for file in sorted(base.glob("*.png")):
        parts = _parse_named_parts(file.stem)
        biome = parts.get("biome", "Neutral")
        variant = parts.get("type") or parts.get("hex") or "base"
        assets.append(
            {
                "id": _slugify_label(file.stem),
                "label": file.stem,
                "file_name": file.name,
                "biome": biome,
                "variant": variant,
            }
        )
    return assets


def _load_landmark_assets() -> List[Dict[str, Any]]:
    base = Path(__file__).resolve().parent / "static" / "mapgen" / "landmarks"
    assets: List[Dict[str, Any]] = []
    if not base.exists():
        return assets
    for file in sorted(base.glob("*.png")):
        parts = _parse_named_parts(file.stem)
        label = parts.get("landmark") or parts.get("zone") or file.stem
        group = "zone" if "zone" in parts else "landmark"
        assets.append(
            {
                "id": _slugify_label(file.stem),
                "label": label,
                "file_name": file.name,
                "group": group,
                "color": parts.get("color"),
                "name_key": _slugify_label(label),
            }
        )
    return assets


def _load_entity_assets() -> List[Dict[str, Any]]:
    base = Path(__file__).resolve().parent / "static" / "mapgen" / "entities"
    assets: List[Dict[str, Any]] = []
    if not base.exists():
        return assets
    for file in sorted(base.glob("*.png")):
        parts = _parse_named_parts(file.stem)
        npc = parts.get("npc") or file.stem
        hero = parts.get("hero")
        label = hero if npc.lower() == "hero" and hero else npc
        assets.append(
            {
                "id": _slugify_label(file.stem),
                "label": label,
                "file_name": file.name,
                "npc": npc,
                "hero": hero,
                "name_key": _slugify_label(label if label else npc),
            }
        )
    return assets


def _load_addon_assets() -> Dict[str, Dict[str, Any]]:
    base = Path(__file__).resolve().parent / "static" / "mapgen" / "addons"
    assets: Dict[str, Dict[str, Any]] = {}
    if not base.exists():
        return assets
    for file in sorted(base.glob("*.png")):
        key = _slugify_label(file.stem)
        assets[key] = {
            "id": key,
            "label": file.stem,
            "file_name": file.name,
        }
    return assets


def _pick_matching_by_hints(values: List[str], hints: tuple[str, ...]) -> List[str]:
    matched = [v for v in values if any(h in v.lower() for h in hints)]
    return matched or values


def _pick_role_biome(role: str, available_biomes: List[str], rng: random.Random) -> str | None:
    if not available_biomes:
        return None
    if role in {"core_area", "center_ring", "center_core"}:
        pool = _pick_matching_by_hints(available_biomes, CORE_BIOME_HINTS)
    else:
        pool = _pick_matching_by_hints(available_biomes, OUTER_BIOME_HINTS)
    return rng.choice(pool)


def _pick_weighted(items: List[Dict[str, Any]], rng: random.Random) -> Dict[str, Any] | None:
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    total = 0
    cumulative: List[tuple[int, Dict[str, Any]]] = []
    for item in items:
        weight = max(1, int(item.get("_weight", 1)))
        total += weight
        cumulative.append((total, item))
    roll = rng.randint(1, total)
    for threshold, item in cumulative:
        if roll <= threshold:
            return item
    return items[-1]


def _allocate_variant_counts(total: int, weights: Dict[str, int]) -> Dict[str, int]:
    if total <= 0 or not weights:
        return {}
    weight_sum = sum(max(0, int(v)) for v in weights.values())
    if weight_sum <= 0:
        return {}

    floors: Dict[str, int] = {}
    remainders: List[tuple[float, str]] = []
    assigned = 0
    for variant, weight in weights.items():
        exact = (total * max(0, int(weight))) / weight_sum
        floor_val = int(exact)
        floors[variant] = floor_val
        assigned += floor_val
        remainders.append((exact - floor_val, variant))

    remaining = total - assigned
    remainders.sort(key=lambda x: (-x[0], x[1]))
    idx = 0
    while remaining > 0 and remainders:
        _, variant = remainders[idx % len(remainders)]
        floors[variant] += 1
        remaining -= 1
        idx += 1
    return floors


def _jitter_variant_weights(weights: Dict[str, int], variance: int, rng: random.Random) -> Dict[str, int]:
    if not weights:
        return {}
    variance = max(0, int(variance))
    if variance == 0:
        return dict(weights)

    variants = list(weights.keys())
    raw: Dict[str, int] = {}
    for variant, value in weights.items():
        base = int(value)
        low = max(1, base - variance)
        high = max(low, base + variance)
        raw[variant] = rng.randint(low, high)

    total = sum(raw.values())
    target = sum(int(v) for v in weights.values())
    if total <= 0 or target <= 0:
        return dict(weights)

    scaled_exact: Dict[str, float] = {
        variant: (raw[variant] * target) / total
        for variant in variants
    }
    scaled: Dict[str, int] = {
        variant: max(1, int(scaled_exact[variant]))
        for variant in variants
    }

    current = sum(scaled.values())
    if current < target:
        remainders = sorted(
            ((scaled_exact[v] - int(scaled_exact[v]), v) for v in variants),
            key=lambda x: (-x[0], x[1]),
        )
        idx = 0
        while current < target and remainders:
            _, variant = remainders[idx % len(remainders)]
            scaled[variant] += 1
            current += 1
            idx += 1
    elif current > target:
        removable = sorted(
            ((scaled[v] - scaled_exact[v], v) for v in variants),
            key=lambda x: (-x[0], x[1]),
        )
        idx = 0
        while current > target and removable:
            _, variant = removable[idx % len(removable)]
            if scaled[variant] > 1:
                scaled[variant] -= 1
                current -= 1
            idx += 1
            if idx > len(removable) * 4:
                break

    return scaled


def _build_biome_variant_plan(
    cells: List[Dict[str, Any]],
    region_biomes: Dict[str, str],
    textures: List[Dict[str, Any]],
    rng: random.Random,
) -> Dict[tuple[int, int], Dict[str, Any]]:
    by_region: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cell in cells:
        if not cell.get("active") or not cell.get("allow_biomes"):
            continue
        if str(cell.get("role") or "").strip().lower() == "center_core":
            continue
        region = str(cell.get("region") or "").strip()
        biome = region_biomes.get(region)
        if not region or not biome:
            continue
        by_region[region].append(cell)

    planned: Dict[tuple[int, int], Dict[str, Any]] = {}
    for region, region_cells in by_region.items():
        if not region_cells:
            continue
        biome = region_biomes.get(region)
        role = str(region_cells[0].get("role") or "outer_area")
        weights = TERRAIN_VARIANT_WEIGHTS.get(role)
        biome_assets = [a for a in textures if a["biome"].lower() == str(biome).lower()]
        if not biome_assets:
            continue

        variant_assets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for asset in biome_assets:
            variant_assets[str(asset.get("variant") or "").strip().lower()].append(asset)

        if not weights:
            shuffled_cells = list(region_cells)
            rng.shuffle(shuffled_cells)
            for cell in shuffled_cells:
                planned[(cell["row"], cell["col"])] = rng.choice(biome_assets)
            continue

        varied_weights = _jitter_variant_weights(weights, TERRAIN_VARIANT_VARIANCE, rng)
        counts = _allocate_variant_counts(len(region_cells), varied_weights)
        shuffled_cells = list(region_cells)
        rng.shuffle(shuffled_cells)
        cell_idx = 0

        # First place the explicitly weighted variants.
        for variant, count in counts.items():
            assets_for_variant = variant_assets.get(variant)
            if not assets_for_variant:
                continue
            for _ in range(count):
                if cell_idx >= len(shuffled_cells):
                    break
                cell = shuffled_cells[cell_idx]
                planned[(cell["row"], cell["col"])] = rng.choice(assets_for_variant)
                cell_idx += 1

        # Any leftovers from missing variants fall back to any biome asset.
        while cell_idx < len(shuffled_cells):
            cell = shuffled_cells[cell_idx]
            planned[(cell["row"], cell["col"])] = rng.choice(biome_assets)
            cell_idx += 1

    return planned


def _build_center_core_plan(
    cells: List[Dict[str, Any]],
    textures: List[Dict[str, Any]],
    rng: random.Random,
) -> Dict[tuple[int, int], Dict[str, Any]]:
    center_core_cells = [c for c in cells if c.get("active") and str(c.get("role") or "").lower() == "center_core"]
    if not center_core_cells:
        return {}

    neutral_assets = [a for a in textures if a["biome"].lower() == "neutral"]
    if not neutral_assets:
        return {}

    variant_assets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for asset in neutral_assets:
        variant = str(asset.get("variant") or "").strip().lower()
        variant_assets[variant].append(asset)

    plains_assets = variant_assets.get("plains") or []
    void_assets = variant_assets.get("void") or []
    mountain_assets = variant_assets.get("mountain") or []
    lava_assets = variant_assets.get("lava") or []

    planned: Dict[tuple[int, int], Dict[str, Any]] = {}
    shuffled_cells = list(center_core_cells)
    rng.shuffle(shuffled_cells)

    counts = _allocate_variant_counts(
        len(shuffled_cells),
        {
            "plains": max(0, 100 - CENTER_CORE_VOID_CHANCE * 100 - CENTER_CORE_MOUNTAIN_CHANCE * 100 - CENTER_CORE_LAVA_CHANCE * 100),
            "void": int(round(CENTER_CORE_VOID_CHANCE * 100)),
            "mountain": int(round(CENTER_CORE_MOUNTAIN_CHANCE * 100)),
            "lava": int(round(CENTER_CORE_LAVA_CHANCE * 100)),
        },
    )

    cell_idx = 0
    for variant, assets in (
        ("void", void_assets),
        ("mountain", mountain_assets),
        ("lava", lava_assets),
        ("plains", plains_assets),
    ):
        if not assets:
            continue
        for _ in range(counts.get(variant, 0)):
            if cell_idx >= len(shuffled_cells):
                break
            cell = shuffled_cells[cell_idx]
            planned[(cell["row"], cell["col"])] = rng.choice(assets)
            cell_idx += 1

    fallback_assets = plains_assets or void_assets or mountain_assets or lava_assets or neutral_assets
    while cell_idx < len(shuffled_cells):
        cell = shuffled_cells[cell_idx]
        planned[(cell["row"], cell["col"])] = rng.choice(fallback_assets)
        cell_idx += 1

    return planned


def _neighbor_keys(row: int, col: int) -> List[tuple[int, int]]:
    if row % 2 == 0:
        offsets = [(-1, -1), (-1, 0), (0, -1), (0, 1), (1, -1), (1, 0)]
    else:
        offsets = [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, 0), (1, 1)]
    return [(row + dr, col + dc) for dr, dc in offsets]


def _is_waterish(cell: Dict[str, Any] | None) -> bool:
    if not cell:
        return True
    role = str(cell.get("role") or "").strip().lower()
    return role in {"water", "empty", "void"}


def _land_region(cell: Dict[str, Any] | None) -> str:
    if not cell or _is_waterish(cell):
        return ""
    region = str(cell.get("region") or "").strip().lower()
    if region and region not in {"none", "water"}:
        return region
    role = str(cell.get("role") or "").strip().lower()
    return role if role not in {"connector", ""} else "land"


def _connector_variant(cell: Dict[str, Any], cell_lookup: Dict[tuple[int, int], Dict[str, Any]]) -> str:
    neighbors = [cell_lookup.get(key) for key in _neighbor_keys(int(cell.get("row", 0)), int(cell.get("col", 0)))]
    water_neighbors = sum(1 for n in neighbors if _is_waterish(n))
    land_neighbors = [n for n in neighbors if n and not _is_waterish(n)]
    if len(land_neighbors) < 2:
        return "road"

    # If the connector touches two or more distinct land regions, it's acting as a bridge.
    regions = {r for r in (_land_region(n) for n in land_neighbors) if r}
    if water_neighbors >= 1 and len(regions) >= 2:
        return "bridge"

    # Fallback: opposite land sides across the hex also count as a bridge crossing.
    opposite_pairs = ((0, 5), (1, 4), (2, 3))
    for a_idx, b_idx in opposite_pairs:
        a = neighbors[a_idx] if a_idx < len(neighbors) else None
        b = neighbors[b_idx] if b_idx < len(neighbors) else None
        if a and b and not _is_waterish(a) and not _is_waterish(b):
            if water_neighbors >= 1:
                return "bridge"

    return "road"


def _is_adjacent_to_role(cell: Dict[str, Any], cell_lookup: Dict[tuple[int, int], Dict[str, Any]], role_name: str) -> bool:
    role_name = str(role_name or "").strip().lower()
    for nkey in _neighbor_keys(int(cell.get("row", 0)), int(cell.get("col", 0))):
        neighbor = cell_lookup.get(nkey)
        if neighbor and str(neighbor.get("role") or "").strip().lower() == role_name:
            return True
    return False


def _texture_variant_name(cell: Dict[str, Any] | None) -> str:
    if not cell:
        return ""
    final_texture = cell.get("_final_texture")
    if not final_texture:
        return ""
    return str(final_texture.get("variant") or "").strip().lower()


def _is_blocked_spawn_texture(cell: Dict[str, Any] | None) -> bool:
    return _texture_variant_name(cell) in {"lava", "forest"}


def _is_adjacent_to_waterlike(cell: Dict[str, Any], cell_lookup: Dict[tuple[int, int], Dict[str, Any]]) -> bool:
    for nkey in _neighbor_keys(int(cell.get("row", 0)), int(cell.get("col", 0))):
        neighbor = cell_lookup.get(nkey)
        if not neighbor:
            continue
        if str(neighbor.get("role") or "").strip().lower() == "water":
            return True
        if _texture_variant_name(neighbor) in {"water", "maelstrom"}:
            return True
    return False


def _odd_r_to_cube(row: int, col: int) -> tuple[int, int, int]:
    q = col - (row - (row & 1)) // 2
    r = row
    x = q
    z = r
    y = -x - z
    return x, y, z


def _hex_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    ax, ay, az = _odd_r_to_cube(a[0], a[1])
    bx, by, bz = _odd_r_to_cube(b[0], b[1])
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


def _pick_texture_for_cell(
    cell: Dict[str, Any],
    cell_lookup: Dict[tuple[int, int], Dict[str, Any]],
    region_biomes: Dict[str, str],
    textures: List[Dict[str, Any]],
    biome_variant_plan: Dict[tuple[int, int], Dict[str, Any]],
    rng: random.Random,
) -> Dict[str, Any] | None:
    role = cell.get("role") or "empty"
    if not cell.get("active"):
        return None

    biome = region_biomes.get(cell.get("region") or "")
    if cell.get("allow_biomes") and biome:
        planned = biome_variant_plan.get((int(cell.get("row", 0)), int(cell.get("col", 0))))
        if planned:
            return planned
        matches = [a for a in textures if a["biome"].lower() == biome.lower()]
        if matches:
            return rng.choice(matches)

    neutral = [a for a in textures if a["biome"].lower() == "neutral"]
    if not neutral:
        return None

    if role == "spawn":
        campfire = [a for a in neutral if "campfire" in a["variant"].lower()]
        if campfire:
            return campfire[0]

    preferred_variants: tuple[str, ...]
    if role == "connector":
        preferred_variants = (_connector_variant(cell, cell_lookup),)
    elif role == "water":
        preferred_variants = ("water",)
    elif role == "center_core":
        preferred_variants = ("plains", "mountain", "void", "lava")
    elif role == "center_ring":
        preferred_variants = ("platform", "plains", "road")
    else:
        preferred_variants = ("plains", "forest", "simple")

    matches = [a for a in neutral if any(pref in a["variant"].lower() for pref in preferred_variants)]
    return rng.choice(matches or neutral)


def _pick_landmark_asset(cell: Dict[str, Any], landmarks: List[Dict[str, Any]], rng: random.Random) -> Dict[str, Any] | None:
    if not landmarks:
        return None
    landmarks = [a for a in landmarks if a["name_key"] != "boat" and a["name_key"] not in DISABLED_LANDMARK_KEYS]
    if not landmarks:
        return None
    if cell.get("role") in {"core_area", "center_ring", "center_core"}:
        zones = [a for a in landmarks if a["group"] == "zone" and a["name_key"] not in {"shipwreck", "port"}]
        return rng.choice(zones or landmarks)
    non_zones = [a for a in landmarks if a["group"] != "zone" and a["name_key"] not in {"shipwreck", "portal", "port"}]
    return rng.choice(non_zones or landmarks)


def _asset_by_name_key(assets: List[Dict[str, Any]], name_key: str, group: str | None = None) -> Dict[str, Any] | None:
    wanted = str(name_key or "").strip().lower()
    wanted_group = str(group or "").strip().lower() if group else None
    for asset in assets:
        if str(asset.get("name_key") or "").strip().lower() != wanted:
            continue
        if wanted_group and str(asset.get("group") or "").strip().lower() != wanted_group:
            continue
        return asset
    return None


def _zone_assets(landmarks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        a for a in landmarks
        if a.get("group") == "zone" and a["name_key"] not in DISABLED_LANDMARK_KEYS and a["name_key"] != "shipwreck"
    ]


def _cell_allows_overlay(cell: Dict[str, Any], allow_forest: bool = False) -> bool:
    variant = _texture_variant_name(cell)
    if variant == "lava":
        return False
    if variant == "forest" and not allow_forest:
        return False
    return True


def _has_adjacent_overlay(cell: Dict[str, Any], overlay_by_key: Dict[tuple[int, int], Dict[str, Any]]) -> bool:
    for nkey in _neighbor_keys(int(cell.get("row", 0)), int(cell.get("col", 0))):
        if nkey in overlay_by_key:
            return True
    return False


def _can_place_content(cell: Dict[str, Any], overlay_by_key: Dict[tuple[int, int], Dict[str, Any]], allow_forest: bool = False) -> bool:
    if not _cell_allows_overlay(cell, allow_forest=allow_forest):
        return False
    key = (int(cell.get("row", 0)), int(cell.get("col", 0)))
    if key in overlay_by_key:
        return False
    if _has_adjacent_overlay(cell, overlay_by_key):
        return False
    return True


def _can_place_on_hex_only(cell: Dict[str, Any], overlay_by_key: Dict[tuple[int, int], Dict[str, Any]], allow_forest: bool = False) -> bool:
    if not _cell_allows_overlay(cell, allow_forest=allow_forest):
        return False
    key = (int(cell.get("row", 0)), int(cell.get("col", 0)))
    return key not in overlay_by_key


def _place_overlay(
    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]],
    cell: Dict[str, Any],
    kind: str,
    asset: Dict[str, Any] | None,
    *,
    allow_forest: bool = False,
    guarded: bool = False,
    ignore_adjacent_rule: bool = False,
    no_stack: bool = False,
) -> bool:
    if not asset:
        return False
    if ignore_adjacent_rule:
        if not _can_place_on_hex_only(cell, overlay_by_key, allow_forest=allow_forest):
            return False
    elif not _can_place_content(cell, overlay_by_key, allow_forest=allow_forest):
        return False
    key = (cell["row"], cell["col"])
    overlay_by_key[key] = {"kind": kind, "asset": asset}
    if guarded:
        overlay_by_key[key]["guarded"] = True
    if no_stack:
        overlay_by_key[key]["no_stack"] = True
    return True


def _remove_overlays_on_blocked_tiles(
    cells: List[Dict[str, Any]],
    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]],
) -> None:
    for cell in cells:
        if not _is_blocked_spawn_texture(cell):
            continue
        overlay_by_key.pop((cell["row"], cell["col"]), None)


def _maybe_stack_non_zone_landmarks(
    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]],
    rng: random.Random,
) -> None:
    for overlay in overlay_by_key.values():
        if overlay.get("kind") != "landmark":
            continue
        if overlay.get("no_stack"):
            continue
        asset = overlay.get("asset") or {}
        if str(asset.get("group") or "").strip().lower() == "zone":
            continue
        if rng.random() < NON_ZONE_LANDMARK_STACK_CHANCE:
            overlay["count"] = int(overlay.get("count", 1)) + 1


def _can_place_landmark(cell: Dict[str, Any], overlay_by_key: Dict[tuple[int, int], Dict[str, Any]]) -> bool:
    return _can_place_content(cell, overlay_by_key)


def _portal_assets_by_color(landmarks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for asset in landmarks:
        if asset["name_key"] in DISABLED_LANDMARK_KEYS:
            continue
        if asset["name_key"] == "portal" and asset.get("color"):
            out[str(asset["color"]).strip().lower()] = asset
    return out


def _pick_zone_asset(
    cell: Dict[str, Any],
    cell_lookup: Dict[tuple[int, int], Dict[str, Any]],
    landmarks: List[Dict[str, Any]],
    rng: random.Random,
) -> Dict[str, Any] | None:
    zone_assets = [
        a for a in landmarks
        if a["group"] == "zone" and a["name_key"] not in DISABLED_LANDMARK_KEYS and a["name_key"] != "shipwreck"
    ]
    if not zone_assets:
        return None

    adjacent_to_water = _is_adjacent_to_role(cell, cell_lookup, "water")
    ports = [a for a in zone_assets if a["name_key"] == "port"]
    non_ports = [a for a in zone_assets if a["name_key"] != "port"]

    if adjacent_to_water and ports and rng.random() < ZONE_PORT_CHANCE:
        return rng.choice(ports)

    return rng.choice(non_ports or zone_assets)


def _overlay_supports_guarded(overlay: Dict[str, Any]) -> bool:
    if not overlay.get("guarded"):
        return False
    kind = overlay.get("kind")
    asset = overlay.get("asset") or {}
    name_key = str(asset.get("name_key") or "").strip().lower()
    if kind == "landmark":
        return name_key in GUARDED_ELIGIBLE_LANDMARK_KEYS
    if kind == "entity":
        return name_key in GUARDED_ELIGIBLE_ENTITY_KEYS
    return False


def _build_texture_overrides(
    cells: List[Dict[str, Any]],
    cell_lookup: Dict[tuple[int, int], Dict[str, Any]],
    textures: List[Dict[str, Any]],
    rng: random.Random,
) -> Dict[tuple[int, int], Dict[str, Any]]:
    overrides: Dict[tuple[int, int], Dict[str, Any]] = {}
    neutral = [a for a in textures if a["biome"].lower() == "neutral"]
    mountains = [a for a in neutral if "mountain" in str(a.get("variant") or "").lower()]
    maelstroms = [a for a in neutral if "maelstrom" in str(a.get("variant") or "").lower()]
    lava = [a for a in neutral if "lava" in str(a.get("variant") or "").lower()]

    water_cells = [c for c in cells if c.get("active") and str(c.get("role") or "").lower() == "water"]
    if maelstroms and water_cells:
        target_count = max(0, int(round(len(water_cells) * CENTER_WATER_MAELSTROM_CHANCE)))
        shuffled_water = list(water_cells)
        rng.shuffle(shuffled_water)
        maelstrom_positions: List[tuple[int, int]] = []
        for cell in shuffled_water:
            if len(maelstrom_positions) >= target_count:
                break
            key = (cell["row"], cell["col"])
            if all(_hex_distance(key, other) >= MAELSTROM_MIN_DISTANCE for other in maelstrom_positions):
                overrides[key] = rng.choice(maelstroms)
                maelstrom_positions.append(key)

    biome_cells = [
        c for c in cells
        if c.get("active") and c.get("allow_biomes") and str(c.get("role") or "").lower() not in {"connector", "water", "center_core"}
    ]
    rng.shuffle(biome_cells)
    for cell in biome_cells:
        key = (cell["row"], cell["col"])
        if key in overrides:
            continue
        if _is_adjacent_to_role(cell, cell_lookup, "connector"):
            continue
        if rng.random() < MOUNTAIN_BASE_CHANCE and mountains:
            overrides[key] = rng.choice(mountains)
            candidates = []
            for nkey in _neighbor_keys(cell["row"], cell["col"]):
                neighbor = cell_lookup.get(nkey)
                if not neighbor:
                    continue
                nrole = str(neighbor.get("role") or "").lower()
                if not neighbor.get("active") or not neighbor.get("allow_biomes") or nrole in {"connector", "water"}:
                    continue
                if _is_adjacent_to_role(neighbor, cell_lookup, "connector"):
                    continue
                if nkey in overrides:
                    continue
                candidates.append(neighbor)
            if candidates and rng.random() < MOUNTAIN_ADJACENT_CHAIN_CHANCE:
                chained = rng.choice(candidates)
                overrides[(chained["row"], chained["col"])] = rng.choice(mountains)

    if lava:
        center_ring_cells = [c for c in cells if c.get("active") and str(c.get("role") or "").lower() == "center_ring"]
        center_core_cells = [c for c in cells if c.get("active") and str(c.get("role") or "").lower() == "center_core"]
        for cell in center_ring_cells:
            if rng.random() < CENTER_RING_LAVA_CHANCE:
                overrides[(cell["row"], cell["col"])] = rng.choice(lava)
        for cell in center_core_cells:
            special_lc = str(cell.get("special") or "").strip().lower()
            if "boss" in special_lc:
                continue
            if rng.random() < CENTER_CORE_LAVA_CHANCE:
                overrides[(cell["row"], cell["col"])] = rng.choice(lava)

    return overrides


def _enforce_lava_water_separation(
    cells: List[Dict[str, Any]],
    cell_lookup: Dict[tuple[int, int], Dict[str, Any]],
    textures: List[Dict[str, Any]],
) -> None:
    neutral = [a for a in textures if a["biome"].lower() == "neutral"]
    plains_assets = [a for a in neutral if "plains" in str(a.get("variant") or "").lower()]
    fallback_plain = plains_assets[0] if plains_assets else None
    if not fallback_plain:
        fallback_plain = next((a for a in neutral if "platform" in str(a.get("variant") or "").lower()), None)
    if not fallback_plain:
        return

    for cell in cells:
        final_texture = cell.get("_final_texture")
        if not final_texture:
            continue
        variant = str(final_texture.get("variant") or "").strip().lower()
        if variant != "lava":
            continue
        special_lc = str(cell.get("special") or "").strip().lower()
        if "boss" in special_lc or _is_adjacent_to_waterlike(cell, cell_lookup):
            cell["_final_texture"] = fallback_plain


def _pick_entity_asset(cell: Dict[str, Any], entities: List[Dict[str, Any]], rng: random.Random, special: str | None = None) -> Dict[str, Any] | None:
    if not entities:
        return None

    special_lc = (special or "").lower()
    special_entity_map = {
        "guardian": "guardian",
        "elite": "elite",
        "boss": "boss",
        "weakling": "weakling",
        "god": "god",
    }
    for token, name_key in special_entity_map.items():
        if token in special_lc:
            exact = _asset_by_name_key(entities, name_key)
            if exact:
                return exact
    if cell.get("spawn"):
        pool = [a for a in entities if a.get("npc", "").lower() == "hero" or a.get("hero")]
        return rng.choice(pool or entities)
    if cell.get("role") in {"core_area", "center_ring", "center_core"}:
        pool = [a for a in entities if any(h in a["label"].lower() or h in a.get("npc", "").lower() for h in CORE_ENTITY_HINTS)]
        return rng.choice(pool or entities)
    pool = [a for a in entities if any(h in a["label"].lower() or h in a.get("npc", "").lower() for h in OUTER_ENTITY_HINTS)]
    return rng.choice(pool or entities)


def _unique_spawn_hero_assets(entities: List[Dict[str, Any]], rng: random.Random) -> List[Dict[str, Any]]:
    hero_assets = [a for a in entities if a.get("npc", "").lower() == "hero" or a.get("hero")]
    unique_by_color: Dict[str, Dict[str, Any]] = {}
    for asset in hero_assets:
        color_key = (
            str(asset.get("hero") or "").strip().lower()
            or str(asset.get("label") or "").strip().lower()
            or str(asset.get("name_key") or "").strip().lower()
        )
        if not color_key or color_key in unique_by_color:
            continue
        unique_by_color[color_key] = asset
    pool = list(unique_by_color.values())
    rng.shuffle(pool)
    return pool


def _is_region_edge_cell(cell: Dict[str, Any], cell_lookup: Dict[tuple[int, int], Dict[str, Any]]) -> bool:
    region = str(cell.get("region") or "").strip().lower()
    if not region:
        return False
    same_region_neighbors = 0
    for nkey in _neighbor_keys(int(cell.get("row", 0)), int(cell.get("col", 0))):
        neighbor = cell_lookup.get(nkey)
        if not neighbor:
            continue
        if str(neighbor.get("role") or "").strip().lower() != "outer_area":
            continue
        if str(neighbor.get("region") or "").strip().lower() == region:
            same_region_neighbors += 1
    return same_region_neighbors < 6


def _min_distance_to_role(
    cell: Dict[str, Any],
    cells: List[Dict[str, Any]],
    role_name: str,
) -> int | None:
    role_name = str(role_name or "").strip().lower()
    distances = [
        _hex_distance((int(cell["row"]), int(cell["col"])), (int(other["row"]), int(other["col"])))
        for other in cells
        if str(other.get("role") or "").strip().lower() == role_name
    ]
    return min(distances) if distances else None


def _min_distance_to_spawn(cell: Dict[str, Any], spawn_cells: List[Dict[str, Any]]) -> int | None:
    if not spawn_cells:
        return None
    return min(
        _hex_distance((int(cell["row"]), int(cell["col"])), (int(other["row"]), int(other["col"])))
        for other in spawn_cells
    )


def _shuffled_cells(rng: random.Random, cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = list(cells)
    rng.shuffle(items)
    return items


def _place_first_matching(
    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]],
    cells: List[Dict[str, Any]],
    asset: Dict[str, Any] | None,
    kind: str,
    rng: random.Random,
    *,
    allow_forest: bool = False,
    guarded: bool = False,
    ignore_adjacent_rule: bool = False,
    no_stack: bool = False,
) -> Dict[str, Any] | None:
    for cell in _shuffled_cells(rng, cells):
        if _place_overlay(
            overlay_by_key,
            cell,
            kind,
            asset,
            allow_forest=allow_forest,
            guarded=guarded,
            ignore_adjacent_rule=ignore_adjacent_rule,
            no_stack=no_stack,
        ):
            return cell
    return None


def _convert_adjacent_hexes_to_forest(
    source_cell: Dict[str, Any],
    cells: List[Dict[str, Any]],
    cell_lookup: Dict[tuple[int, int], Dict[str, Any]],
    textures: List[Dict[str, Any]],
    rng: random.Random,
    count: int,
) -> None:
    region = str(source_cell.get("region") or "").strip()
    biome = str(source_cell.get("_resolved_biome") or "").strip()
    if not region or not biome:
        return

    biome_forest_assets = [
        a for a in textures
        if str(a.get("biome") or "").strip().lower() == biome.lower()
        and str(a.get("variant") or "").strip().lower() == "forest"
    ]
    if not biome_forest_assets:
        return

    candidates = []
    for nkey in _neighbor_keys(int(source_cell.get("row", 0)), int(source_cell.get("col", 0))):
        neighbor = cell_lookup.get(nkey)
        if not neighbor:
            continue
        if not neighbor.get("active"):
            continue
        if str(neighbor.get("region") or "").strip() != region:
            continue
        if str(neighbor.get("role") or "").strip().lower() != "outer_area":
            continue
        if _texture_variant_name(neighbor) == "lava":
            continue
        candidates.append(neighbor)

    for neighbor in _shuffled_cells(rng, candidates)[: max(0, int(count))]:
        neighbor["_final_texture"] = rng.choice(biome_forest_assets)


def _convert_cell_to_biome_variant(
    cell: Dict[str, Any],
    textures: List[Dict[str, Any]],
    rng: random.Random,
    variant_name: str,
) -> bool:
    biome = str(cell.get("_resolved_biome") or "").strip()
    wanted = str(variant_name or "").strip().lower()
    if not biome or not wanted:
        return False
    matching_assets = [
        a for a in textures
        if str(a.get("biome") or "").strip().lower() == biome.lower()
        and str(a.get("variant") or "").strip().lower() == wanted
    ]
    if not matching_assets:
        return False
    cell["_final_texture"] = rng.choice(matching_assets)
    return True


def _spawn_guard_matches_for_stacked_landmarks(
    cells: List[Dict[str, Any]],
    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]],
    entities: List[Dict[str, Any]],
    rng: random.Random,
) -> None:
    entity_by_key = {a["name_key"]: a for a in entities}
    for key, overlay in list(overlay_by_key.items()):
        if overlay.get("kind") != "landmark":
            continue
        count = int(overlay.get("count", 1))
        if count <= 1:
            continue
        asset = overlay.get("asset") or {}
        name_key = str(asset.get("name_key") or "").strip().lower()
        if name_key == "gold":
            guard_asset = entity_by_key.get("weakling")
        elif name_key in {"chest", "treasurechest", "legendarychest"}:
            guard_asset = entity_by_key.get("elite")
        else:
            continue

        source_cell = next((c for c in cells if (int(c["row"]), int(c["col"])) == key), None)
        if not source_cell:
            continue
        region = str(source_cell.get("region") or "").strip().lower()
        region_cells = [
            c for c in cells
            if str(c.get("region") or "").strip().lower() == region
            and str(c.get("role") or "").strip().lower() == "outer_area"
            and c.get("allow_entities")
        ]
        extra_needed = count - 1
        for _ in range(extra_needed):
            _place_first_matching(overlay_by_key, region_cells, guard_asset, "entity", rng)


def _generate_outer_area_content(
    cells: List[Dict[str, Any]],
    cell_lookup: Dict[tuple[int, int], Dict[str, Any]],
    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]],
    landmarks: List[Dict[str, Any]],
    entities: List[Dict[str, Any]],
    textures: List[Dict[str, Any]],
    rng: random.Random,
) -> None:
    landmark_by_key = {a["name_key"]: a for a in landmarks}
    entity_by_key = {a["name_key"]: a for a in entities}
    zone_assets = _zone_assets(landmarks)
    spawn_cells = [c for c in cells if c.get("active") and c.get("spawn")]

    forced_chest = landmark_by_key.get("chest")
    forced_gold = landmark_by_key.get("gold")
    forced_weakling = entity_by_key.get("weakling")

    # For each spawn, force a Chest, Gold, and Weakling nearby on distinct adjacent hexes.
    for spawn_cell in spawn_cells:
        adjacent_outer = []
        for nkey in _neighbor_keys(int(spawn_cell["row"]), int(spawn_cell["col"])):
            neighbor = cell_lookup.get(nkey)
            if not neighbor:
                continue
            if not neighbor.get("active") or str(neighbor.get("role") or "").strip().lower() != "outer_area":
                continue
            adjacent_outer.append(neighbor)
        trio_assets = [
            ("landmark", forced_chest),
            ("landmark", forced_gold),
            ("entity", forced_weakling),
        ]
        trio_cells = _shuffled_cells(rng, adjacent_outer)
        trio_idx = 0
        for kind, asset in trio_assets:
            placed = False
            while trio_idx < len(trio_cells):
                candidate = trio_cells[trio_idx]
                trio_idx += 1
                if _texture_variant_name(candidate) == "forest":
                    _convert_cell_to_biome_variant(candidate, textures, rng, "simple")
                if _place_overlay(
                    overlay_by_key,
                    candidate,
                    kind,
                    asset,
                    allow_forest=True,
                    ignore_adjacent_rule=True,
                    no_stack=True,
                ):
                    placed = True
                    break
            if not placed:
                break

    outer_regions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cell in cells:
        if not cell.get("active") or str(cell.get("role") or "").strip().lower() != "outer_area":
            continue
        region = str(cell.get("region") or "").strip()
        if not region or region.lower() in {"none", "water"}:
            continue
        outer_regions[region].append(cell)

    for region, region_cells in outer_regions.items():
        region_landmark_cells = [c for c in region_cells if c.get("allow_landmarks")]
        region_entity_cells = [c for c in region_cells if c.get("allow_entities")]
        if not region_landmark_cells and not region_entity_cells:
            continue

        unknown_target = max(1, len(region_landmark_cells) // OUTER_UNKNOWNSITE_DENSITY)
        weakling_target = max(1, len(region_entity_cells) // OUTER_WEAKLING_DENSITY) if region_entity_cells else 0
        chest_pair_target = max(0, len(region_landmark_cells) // OUTER_CHEST_PAIR_DENSITY)
        if len(region_landmark_cells) >= OUTER_LEGENDARY_MIN_HEXES:
            chest_pair_target = max(1, chest_pair_target)
        unknown_target = max(unknown_target, weakling_target + chest_pair_target + 1)

        # Unknown Sites should be the most abundant.
        unknown_asset = landmark_by_key.get("unknownsite")
        for _ in range(unknown_target):
            _place_first_matching(overlay_by_key, region_landmark_cells, unknown_asset, "landmark", rng)

        # One Questgiver if the region is large enough.
        if len(region_entity_cells) >= OUTER_QUESTGIVER_MIN_HEXES:
            _place_first_matching(overlay_by_key, region_entity_cells, entity_by_key.get("questgiver"), "entity", rng)

        # Any zone can appear on zone-marked cells in the region if a slot remains.
        zone_cells = [
            c for c in region_landmark_cells
            if "zone" in str(c.get("special") or "").strip().lower()
        ]
        if zone_assets and zone_cells:
            zone_asset = rng.choice(zone_assets)
            _place_first_matching(overlay_by_key, zone_cells, zone_asset, "landmark", rng)

        # One companion max, on a random valid outer hex at least 2 away from spawn.
        if len(region_entity_cells) >= OUTER_COMPANION_MIN_HEXES:
            companion_cells = [
                c for c in region_entity_cells
                if (_min_distance_to_spawn(c, spawn_cells) or 999) >= OUTER_COMPANION_SPAWN_DISTANCE
            ]
            _place_first_matching(overlay_by_key, companion_cells, entity_by_key.get("companion"), "entity", rng)

        # Gold and Weaklings should match.
        gold_asset = landmark_by_key.get("gold")
        weakling_asset = entity_by_key.get("weakling")
        for _ in range(weakling_target):
            _place_first_matching(overlay_by_key, region_landmark_cells, gold_asset, "landmark", rng)
            _place_first_matching(overlay_by_key, region_entity_cells, weakling_asset, "entity", rng)

        # Chest/TreasureChest/LegendaryChest should match Elite count conceptually.
        chest_assets = [a for a in (landmark_by_key.get("chest"), landmark_by_key.get("treasurechest")) if a]
        legendary_asset = landmark_by_key.get("legendarychest")
        elite_asset = entity_by_key.get("elite")
        legendary_used = False
        for idx in range(chest_pair_target):
            chest_cell_pool = list(region_landmark_cells)
            chosen_asset: Dict[str, Any] | None = None
            if (
                not legendary_used
                and legendary_asset
                and len(region_landmark_cells) >= OUTER_LEGENDARY_MIN_HEXES
            ):
                legendary_candidates = [
                    c for c in region_landmark_cells
                    if (_min_distance_to_spawn(c, spawn_cells) or 999) >= OUTER_LEGENDARY_SPAWN_DISTANCE
                ]
                if legendary_candidates:
                    chosen_asset = legendary_asset
                    chest_cell_pool = legendary_candidates
                    legendary_used = True
            if not chosen_asset:
                if not chest_assets:
                    break
                chosen_asset = rng.choice(chest_assets)

            guarded = rng.random() < 0.5
            placed_cell = _place_first_matching(
                overlay_by_key,
                chest_cell_pool,
                chosen_asset,
                "landmark",
                rng,
                guarded=guarded,
            )
            if not placed_cell:
                continue
            if chosen_asset and str(chosen_asset.get("name_key") or "").strip().lower() == "legendarychest":
                _convert_adjacent_hexes_to_forest(placed_cell, cells, cell_lookup, textures, rng, 3)
            if not guarded:
                _place_first_matching(overlay_by_key, region_entity_cells, elite_asset, "entity", rng)


def _build_preview_map(payload: Dict[str, Any], seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    textures = _load_texture_assets()
    landmarks = _load_landmark_assets()
    entities = _load_entity_assets()
    addons = _load_addon_assets()

    texture_biomes = sorted(
        {
            a["biome"]
            for a in textures
            if a["biome"].lower() != "neutral" and a["biome"].strip().lower() not in DISABLED_BIOMES
        }
    )
    cells = [dict(c) for c in payload.get("cells", [])]
    cell_lookup = {(c["row"], c["col"]): c for c in cells}
    region_biomes: Dict[str, str] = {}
    by_region_roles: Dict[str, str] = {}
    for cell in cells:
        if not cell.get("active") or not cell.get("allow_biomes"):
            continue
        if str(cell.get("role") or "").strip().lower() == "center_core":
            continue
        region = str(cell.get("region") or "").strip()
        if not region:
            continue
        by_region_roles.setdefault(region, cell.get("role") or "outer_area")
    for region, role in by_region_roles.items():
        chosen = _pick_role_biome(role, texture_biomes, rng)
        if chosen:
            region_biomes[region] = chosen
    biome_variant_plan = _build_biome_variant_plan(cells, region_biomes, textures, rng)
    center_core_plan = _build_center_core_plan(cells, textures, rng)
    texture_overrides = _build_texture_overrides(cells, cell_lookup, textures, rng)
    for cell in cells:
        cell["_resolved_biome"] = region_biomes.get(cell.get("region") or "")
        cell["_texture_override"] = texture_overrides.get((cell["row"], cell["col"]))
        cell["_final_texture"] = (
            cell["_texture_override"]
            or center_core_plan.get((cell["row"], cell["col"]))
            or biome_variant_plan.get((cell["row"], cell["col"]))
        )
    _enforce_lava_water_separation(cells, cell_lookup, textures)

    overlay_by_key: Dict[tuple[int, int], Dict[str, Any]] = {}
    portal_assets = _portal_assets_by_color(landmarks)
    shipwreck_assets = [a for a in landmarks if a["name_key"] == "shipwreck"]

    spawn_cells = [c for c in cells if c.get("active") and c.get("spawn")]
    available_spawn_heroes = _unique_spawn_hero_assets(entities, rng)
    for cell in spawn_cells:
        if not available_spawn_heroes:
            continue
        asset = available_spawn_heroes.pop(0)
        _place_overlay(overlay_by_key, cell, "entity", asset)

    special_entity_cells = [
        c for c in cells
        if c.get("active")
        and (
            (c.get("special") or "").lower().find("boss") >= 0
            or (c.get("special") or "").lower().find("elite") >= 0
            or (c.get("special") or "").lower().find("guardian") >= 0
            or (c.get("special") or "").lower().find("weakling") >= 0
            or (c.get("special") or "").lower().find("god") >= 0
        )
    ]
    for cell in special_entity_cells:
        asset = _pick_entity_asset(cell, entities, rng, special=str(cell.get("special") or ""))
        _place_overlay(overlay_by_key, cell, "entity", asset, ignore_adjacent_rule=True)

    _generate_outer_area_content(cells, cell_lookup, overlay_by_key, landmarks, entities, textures, rng)

    zone_regions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cell in cells:
        if not cell.get("active") or not cell.get("allow_landmarks"):
            continue
        if str(cell.get("role") or "").strip().lower() == "outer_area":
            continue
        region = str(cell.get("region") or "").strip()
        special = str(cell.get("special") or "").strip().lower()
        if region and region.lower() not in {"none", "water"} and "zone" in special:
            zone_regions[region].append(cell)

    for region, region_cells in zone_regions.items():
        shuffled_zone_cells = list(region_cells)
        rng.shuffle(shuffled_zone_cells)
        placed = 0
        for cell in shuffled_zone_cells:
            if placed >= ZONES_PER_REGION:
                break
            ignore_adjacent_rule = bool(str(cell.get("special") or "").strip())
            if not ignore_adjacent_rule and not _can_place_landmark(cell, overlay_by_key):
                continue
            zone_asset = _pick_zone_asset(cell, cell_lookup, landmarks, rng)
            if _place_overlay(overlay_by_key, cell, "landmark", zone_asset, ignore_adjacent_rule=ignore_adjacent_rule):
                placed += 1

    outer_landmark_candidates = [c for c in cells if c.get("active") and c.get("allow_landmarks") and c.get("role") == "connector" and (c["row"], c["col"]) not in overlay_by_key]
    core_landmark_candidates = [c for c in cells if c.get("active") and c.get("allow_landmarks") and c.get("role") in {"core_area", "center_ring", "center_core"} and (c["row"], c["col"]) not in overlay_by_key]
    outer_entity_candidates = [
        c for c in cells
        if c.get("active")
        and c.get("allow_entities")
        and c.get("role") == "connector"
        and (c["row"], c["col"]) not in overlay_by_key
        and not (
            c.get("_final_texture")
            and str(c["_final_texture"].get("variant") or "").strip().lower() in {"lava", "forest"}
        )
    ]
    core_entity_candidates = [
        c for c in cells
        if c.get("active")
        and c.get("allow_entities")
        and c.get("role") in {"core_area", "center_ring"}
        and (c["row"], c["col"]) not in overlay_by_key
        and not (
            c.get("_final_texture")
            and str(c["_final_texture"].get("variant") or "").strip().lower() in {"lava", "forest"}
        )
    ]
    water_landmark_candidates = [c for c in cells if c.get("active") and c.get("role") == "water" and (c["row"], c["col"]) not in overlay_by_key]

    outer_landmark_count = min(len(outer_landmark_candidates), max(0, int(round(len(outer_landmark_candidates) * 0.08))))
    core_landmark_count = min(len(core_landmark_candidates), max(1 if core_landmark_candidates else 0, int(round(len(core_landmark_candidates) * 0.14))))
    outer_entity_count = min(len(outer_entity_candidates), max(0, int(round(len(outer_entity_candidates) * 0.10))))
    core_entity_count = min(len(core_entity_candidates), max(0, int(round(len(core_entity_candidates) * 0.16))))

    # Portals are only generated as a same-color pair.
    if len(core_landmark_candidates) >= 2 and portal_assets and rng.random() < 0.45:
        portal_color = rng.choice(sorted(portal_assets.keys()))
        portal_asset = portal_assets[portal_color]
        candidates_by_region: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for cell in core_landmark_candidates:
            region = str(cell.get("region") or "").strip().lower()
            if not region or region in {"none", "water"}:
                continue
            candidates_by_region[region].append(cell)

        eligible_regions = [region for region, items in candidates_by_region.items() if len(items) >= 2]
        portal_cells: List[Dict[str, Any]] = []
        if eligible_regions:
            portal_region = rng.choice(eligible_regions)
            shuffled_core = list(candidates_by_region[portal_region])
            rng.shuffle(shuffled_core)
            for cell in shuffled_core:
                if not _can_place_landmark(cell, overlay_by_key):
                    continue
                if any((cell["row"], cell["col"]) in _neighbor_keys(pc["row"], pc["col"]) for pc in portal_cells):
                    continue
                portal_cells.append(cell)
                if len(portal_cells) == 2:
                    break
        for cell in portal_cells:
            _place_overlay(overlay_by_key, cell, "landmark", portal_asset)
        core_landmark_candidates = [c for c in core_landmark_candidates if (c["row"], c["col"]) not in overlay_by_key]
        outer_landmark_candidates = [c for c in outer_landmark_candidates if (c["row"], c["col"]) not in overlay_by_key]

    # Shipwrecks are allowed only on water.
    # Base chance is 27% per eligible water hex.
    if shipwreck_assets and water_landmark_candidates:
        water_cells = list(water_landmark_candidates)
        rng.shuffle(water_cells)
        for cell in water_cells:
            if not _can_place_landmark(cell, overlay_by_key):
                continue
            if rng.random() < 0.27:
                shipwreck_asset = rng.choice(shipwreck_assets)
                _place_overlay(overlay_by_key, cell, "landmark", shipwreck_asset)

    shuffled_outer_landmarks = list(outer_landmark_candidates)
    rng.shuffle(shuffled_outer_landmarks)
    placed_outer_landmarks = 0
    for cell in shuffled_outer_landmarks:
        if placed_outer_landmarks >= outer_landmark_count:
            break
        if not _can_place_landmark(cell, overlay_by_key):
            continue
        asset = _pick_landmark_asset(cell, landmarks, rng)
        if _place_overlay(overlay_by_key, cell, "landmark", asset):
            placed_outer_landmarks += 1

    shuffled_core_landmarks = list(core_landmark_candidates)
    rng.shuffle(shuffled_core_landmarks)
    placed_core_landmarks = 0
    for cell in shuffled_core_landmarks:
        if placed_core_landmarks >= core_landmark_count:
            break
        if not _can_place_landmark(cell, overlay_by_key):
            continue
        asset = _pick_landmark_asset(cell, landmarks, rng)
        if _place_overlay(overlay_by_key, cell, "landmark", asset):
            placed_core_landmarks += 1

    outer_entity_candidates = [c for c in outer_entity_candidates if (c["row"], c["col"]) not in overlay_by_key]
    core_entity_candidates = [c for c in core_entity_candidates if (c["row"], c["col"]) not in overlay_by_key]
    outer_entity_count = min(len(outer_entity_candidates), outer_entity_count)
    core_entity_count = min(len(core_entity_candidates), core_entity_count)

    for cell in rng.sample(outer_entity_candidates, outer_entity_count) if outer_entity_count else []:
        asset = _pick_entity_asset(cell, entities, rng)
        _place_overlay(overlay_by_key, cell, "entity", asset)
    for cell in rng.sample(core_entity_candidates, core_entity_count) if core_entity_count else []:
        asset = _pick_entity_asset(cell, entities, rng)
        _place_overlay(overlay_by_key, cell, "entity", asset)

    _remove_overlays_on_blocked_tiles(cells, overlay_by_key)
    _maybe_stack_non_zone_landmarks(overlay_by_key, rng)
    _spawn_guard_matches_for_stacked_landmarks(cells, overlay_by_key, entities, rng)

    rows: List[List[Dict[str, Any]]] = []
    summary = defaultdict(int)
    for row in range(int(payload.get("height", 0))):
        row_cells: List[Dict[str, Any]] = []
        for col in range(int(payload.get("width", 0))):
            cell = cell_lookup.get((row, col))
            if cell is None:
                cell = {
                    "row": row,
                    "col": col,
                    "active": False,
                    "role": "empty",
                    "region": "",
                    "spawn": False,
                    "special": None,
                }
            texture = cell.get("_final_texture") or texture_overrides.get((row, col))
            if texture is None:
                texture = _pick_texture_for_cell(cell, cell_lookup, region_biomes, textures, biome_variant_plan, rng)
            overlay = overlay_by_key.get((row, col))
            addon = None
            addon_url = None
            if overlay and "guarded" in addons and _overlay_supports_guarded(overlay):
                addon = addons["guarded"]
                addon_url = url_for("static", filename=f"mapgen/addons/{addon['file_name']}")

            if texture:
                summary[f"texture:{texture['biome']}"] += 1
            if overlay:
                summary[f"{overlay['kind']}:{overlay['asset']['label']}"] += int(overlay.get("count", 1))

            texture_url = url_for("static", filename=f"mapgen/textures/{texture['file_name']}") if texture else None
            overlay_url = None
            if overlay:
                folder = "entities" if overlay["kind"] == "entity" else "landmarks"
                overlay_url = url_for("static", filename=f"mapgen/{folder}/{overlay['asset']['file_name']}")

            row_cells.append(
                {
                    "row": row,
                    "col": col,
                    "active": bool(cell.get("active")),
                    "role": cell.get("role") or "empty",
                    "region": cell.get("region") or "",
                    "spawn": bool(cell.get("spawn")),
                    "special": cell.get("special"),
                    "biome": region_biomes.get(cell.get("region") or ""),
                    "texture": texture,
                    "texture_url": texture_url,
                    "overlay": overlay,
                    "overlay_count": int(overlay.get("count", 1)) if overlay else 0,
                    "overlay_url": overlay_url,
                    "addon": addon,
                    "addon_url": addon_url,
                    "role_color": ROLE_COLORS.get(cell.get("role") or "empty", ROLE_COLORS["empty"]),
                }
            )
        rows.append(row_cells)

    return {
        "seed": seed,
        "rows": rows,
        "region_biomes": region_biomes,
        "summary": dict(sorted(summary.items())),
        "asset_counts": {
            "textures": len(textures),
            "landmarks": len(landmarks),
            "entities": len(entities),
            "addons": len(addons),
        },
    }


def _login_required_local(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def _safe_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unnamed_map"


def _skeleton_dir(app) -> Path:
    p = _map_storage_root(app) / "map_skeletons"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _detail_map_dir(app) -> Path:
    p = _map_storage_root(app) / "map_detail_edits"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _legacy_skeleton_dir(app) -> Path:
    return Path(app.root_path) / "data" / "map_skeletons"


def _legacy_detail_map_dir(app) -> Path:
    return Path(app.root_path) / "data" / "map_detail_edits"


def _map_storage_root(app) -> Path:
    explicit_root = (os.getenv("MAPGEN_DATA_ROOT") or "").strip()
    if explicit_root:
        root = Path(explicit_root)
    else:
        configured_base = (
            os.getenv("PERSISTENT_DATA_DIR")
            or os.getenv("DATA_DIR")
            or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
            or ""
        ).strip()
        if configured_base:
            root = Path(configured_base) / "perfection"
        else:
        # Common mounted-volume paths on Linux hosts. Falls back to repo-local data for local dev.
            railway_volume = Path("/app/var")
            linux_volume = Path("/data")
            if os.name != "nt" and railway_volume.exists() and railway_volume.is_dir():
                root = railway_volume / "perfection"
            elif os.name != "nt" and linux_volume.exists() and linux_volume.is_dir():
                root = linux_volume / "perfection"
            else:
                root = Path(app.root_path) / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _blank_skeleton(name: str, width: int, height: int) -> Dict[str, Any]:
    width = max(3, min(int(width), 80))
    height = max(3, min(int(height), 80))
    cells: List[Dict[str, Any]] = []
    for row in range(height):
        for col in range(width):
            d = ROLE_DEFAULTS["empty"].copy()
            cells.append(
                {
                    "row": row,
                    "col": col,
                    "active": d["active"],
                    "role": "empty",
                    "region": "",
                    "spawn": d["spawn"],
                    "special": d["special"],
                    "allow_biomes": d["allow_biomes"],
                    "allow_landmarks": d["allow_landmarks"],
                    "allow_entities": d["allow_entities"],
                }
            )
    return {
        "name": name,
        "description": "",
        "width": width,
        "height": height,
        "cells": cells,
    }


def _normalize_role(role: str) -> str:
    role = str(role or "empty").strip()
    if role == "void":
        role = "empty"
    if role not in ROLE_DEFAULTS:
        role = "empty"
    return role


def _normalize_payload(payload: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
    width = max(1, min(int(payload.get("width", 1)), 120))
    height = max(1, min(int(payload.get("height", 1)), 120))
    name = _safe_name(payload.get("name") or fallback_name)
    description = str(payload.get("description") or "")[:500]

    by_key: Dict[tuple[int, int], Dict[str, Any]] = {}
    for raw in payload.get("cells", []):
        try:
            row = int(raw.get("row", 0))
            col = int(raw.get("col", 0))
        except Exception:
            continue
        if row < 0 or col < 0 or row >= height or col >= width:
            continue
        role = _normalize_role(raw.get("role") or "empty")
        defaults = ROLE_DEFAULTS[role]
        region_value = str(raw.get("region") or "")[:80]
        if role == "connector":
            region_value = ""
        by_key[(row, col)] = {
            "row": row,
            "col": col,
            "active": bool(raw.get("active", defaults["active"])),
            "role": role,
            "region": region_value,
            "spawn": bool(raw.get("spawn", defaults["spawn"])),
            "special": (str(raw.get("special")).strip()[:120] if raw.get("special") not in (None, "", "null") else None),
            "allow_biomes": bool(raw.get("allow_biomes", defaults["allow_biomes"])),
            "allow_landmarks": bool(raw.get("allow_landmarks", defaults["allow_landmarks"])),
            "allow_entities": bool(raw.get("allow_entities", defaults["allow_entities"])),
        }

    cells: List[Dict[str, Any]] = []
    for row in range(height):
        for col in range(width):
            if (row, col) in by_key:
                cells.append(by_key[(row, col)])
            else:
                defaults = ROLE_DEFAULTS["empty"]
                cells.append(
                    {
                        "row": row,
                        "col": col,
                        "active": defaults["active"],
                        "role": "empty",
                        "region": "",
                        "spawn": defaults["spawn"],
                        "special": defaults["special"],
                        "allow_biomes": defaults["allow_biomes"],
                        "allow_landmarks": defaults["allow_landmarks"],
                        "allow_entities": defaults["allow_entities"],
                    }
                )

    return {
        "name": name,
        "description": description,
        "width": width,
        "height": height,
        "cells": cells,
    }


def _detail_map_file_name(skeleton_name: str, seed: int) -> str:
    return f"{_safe_name(skeleton_name)}__seed_{int(seed)}.json"


def _build_detail_editor_payload(
    skeleton_payload: Dict[str, Any],
    preview: Dict[str, Any],
) -> Dict[str, Any]:
    rows = preview.get("rows") or []
    cells: List[Dict[str, Any]] = []
    for row in rows:
        for cell in row:
            texture = cell.get("texture") or {}
            overlay = cell.get("overlay") or {}
            asset = overlay.get("asset") or {}
            hero_file_name = None
            hero_name_key = None
            hero_label = None
            hero_count = 0
            hero_pathfinder = False
            if (overlay.get("kind") == "entity") and _is_hero_entity_asset_data(asset):
                hero_file_name = asset.get("file_name")
                hero_name_key = asset.get("name_key")
                hero_label = asset.get("label")
                hero_count = 1
                overlay = {}
                asset = {}
            cells.append(
                {
                    "row": int(cell.get("row", 0)),
                    "col": int(cell.get("col", 0)),
                    "active": bool(cell.get("active")),
                    "role": cell.get("role") or "empty",
                    "role_color": cell.get("role_color") or ROLE_COLORS.get(cell.get("role") or "empty", ROLE_COLORS["empty"]),
                    "region": cell.get("region") or "",
                    "spawn": bool(cell.get("spawn")),
                    "special": cell.get("special"),
                    "biome": cell.get("biome") or "",
                    "texture_file_name": texture.get("file_name"),
                    "overlay_kind": overlay.get("kind"),
                    "overlay_file_name": asset.get("file_name"),
                    "overlay_name_key": asset.get("name_key"),
                    "overlay_label": asset.get("label"),
                    "overlay_group": asset.get("group"),
                    "overlay_owner_color": None,
                    "overlay_pathfinder": False,
                    "overlay_count": int(cell.get("overlay_count") or 0),
                    "guarded": bool((overlay or {}).get("guarded")),
                    "hero_file_name": hero_file_name,
                    "hero_name_key": hero_name_key,
                    "hero_label": hero_label,
                    "hero_count": hero_count,
                    "hero_owner_color": None,
                    "hero_pathfinder": hero_pathfinder,
                }
            )
    return {
        "name": skeleton_payload.get("name") or "unnamed_map",
        "description": skeleton_payload.get("description") or "",
        "save_label": "",
        "seed": int(preview.get("seed") or 0),
        "width": int(skeleton_payload.get("width") or 0),
        "height": int(skeleton_payload.get("height") or 0),
        "region_biomes": dict(preview.get("region_biomes") or {}),
        "cells": cells,
    }


def _normalize_detail_map_payload(payload: Dict[str, Any], fallback_name: str, fallback_seed: int) -> Dict[str, Any]:
    width = max(1, min(int(payload.get("width", 1)), 120))
    height = max(1, min(int(payload.get("height", 1)), 120))
    seed = int(payload.get("seed", fallback_seed))
    name = _safe_name(payload.get("name") or fallback_name)
    description = str(payload.get("description") or "")[:500]
    save_label = str(payload.get("save_label") or "").strip()[:120]
    region_biomes = {str(k): str(v) for k, v in (payload.get("region_biomes") or {}).items()}

    by_key: Dict[tuple[int, int], Dict[str, Any]] = {}
    for raw in payload.get("cells", []):
        cell = _normalize_detail_map_cell(raw, width, height)
        if not cell:
            continue
        by_key[(cell["row"], cell["col"])] = cell

    cells: List[Dict[str, Any]] = []
    for row in range(height):
        for col in range(width):
            if (row, col) in by_key:
                cells.append(by_key[(row, col)])
            else:
                defaults = ROLE_DEFAULTS["empty"]
                cells.append(
                    {
                        "row": row,
                        "col": col,
                        "active": defaults["active"],
                        "role": "empty",
                        "role_color": ROLE_COLORS["empty"],
                        "region": "",
                        "spawn": defaults["spawn"],
                        "special": defaults["special"],
                        "biome": "",
                        "texture_file_name": None,
                        "overlay_kind": None,
                        "overlay_file_name": None,
                        "overlay_name_key": None,
                        "overlay_label": None,
                        "overlay_group": None,
                        "overlay_owner_color": None,
                        "overlay_pathfinder": False,
                        "overlay_count": 0,
                        "guarded": False,
                        "hero_file_name": None,
                        "hero_name_key": None,
                        "hero_label": None,
                        "hero_count": 0,
                        "hero_owner_color": None,
                        "hero_pathfinder": False,
                    }
                )

    return {
        "name": name,
        "description": description,
        "save_label": save_label,
        "seed": seed,
        "width": width,
        "height": height,
        "region_biomes": region_biomes,
        "cells": cells,
    }


def _is_hero_entity_asset_data(asset: Dict[str, Any] | None) -> bool:
    if not asset:
        return False
    npc = str(asset.get("npc") or "").strip().lower()
    file_name = str(asset.get("file_name") or "").strip().lower()
    return npc == "hero" or file_name.startswith("npc=hero")


def _is_boat_landmark_detail_data(
    overlay_kind: str | None,
    overlay_name_key: str | None,
    overlay_label: str | None,
    overlay_file_name: str | None,
) -> bool:
    if str(overlay_kind or "").strip().lower() != "landmark":
        return False
    name_key = str(overlay_name_key or "").strip().lower()
    label = str(overlay_label or "").strip().lower()
    file_name = str(overlay_file_name or "").strip().lower()
    return name_key == "boat" or label == "boat" or file_name.startswith("landmark=boat")


def _repair_detail_map_spawn_heroes(detail_payload: Dict[str, Any], entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    cells = detail_payload.get("cells") or []
    hero_assets = [a for a in entities if _is_hero_entity_asset_data(a)]
    if not cells or not hero_assets:
        return detail_payload

    by_file = {str(a.get("file_name") or ""): a for a in hero_assets}
    available = _unique_spawn_hero_assets(hero_assets, random.Random(int(detail_payload.get("seed") or 0)))
    used_files = {
        str(cell.get("hero_file_name") or "")
        for cell in cells
        if str(cell.get("hero_file_name") or "") in by_file
    }
    available = [asset for asset in available if str(asset.get("file_name") or "") not in used_files]

    for cell in cells:
        if not cell.get("spawn"):
            continue
        hero_file_name = str(cell.get("hero_file_name") or "")
        if hero_file_name and hero_file_name in by_file:
            asset = by_file[hero_file_name]
            cell["hero_name_key"] = asset.get("name_key")
            cell["hero_label"] = asset.get("label")
            continue
        if not available:
            cell["hero_file_name"] = None
            cell["hero_name_key"] = None
            cell["hero_label"] = None
            cell["hero_count"] = 0
            cell["hero_owner_color"] = None
            cell["hero_pathfinder"] = False
            continue
        asset = available.pop(0)
        cell["hero_file_name"] = asset.get("file_name")
        cell["hero_name_key"] = asset.get("name_key")
        cell["hero_label"] = asset.get("label")
        cell["hero_count"] = max(1, int(cell.get("hero_count") or 1))
        cell["hero_owner_color"] = cell.get("hero_owner_color") or None
        cell["hero_pathfinder"] = bool(cell.get("hero_pathfinder", False))

    return detail_payload


def _normalize_detail_map_cell(raw: Dict[str, Any], width: int, height: int) -> Dict[str, Any] | None:
    try:
        row = int(raw.get("row", 0))
        col = int(raw.get("col", 0))
    except Exception:
        return None
    if row < 0 or col < 0 or row >= height or col >= width:
        return None
    role = _normalize_role(raw.get("role") or "empty")
    defaults = ROLE_DEFAULTS[role]
    overlay_kind = (str(raw.get("overlay_kind") or "").strip().lower() or None)
    overlay_file_name = str(raw.get("overlay_file_name") or "") or None
    overlay_name_key = str(raw.get("overlay_name_key") or "") or None
    overlay_label = str(raw.get("overlay_label") or "") or None
    overlay_group = str(raw.get("overlay_group") or "") or None
    overlay_owner_color = str(raw.get("overlay_owner_color") or "") or None
    overlay_pathfinder = bool(raw.get("overlay_pathfinder", False))
    hero_file_name = str(raw.get("hero_file_name") or "") or None
    hero_name_key = str(raw.get("hero_name_key") or "") or None
    hero_label = str(raw.get("hero_label") or "") or None
    hero_count = max(0, min(int(raw.get("hero_count", 0) or 0), 99))
    hero_owner_color = str(raw.get("hero_owner_color") or "") or None
    hero_pathfinder = bool(raw.get("hero_pathfinder", False))

    if not hero_file_name and overlay_kind == "entity" and overlay_file_name and overlay_file_name.lower().startswith("npc=hero"):
        hero_file_name = overlay_file_name
        hero_name_key = overlay_name_key
        hero_label = overlay_label
        hero_count = max(hero_count, 1)
        hero_pathfinder = bool(raw.get("hero_pathfinder", False))
        overlay_kind = None
        overlay_file_name = None
        overlay_name_key = None
        overlay_label = None
        overlay_group = None

    return {
        "row": row,
        "col": col,
        "active": bool(raw.get("active", defaults["active"])),
        "role": role,
        "role_color": str(raw.get("role_color") or ROLE_COLORS.get(role, ROLE_COLORS["empty"])),
        "region": "" if role == "connector" else str(raw.get("region") or "")[:80],
        "spawn": bool(raw.get("spawn", defaults["spawn"])),
        "special": (str(raw.get("special")).strip()[:120] if raw.get("special") not in (None, "", "null") else None),
        "biome": str(raw.get("biome") or "")[:80],
        "texture_file_name": str(raw.get("texture_file_name") or "") or None,
        "overlay_kind": overlay_kind,
        "overlay_file_name": overlay_file_name,
        "overlay_name_key": overlay_name_key,
        "overlay_label": overlay_label,
        "overlay_group": overlay_group,
        "overlay_owner_color": (
            overlay_owner_color
            if (
                overlay_kind == "entity"
                or _is_boat_landmark_detail_data(overlay_kind, overlay_name_key, overlay_label, overlay_file_name)
            )
            else None
        ),
        "overlay_pathfinder": (
            overlay_pathfinder
            if (
                overlay_kind == "entity"
                or _is_boat_landmark_detail_data(overlay_kind, overlay_name_key, overlay_label, overlay_file_name)
            )
            else False
        ),
        "overlay_count": max(0, min(int(raw.get("overlay_count", 0) or 0), 99)),
        "guarded": bool(raw.get("guarded", False)),
        "hero_file_name": hero_file_name,
        "hero_name_key": hero_name_key,
        "hero_label": hero_label,
        "hero_count": hero_count if hero_file_name else 0,
        "hero_owner_color": hero_owner_color if hero_file_name else None,
        "hero_pathfinder": hero_pathfinder if hero_file_name else False,
    }


def init_map_skeletons(app, socketio=None):
    data_dir = _skeleton_dir(app)
    detail_dir = _detail_map_dir(app)
    legacy_data_dir = _legacy_skeleton_dir(app)
    legacy_detail_dir = _legacy_detail_map_dir(app)
    db_path = app.config.get("AUTH_DB_PATH") or os.getenv("AUTH_DB_PATH") or str(Path(app.root_path) / "data" / "auth.db")
    _admin_required = getattr(app, "admin_required", _login_required_local)
    detail_room_states: Dict[str, Dict[str, Any]] = {}
    detail_room_presence: Dict[str, Dict[str, Dict[str, Any]]] = {}
    detail_sid_rooms: Dict[str, Dict[str, Any]] = {}
    redis_url = os.getenv("MAPGEN_REDIS_URL") or os.getenv("REDIS_URL") or ""
    redis_client = None
    if redis_url and redis_lib is not None:
        try:
            redis_client = redis_lib.from_url(redis_url, decode_responses=True)
            redis_client.ping()
        except Exception:
            redis_client = None

    def _db_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_map_tables() -> None:
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS map_skeletons (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS map_detail_edits (
                    skeleton_name TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (skeleton_name, seed)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    _ensure_map_tables()

    def _detail_room_name(skeleton_name: str, seed: int) -> str:
        return f"detail:{_safe_name(skeleton_name)}:{int(seed)}"

    def _detail_state_key(skeleton_name: str, seed: int) -> str:
        return f"mapgen:detail:state:{_safe_name(skeleton_name)}:{int(seed)}"

    def _detail_presence_key(skeleton_name: str, seed: int) -> str:
        return f"mapgen:detail:presence:{_safe_name(skeleton_name)}:{int(seed)}"

    def _detail_editor_user_label() -> str:
        return (
            (session.get("username") or "").strip()
            or (session.get("current_user_name") or "").strip()
            or (session.get("email") or "").strip()
            or "Anonymous"
        )[:80]

    def _detail_room_editor_names(room: str) -> list[str]:
        cutoff = time.time() - 90
        names = []
        seen = set()
        room_presence = detail_room_presence.get(room, {})
        for sid, meta in list(room_presence.items()):
            last_seen = float(meta.get("ts") or 0)
            if last_seen < cutoff:
                room_presence.pop(sid, None)
                continue
            name = str(meta.get("name") or "").strip() or "Anonymous"
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
        return sorted(names, key=str.lower)

    def _path_for(name: str) -> Path:
        return data_dir / f"{_safe_name(name)}.json"

    def _legacy_path_for(name: str) -> Path:
        return legacy_data_dir / f"{_safe_name(name)}.json"

    def _read_json(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _load_skeleton_from_db(name: str) -> Dict[str, Any] | None:
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT payload FROM map_skeletons WHERE name = ?", (_safe_name(name),))
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return _normalize_payload(json.loads(row["payload"]), _safe_name(name))
        except Exception:
            return None

    def _save_skeleton_to_db(payload: Dict[str, Any], name_hint: str) -> Dict[str, Any]:
        normalized = _normalize_payload(payload, name_hint)
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO map_skeletons (name, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized["name"],
                    json.dumps(normalized),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return normalized

    def _load_detail_from_db(skeleton_name: str, seed: int) -> Dict[str, Any] | None:
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT payload FROM map_detail_edits WHERE skeleton_name = ? AND seed = ?",
                (_safe_name(skeleton_name), int(seed)),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return _normalize_detail_map_payload(json.loads(row["payload"]), skeleton_name, seed)
        except Exception:
            return None

    def _save_detail_to_db(payload: Dict[str, Any], skeleton_name: str, seed: int) -> Dict[str, Any]:
        normalized = _normalize_detail_map_payload(payload, skeleton_name, seed)
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO map_detail_edits (skeleton_name, seed, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(skeleton_name, seed) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized["name"],
                    int(normalized["seed"]),
                    json.dumps(normalized),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return normalized

    def _load(name: str) -> Dict[str, Any]:
        from_db = _load_skeleton_from_db(name)
        if from_db is not None:
            return from_db
        p = _path_for(name)
        if p.exists():
            payload = _read_json(p)
            normalized = _normalize_payload(payload, _safe_name(name))
            _save_skeleton_to_db(normalized, normalized["name"])
            return normalized
        legacy = _legacy_path_for(name)
        if not legacy.exists():
            raise FileNotFoundError(name)
        payload = _read_json(legacy)
        normalized = _normalize_payload(payload, _safe_name(name))
        _save_skeleton_to_db(normalized, normalized["name"])
        return normalized

    def _save(payload: Dict[str, Any], name_hint: str) -> Path:
        normalized = _save_skeleton_to_db(payload, name_hint)
        p = _path_for(normalized["name"])
        tmp = p.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2)
        tmp.replace(p)
        return p

    def _detail_path_for(skeleton_name: str, seed: int) -> Path:
        return detail_dir / _detail_map_file_name(skeleton_name, seed)

    def _legacy_detail_path_for(skeleton_name: str, seed: int) -> Path:
        return legacy_detail_dir / _detail_map_file_name(skeleton_name, seed)

    def _save_detail_map(payload: Dict[str, Any], skeleton_name: str, seed: int) -> Path:
        normalized = _save_detail_to_db(payload, skeleton_name, seed)
        p = _detail_path_for(normalized["name"], normalized["seed"])
        tmp = p.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2)
        tmp.replace(p)
        return p

    def _load_detail_map(skeleton_name: str, seed: int) -> Dict[str, Any]:
        from_db = _load_detail_from_db(skeleton_name, seed)
        if from_db is not None:
            return from_db
        p = _detail_path_for(skeleton_name, seed)
        if p.exists():
            payload = _read_json(p)
            normalized = _normalize_detail_map_payload(payload, skeleton_name, seed)
            _save_detail_to_db(normalized, skeleton_name, seed)
            return normalized
        legacy = _legacy_detail_path_for(skeleton_name, seed)
        if not legacy.exists():
            raise FileNotFoundError(p.name)
        payload = _read_json(legacy)
        normalized = _normalize_detail_map_payload(payload, skeleton_name, seed)
        _save_detail_to_db(normalized, skeleton_name, seed)
        return normalized

    def _delete_detail_map(skeleton_name: str, seed: int) -> None:
        p = _detail_path_for(skeleton_name, seed)
        legacy = _legacy_detail_path_for(skeleton_name, seed)
        deleted = False
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM map_detail_edits WHERE skeleton_name = ? AND seed = ?",
                (_safe_name(skeleton_name), int(seed)),
            )
            deleted = cur.rowcount > 0
            conn.commit()
        finally:
            conn.close()
        if p.exists():
            p.unlink()
            deleted = True
        if legacy.exists() and legacy != p:
            legacy.unlink()
            deleted = True
        if not deleted:
            raise FileNotFoundError(p.name)

    def _list_skeleton_maps() -> list[Dict[str, Any]]:
        items: Dict[str, Dict[str, Any]] = {}
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT name, payload FROM map_skeletons ORDER BY name")
            db_rows = cur.fetchall()
        finally:
            conn.close()
        for row in db_rows:
            try:
                payload = _normalize_payload(json.loads(row["payload"]), row["name"])
                items[payload["name"]] = {
                    "name": payload["name"],
                    "width": payload["width"],
                    "height": payload["height"],
                    "description": payload.get("description", ""),
                }
            except Exception:
                continue
        seen_paths: set[str] = set()
        for folder in (data_dir, legacy_data_dir):
            if not folder.exists():
                continue
            for p in sorted(folder.glob("*.json")):
                path_key = str(p.resolve())
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                try:
                    payload = _normalize_payload(_read_json(p), p.stem)
                    _save_skeleton_to_db(payload, payload["name"])
                    items[payload["name"]] = {
                        "name": payload["name"],
                        "width": payload["width"],
                        "height": payload["height"],
                        "description": payload.get("description", ""),
                    }
                except Exception:
                    items.setdefault(
                        p.stem,
                        {"name": p.stem, "width": "?", "height": "?", "description": "Unreadable JSON"},
                    )
        return sorted(items.values(), key=lambda item: str(item.get("name") or "").lower())

    def _list_detail_maps(skeleton_name: str) -> list[Dict[str, Any]]:
        prefix = f"{_safe_name(skeleton_name)}__seed_"
        items_by_seed: Dict[int, Dict[str, Any]] = {}
        conn = _db_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT seed, payload, updated_at FROM map_detail_edits WHERE skeleton_name = ? ORDER BY seed DESC",
                (_safe_name(skeleton_name),),
            )
            db_rows = cur.fetchall()
        finally:
            conn.close()
        for row in db_rows:
            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {}
            items_by_seed[int(row["seed"])] = {
                "seed": int(row["seed"]),
                "save_label": str(payload.get("save_label") or "")[:120],
                "file_name": _detail_map_file_name(skeleton_name, int(row["seed"])),
                "updated_at": datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.utcnow(),
                "description": str(payload.get("description") or "")[:160],
                "width": int(payload.get("width") or 0),
                "height": int(payload.get("height") or 0),
            }
        for folder in (detail_dir, legacy_detail_dir):
            if not folder.exists():
                continue
            for p in sorted(folder.glob(f"{prefix}*.json"), reverse=True):
                seed_part = p.stem.removeprefix(prefix)
                try:
                    seed_value = int(seed_part)
                except ValueError:
                    continue
                if seed_value in items_by_seed:
                    continue
                payload: Dict[str, Any] = {}
                try:
                    payload = _read_json(p)
                    _save_detail_to_db(payload, skeleton_name, seed_value)
                except Exception:
                    payload = {}
                items_by_seed[seed_value] = {
                    "seed": seed_value,
                    "save_label": str(payload.get("save_label") or "")[:120],
                    "file_name": p.name,
                    "updated_at": datetime.fromtimestamp(p.stat().st_mtime),
                    "description": str(payload.get("description") or "")[:160],
                    "width": int(payload.get("width") or 0),
                    "height": int(payload.get("height") or 0),
                }
        return sorted(items_by_seed.values(), key=lambda item: int(item["seed"]), reverse=True)

    def _load_detail_state_from_store(skeleton_name: str, seed: int) -> Dict[str, Any] | None:
        if redis_client is None:
            return detail_room_states.get(_detail_room_name(skeleton_name, seed))
        raw = redis_client.get(_detail_state_key(skeleton_name, seed))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except Exception:
            return None
        return _normalize_detail_map_payload(payload, skeleton_name, seed)

    def _save_detail_state_to_store(detail_payload: Dict[str, Any], skeleton_name: str, seed: int) -> None:
        normalized = _normalize_detail_map_payload(detail_payload, skeleton_name, seed)
        if redis_client is None:
            detail_room_states[_detail_room_name(skeleton_name, seed)] = normalized
            return
        redis_client.set(_detail_state_key(skeleton_name, seed), json.dumps(normalized))
        redis_client.expire(_detail_state_key(skeleton_name, seed), 60 * 60 * 24)

    def _delete_detail_state_from_store(skeleton_name: str, seed: int) -> None:
        room = _detail_room_name(skeleton_name, seed)
        detail_room_states.pop(room, None)
        detail_room_presence.pop(room, None)
        if redis_client is not None:
            redis_client.delete(_detail_state_key(skeleton_name, seed))
            redis_client.delete(_detail_presence_key(skeleton_name, seed))

    def _presence_touch(room: str, skeleton_name: str, seed: int, sid: str, user_name: str) -> None:
        now = time.time()
        if redis_client is None:
            detail_room_presence.setdefault(room, {})[sid] = {"name": user_name, "ts": now}
            return
        redis_client.hset(
            _detail_presence_key(skeleton_name, seed),
            sid,
            json.dumps({"name": user_name, "ts": now}),
        )
        redis_client.expire(_detail_presence_key(skeleton_name, seed), 60 * 60 * 24)

    def _presence_remove(room: str, skeleton_name: str, seed: int, sid: str) -> None:
        if redis_client is None:
            room_presence = detail_room_presence.get(room, {})
            room_presence.pop(sid, None)
            if not room_presence:
                detail_room_presence.pop(room, None)
            return
        redis_client.hdel(_detail_presence_key(skeleton_name, seed), sid)

    def _presence_names(room: str, skeleton_name: str, seed: int) -> list[str]:
        cutoff = time.time() - 90
        names: list[str] = []
        seen = set()
        if redis_client is None:
            room_presence = detail_room_presence.get(room, {})
            for sid, meta in list(room_presence.items()):
                last_seen = float(meta.get("ts") or 0)
                if last_seen < cutoff:
                    room_presence.pop(sid, None)
                    continue
                name = str(meta.get("name") or "").strip() or "Anonymous"
                lowered = name.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                names.append(name)
            return sorted(names, key=str.lower)

        for sid, raw in (redis_client.hgetall(_detail_presence_key(skeleton_name, seed)) or {}).items():
            try:
                meta = json.loads(raw)
            except Exception:
                redis_client.hdel(_detail_presence_key(skeleton_name, seed), sid)
                continue
            last_seen = float(meta.get("ts") or 0)
            if last_seen < cutoff:
                redis_client.hdel(_detail_presence_key(skeleton_name, seed), sid)
                continue
            name = str(meta.get("name") or "").strip() or "Anonymous"
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            names.append(name)
        return sorted(names, key=str.lower)

    def _get_or_create_room_state(skeleton_name: str, seed: int, base_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        existing = _load_detail_state_from_store(skeleton_name, seed)
        if existing:
            _repair_detail_map_spawn_heroes(existing, _load_entity_assets())
            return existing
        if base_payload is not None:
            normalized = _normalize_detail_map_payload(base_payload, skeleton_name, seed)
        else:
            try:
                normalized = _load_detail_map(skeleton_name, seed)
            except FileNotFoundError:
                normalized = _normalize_detail_map_payload(
                    {
                        "name": skeleton_name,
                        "seed": seed,
                        "width": 1,
                        "height": 1,
                        "cells": [],
                    },
                    skeleton_name,
                    seed,
                )
        _repair_detail_map_spawn_heroes(normalized, _load_entity_assets())
        _save_detail_state_to_store(normalized, skeleton_name, seed)
        return normalized

    def _apply_detail_cell_patches(detail_payload: Dict[str, Any], raw_cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        width = int(detail_payload.get("width") or 1)
        height = int(detail_payload.get("height") or 1)
        by_key = {(int(cell["row"]), int(cell["col"])): cell for cell in detail_payload.get("cells", [])}
        applied: List[Dict[str, Any]] = []
        for raw in raw_cells:
            normalized = _normalize_detail_map_cell(raw, width, height)
            if not normalized:
                continue
            by_key[(normalized["row"], normalized["col"])] = normalized
            applied.append(normalized)
        if applied:
            detail_payload["cells"] = [by_key[(row, col)] for row in range(height) for col in range(width) if (row, col) in by_key]
        return applied

    @app.route("/map-skeletons", methods=["GET", "POST"])
    @_admin_required
    def map_skeletons_home():
        if request.method == "POST":
            name = _safe_name(request.form.get("name") or "new_map")
            width = request.form.get("width", 25)
            height = request.form.get("height", 25)
            skeleton = _blank_skeleton(name, int(width), int(height))
            _save(skeleton, name)
            return redirect(url_for("map_skeletons_editor", name=name))

        maps = _list_skeleton_maps()
        return render_template("map_skeletons_index.html", maps=maps)

    @app.route("/map-skeletons/<name>")
    @_admin_required
    def map_skeletons_editor(name: str):
        safe_name = _safe_name(name)
        try:
            payload = _load(safe_name)
        except FileNotFoundError:
            payload = _blank_skeleton(safe_name, 25, 25)
            _save(payload, safe_name)
        return render_template(
            "map_skeleton_editor.html",
            map_name=payload["name"],
            map_width=payload["width"],
            map_height=payload["height"],
            role_colors=ROLE_COLORS,
            role_defaults=ROLE_DEFAULTS,
        )

    @app.route("/map-skeletons/<name>/preview")
    @_admin_required
    def map_skeletons_preview(name: str):
        try:
            payload = _load(name)
        except FileNotFoundError:
            return redirect(url_for("map_skeletons_home"))

        seed_raw = request.args.get("seed", "").strip()
        try:
            seed = int(seed_raw) if seed_raw else random.randint(1000, 999999)
        except ValueError:
            seed = random.randint(1000, 999999)

        preview = _build_preview_map(payload, seed)
        return render_template(
            "map_skeleton_preview.html",
            map_name=payload["name"],
            map_width=payload["width"],
            map_height=payload["height"],
            map_description=payload.get("description") or "",
            preview=preview,
        )

    @app.route("/map-skeletons/<name>/detail")
    @_admin_required
    def map_skeletons_detail_editor(name: str):
        try:
            skeleton_payload = _load(name)
        except FileNotFoundError:
            return redirect(url_for("map_skeletons_home"))

        seed_raw = request.args.get("seed", "").strip()
        try:
            seed = int(seed_raw) if seed_raw else random.randint(1000, 999999)
        except ValueError:
            seed = random.randint(1000, 999999)

        try:
            detail_payload = _load_detail_map(skeleton_payload["name"], seed)
        except FileNotFoundError:
            preview = _build_preview_map(skeleton_payload, seed)
            detail_payload = _build_detail_editor_payload(skeleton_payload, preview)
            _save_detail_map(detail_payload, skeleton_payload["name"], seed)

        textures = _load_texture_assets()
        landmarks = _load_landmark_assets()
        entities = _load_entity_assets()
        _repair_detail_map_spawn_heroes(detail_payload, entities)
        saved_detail_maps = _list_detail_maps(skeleton_payload["name"])

        return render_template(
            "map_detail_editor.html",
            map_name=skeleton_payload["name"],
            map_width=detail_payload["width"],
            map_height=detail_payload["height"],
            map_description=skeleton_payload.get("description") or "",
            detail_map=detail_payload,
            textures=textures,
            landmarks=landmarks,
            entities=entities,
            guarded_landmark_keys=sorted(GUARDED_ELIGIBLE_LANDMARK_KEYS),
            guarded_entity_keys=sorted(GUARDED_ELIGIBLE_ENTITY_KEYS),
            saved_detail_maps=saved_detail_maps,
        )

    @app.route("/map-skeletons/<name>/detail-maps")
    @_admin_required
    def map_skeletons_detail_maps(name: str):
        try:
            skeleton_payload = _load(name)
        except FileNotFoundError:
            return redirect(url_for("map_skeletons_home"))

        return render_template(
            "map_detail_maps_index.html",
            map_name=skeleton_payload["name"],
            map_width=skeleton_payload["width"],
            map_height=skeleton_payload["height"],
            map_description=skeleton_payload.get("description") or "",
            saved_detail_maps=_list_detail_maps(skeleton_payload["name"]),
        )

    @app.route("/api/map-skeletons/<name>", methods=["GET"])
    @_admin_required
    def api_map_skeleton_get(name: str):
        try:
            return jsonify(_load(name))
        except FileNotFoundError:
            return jsonify({"error": "Map not found"}), 404

    @app.route("/api/map-skeletons/<name>/save", methods=["POST"])
    @_admin_required
    def api_map_skeleton_save(name: str):
        payload = request.get_json(silent=True) or {}
        try:
            p = _save(payload, name)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "name": p.stem, "path": str(p.name)})

    @app.route("/api/map-skeletons/<name>/detail-save", methods=["POST"])
    @_admin_required
    def api_map_detail_save(name: str):
        payload = request.get_json(silent=True) or {}
        seed = int(payload.get("seed") or 0)
        try:
            p = _save_detail_map(payload, name, seed)
            _save_detail_state_to_store(payload, name, seed)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "name": p.stem, "path": str(p.name)})

    @app.route("/api/map-skeletons/<name>/detail-save/<int:seed>/delete", methods=["POST"])
    @_admin_required
    def api_map_detail_delete(name: str, seed: int):
        try:
            _delete_detail_map(name, seed)
            _delete_detail_state_from_store(name, seed)
        except FileNotFoundError:
            return jsonify({"ok": False, "error": "Detail save not found"}), 404
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True})

    if socketio is not None:
        @socketio.on("detail_map_join")
        def detail_map_join(payload: Dict[str, Any] | None = None):
            payload = payload or {}
            skeleton_name = _safe_name(payload.get("map_name") or payload.get("name") or "")
            seed = int(payload.get("seed") or 0)
            if not skeleton_name or not seed:
                return
            room = _detail_room_name(skeleton_name, seed)
            join_room(room)
            detail_sid_rooms[request.sid] = {"room": room, "name": skeleton_name, "seed": seed}
            _presence_touch(room, skeleton_name, seed, request.sid, _detail_editor_user_label())
            detail_payload = _get_or_create_room_state(skeleton_name, seed, payload.get("detail_map"))
            emit(
                "detail_map_state",
                {
                    "map_name": skeleton_name,
                    "seed": seed,
                    "detail_map": detail_payload,
                    "editors": _presence_names(room, skeleton_name, seed),
                },
            )
            emit(
                "detail_map_presence",
                {
                    "map_name": skeleton_name,
                    "seed": seed,
                    "editors": _presence_names(room, skeleton_name, seed),
                },
                to=room,
            )

        @socketio.on("detail_map_presence_ping")
        def detail_map_presence_ping(payload: Dict[str, Any] | None = None):
            payload = payload or {}
            skeleton_name = _safe_name(payload.get("map_name") or payload.get("name") or "")
            seed = int(payload.get("seed") or 0)
            if not skeleton_name or not seed:
                return
            room = _detail_room_name(skeleton_name, seed)
            _presence_touch(room, skeleton_name, seed, request.sid, _detail_editor_user_label())
            emit(
                "detail_map_presence",
                {
                    "map_name": skeleton_name,
                    "seed": seed,
                    "editors": _presence_names(room, skeleton_name, seed),
                },
                to=room,
            )

        @socketio.on("detail_map_patch")
        def detail_map_patch(payload: Dict[str, Any] | None = None):
            payload = payload or {}
            skeleton_name = _safe_name(payload.get("map_name") or payload.get("name") or "")
            seed = int(payload.get("seed") or 0)
            raw_cells = payload.get("cells") or []
            if not skeleton_name or not seed or not isinstance(raw_cells, list):
                return
            room = _detail_room_name(skeleton_name, seed)
            detail_payload = _get_or_create_room_state(skeleton_name, seed, payload.get("detail_map"))
            _presence_touch(room, skeleton_name, seed, request.sid, _detail_editor_user_label())
            if "save_label" in payload:
                detail_payload["save_label"] = str(payload.get("save_label") or "").strip()[:120]
            applied = _apply_detail_cell_patches(detail_payload, raw_cells)
            if not applied and "save_label" not in payload:
                return
            _save_detail_state_to_store(detail_payload, skeleton_name, seed)
            emit(
                "detail_map_patch",
                {
                    "map_name": skeleton_name,
                    "seed": seed,
                    "cells": applied,
                    "save_label": detail_payload.get("save_label") or "",
                },
                to=room,
                include_self=False,
            )

        @socketio.on("detail_map_leave")
        def detail_map_leave(payload: Dict[str, Any] | None = None):
            payload = payload or {}
            skeleton_name = _safe_name(payload.get("map_name") or payload.get("name") or "")
            seed = int(payload.get("seed") or 0)
            info = detail_sid_rooms.pop(request.sid, None) or {}
            room = info.get("room")
            skeleton_name = skeleton_name or info.get("name") or ""
            seed = seed or int(info.get("seed") or 0)
            if not room and skeleton_name and seed:
                room = _detail_room_name(skeleton_name, seed)
            if not room or not skeleton_name or not seed:
                return
            leave_room(room)
            _presence_remove(room, skeleton_name, seed, request.sid)
            emit(
                "detail_map_presence",
                {
                    "map_name": skeleton_name,
                    "seed": seed,
                    "editors": _presence_names(room, skeleton_name, seed),
                },
                to=room,
            )

    @app.route("/map-skeletons/<name>/download")
    @_admin_required
    def map_skeleton_download(name: str):
        from flask import send_file

        try:
            payload = _load(name)
            p = _save(payload, name)
        except FileNotFoundError:
            return redirect(url_for("map_skeletons_home"))
        return send_file(p, as_attachment=True, download_name=p.name, mimetype="application/json")
