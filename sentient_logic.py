# sentient_logic.py

import random
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Tuple

from sentient_generator import (
    RaceTemplate,
    GearItem,
    combine_race_and_gear,
)

# -------------------------------------------------
#  RARITY → GOLD COST  (all keys LOWERCASE) (DO NOT FUCKING MAKE THEM UPPERCASE OR THIS FUCKING SHIT BREAKS)
# -------------------------------------------------

RARITY_COST: Dict[str, int] = {
    "common": 200,
    "uncommon": 400,
    "rare": 600,
    "epic": 800,
    "legendary": 1000,
    "mythic": 2000,
}


def rarity_key(value: Optional[str]) -> str:
    """Normalize any rarity string to a lowercase key."""
    return str(value or "").strip().lower()


def same_rarity(a: Optional[str], b: Optional[str]) -> bool:
    return rarity_key(a) == rarity_key(b)


def _item_cost(item: GearItem) -> int:
    """Cost of an item in 'gold' based purely on its rarity."""
    key = rarity_key(getattr(item, "rarity", None))
    return RARITY_COST.get(key, 0)


# -------------------------------------------------
#  RANK CONFIG
# -------------------------------------------------
# required_rarity is written with pretty capitalization (for display),

RANK_CONFIG: Dict[str, Dict[str, int]] = {
    "Weakling":       {"required_rarity": "Common",    "extra_gold": 200},
    "Prime Weakling": {"required_rarity": "Uncommon",  "extra_gold": 200},
    "Elite":          {"required_rarity": "Rare",      "extra_gold": 400},
    "Prime Elite":    {"required_rarity": "Epic",      "extra_gold": 400},
    "Boss":           {"required_rarity": "Legendary", "extra_gold": 600},
    "Prime Boss":     {"required_rarity": "Legendary", "extra_gold": 800},
    "Guardian":       {"required_rarity": "Mythic",    "extra_gold": 1000},
}

FACTIONS = ["Bandit", "Legion", "Conclave"]

# -------------------------------------------------
#  INTELLIGENCE
# -------------------------------------------------


def roll_intelligence(rng: random.Random) -> Tuple[int, str]:
    """Roll a d20 and translate to an intelligence label."""
    roll = rng.randint(1, 20)

    if roll <= 1:
        label = "Dumb"
    elif roll <= 6:
        label = "Dimwitted"
    elif roll <= 15:
        label = "Average"
    elif roll <= 19:
        label = "Cunning"
    else:
        label = "Genius"

    return roll, label


# -------------------------------------------------
#  NAMES & ABILITIES (placeholder)
# -------------------------------------------------

NAME_POOL = ["Ayo", "Berlin", "Corin", "DoraTheBitch", "MrNutsScratcher", "Gaylord"]  # you can replace this


def random_name(rng: random.Random) -> str:
    return rng.choice(NAME_POOL)


def random_abilities_for_race(
    rank_key: str,
    race_key: str,
    rng: random.Random,
) -> List[str]:
    """
    Placeholder hook. Later you’ll plug in your Normalized Abilities logic.
    For now we just return an empty list.
    """
    return []


# -------------------------------------------------
#  GEAR HELPERS
# -------------------------------------------------


def _is_artifact(item: GearItem) -> bool:
    """Artifacts should never be picked for sentients."""
    t = (getattr(item, "gear_type", "") or "").strip().lower()
    slot = (getattr(item, "slot_type", "") or "").strip().lower()
    name = (getattr(item, "name", "") or "").strip().lower()
    return "artifact" in t or "artifact" in slot or "artifact" in name


def _allowed_for_faction(g: GearItem, faction: str) -> bool:
    """
    Filter for usable gear:
      - must have a non-empty name
      - must not be a 'nan' or 'Insert' placeholder
      - must not be an Artifact
      - must match faction (unless faction is empty/'Any')
    """
    raw_name = getattr(g, "name", None)
    name_str = str(raw_name).strip()

    # nameless / NaN
    if not name_str or name_str.lower() == "nan":
        return False

    # WIP placeholders
    if "insert" in name_str.lower():
        return False

    # no artifacts
    if _is_artifact(g):
        return False

    f = (g.faction or "").strip()
    if not f or f.lower() == "any":
        return True

    return f.lower() == faction.lower()


def _get_handedness(g: GearItem) -> str:
    """
    Determine if a gear item is one-handed or two-handed.
    Returns: "one-handed", "two-handed", or "" (unknown).
    """
    raw = (
        getattr(g, "slot_type", None)
        or getattr(g, "handedness", None)
        or getattr(g, "subtype", None)
        or ""
    )
    s = str(raw).strip().lower()

    if "two" in s and "hand" in s:
        return "two-handed"
    if "one" in s and "hand" in s:
        return "one-handed"
    return ""


def _ammo_kind_from_item(item: GearItem) -> str:
    """
    Classify an *ammo item* (Quiver / Pouch).
    Uses slot_type + name (since Column AT is for weapons only).

    Returns:
        "quiver" / "pouch" / "" (not ammo).
    """
    slot = (item.slot_type or "").strip().lower()
    name = (item.name or "").strip().lower()

    if "ammo" not in slot and "ammunition" not in slot:
        return ""

    if "quiver" in name:
        return "quiver"
    if any(x in name for x in ["pouch", "sack", "bag"]):
        return "pouch"

    return ""


def _weapon_ammo_kind(weapon: Optional[GearItem]) -> str:
    """
    Look at Column AT ('Ammo Requirement') on the weapon:

      - contains 'Quiver' -> 'quiver'
      - contains 'Pouch' / 'Sack' / 'Bag' -> 'pouch'
      - otherwise -> ''  (no ammo required)
    """
    if weapon is None:
        return ""

    if (weapon.gear_type or "").strip().lower() != "weapon":
        return ""

    req = (weapon.ammo_requirement or "").strip().lower()
    if "quiver" in req:
        return "quiver"
    if any(x in req for x in ["pouch", "sack", "bag"]):
        return "pouch"

    return ""


def _is_weapon(item: GearItem) -> bool:
    return (item.gear_type or "").strip().lower() == "weapon"


# -------------------------------------------------
#  MAIN GEAR GENERATION
# -------------------------------------------------


def generate_gear_for_sentient(
    rank_name: str,
    faction: str,
    gear_pool: Dict[int, GearItem],
    rng: random.Random,
) -> List[GearItem]:
    """
    New flow:

      1) Pick REQUIRED rarity weapon first (if possible).
         This is the “mandatory” item for the rank.
      2) If that weapon needs ammo (Column AT), buy that ammo
         immediately from the same gold pool.
      3) With remaining budget, keep buying random extra gear
         (non-ammo) until we can't afford more.
         - Respect one-handed / two-handed weapon rules.
         - Never give ammo without a weapon that wants it.
    """

    cfg = RANK_CONFIG[rank_name]
    required_rarity_name: str = cfg["required_rarity"]        # e.g. "Legendary"
    required_rarity_key: str = rarity_key(required_rarity_name)  # 'legendary'
    extra_gold: int = cfg["extra_gold"]

    # Total budget in "gold"
    total_budget = RARITY_COST[required_rarity_key] + extra_gold

    # --------- Build candidate pools (by faction) ---------
    candidates: List[GearItem] = [
        g for g in gear_pool.values() if _allowed_for_faction(g, faction)
    ]
    if not candidates:
        return []

    ammo_items: List[GearItem] = [g for g in candidates if _ammo_kind_from_item(g)]
    weapons: List[GearItem] = [
        g for g in candidates if _is_weapon(g) and g not in ammo_items
    ]
    others: List[GearItem] = [
        g for g in candidates
        if g not in ammo_items and g not in weapons
    ]

    # --------- 1) REQUIRED rarity item: try to make it a weapon ---------
    forced_item: GearItem
    main_weapon: Optional[GearItem] = None

    forced_weapons = [
        w for w in weapons if same_rarity(w.rarity, required_rarity_name)
    ]

    if forced_weapons:
        main_weapon = rng.choice(forced_weapons)
        forced_item = main_weapon
    else:
        rarity_items = [
            g for g in others if same_rarity(g.rarity, required_rarity_name)
        ]
        if rarity_items:
            forced_item = rng.choice(rarity_items)
        else:
            non_ammo = weapons + others
            if not non_ammo:
                return []
            forced_item = rng.choice(non_ammo)
        if _is_weapon(forced_item):
            main_weapon = forced_item

    chosen: List[GearItem] = [forced_item]

    # the required item always costs its rank rarity
    remaining_budget = total_budget - RARITY_COST[required_rarity_key]

    # --------- 2) If we still have no weapon, try to buy one now ---------
    if main_weapon is None:
        weapon_candidates = [w for w in weapons if w.id != forced_item.id]
        affordable = [w for w in weapon_candidates if _item_cost(w) <= remaining_budget]
        if affordable:
            main_weapon = rng.choice(affordable)
            chosen.append(main_weapon)
            remaining_budget -= _item_cost(main_weapon)

    # --------- 3) If main weapon needs ammo → buy it immediately ---------
    ammo_kind_needed = _weapon_ammo_kind(main_weapon)
    if ammo_kind_needed:
        kind_candidates = [
            a for a in ammo_items if _ammo_kind_from_item(a) == ammo_kind_needed
        ]
        affordable_ammo = [
            a for a in kind_candidates if _item_cost(a) <= remaining_budget
        ]
        if affordable_ammo:
            ammo_item = rng.choice(affordable_ammo)
            chosen.append(ammo_item)
            remaining_budget -= _item_cost(ammo_item)
            # remove from pool so it isn't picked again later
            ammo_items = [a for a in ammo_items if a.id != ammo_item.id]

    taken_ids: Set[int] = {g.id for g in chosen}

    # --------- 4) Spend remaining budget on random extras (no ammo) ---------

    def build_extra_candidates() -> List[GearItem]:
        extra: List[GearItem] = []

        current_weapons = [g for g in chosen if _is_weapon(g)]
        weapon_count = len(current_weapons)
        main_hands = _get_handedness(current_weapons[0]) if weapon_count else ""

        for g in weapons + others:
            if g.id in taken_ids:
                continue

            cost = _item_cost(g)
            if cost <= 0 or cost > remaining_budget:
                continue

            if _is_weapon(g):
                # Weapon rules:
                if weapon_count == 0:
                    extra.append(g)
                elif weapon_count == 1:
                    gh = _get_handedness(g)
                    if main_hands == "two-handed":
                        # already have a 2H -> no more weapons
                        continue
                    if gh == "two-handed":
                        # can't add a 2H to an existing 1H
                        continue
                    extra.append(g)  # 1H + 1H allowed
                else:
                    # already have 2 weapons
                    continue
            else:
                extra.append(g)

        return extra

    min_cost = min(RARITY_COST.values())

    while remaining_budget >= min_cost:
        extra_candidates = build_extra_candidates()
        if not extra_candidates:
            break

        item = rng.choice(extra_candidates)
        chosen.append(item)
        taken_ids.add(item.id)
        remaining_budget -= _item_cost(item)

    return chosen


# -------------------------------------------------
#  RESULT DATACLASS
# -------------------------------------------------

@dataclass
class GeneratedSentient:
    name: str
    rank: str
    faction: str
    race_key: str
    race: RaceTemplate
    intelligence_roll: int
    intelligence_label: str
    abilities: List[str]
    gear: List[GearItem]
    stats: Dict[str, float]
    resists: Dict[str, float]


# -------------------------------------------------
#  MASTER GENERATOR
# -------------------------------------------------

def generate_sentient(
    rank_key: str,
    RACES: Dict[str, RaceTemplate],
    GEAR: Dict[int, GearItem],
    rng: Optional[random.Random] = None,
) -> GeneratedSentient:
    """
    High-level pipeline:
      1) Pick faction (33.3% each)
      2) Pick race out of the full pool
      3) Generate gear using current logic
      4) Combine race + gear into final stats
      5) Roll d20 intelligence
      6) Assign placeholder name
      7) Placeholder abilities (currently empty list)
    """
    if rng is None:
        rng = random

    if rank_key not in RANK_CONFIG:
        raise ValueError(f"Unknown rank '{rank_key}'")

    # 1) faction
    faction = rng.choice(FACTIONS)

    # 2) race
    race_key = rng.choice(list(RACES.keys()))
    race = RACES[race_key]

    # 3) gear
    gear_list = generate_gear_for_sentient(rank_key, faction, GEAR, rng)

    # 4) combined stats
    sent_stats = combine_race_and_gear(race, gear_list)

    # 5) intelligence
    int_roll, int_label = roll_intelligence(rng)

    # 6) name
    name = random_name(rng)

    # 7) abilities (placeholder)
    abilities = random_abilities_for_race(rank_key, race_key, rng)

    return GeneratedSentient(
        name=name,
        rank=rank_key,
        faction=faction,
        race_key=race_key,
        race=race,
        intelligence_roll=int_roll,
        intelligence_label=int_label,
        abilities=abilities,
        gear=gear_list,
        stats=sent_stats.stats,
        resists=sent_stats.resists,
    )
