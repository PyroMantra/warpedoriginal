
from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import math
import re

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _num(x, default=0.0) -> float:
    """Coerce any cell value to float, treating NaN / '' as 0."""
    if isinstance(x, str) and not x.strip():
        return float(default)
    try:
        v = float(x)
        if math.isnan(v):
            return float(default)
        return v
    except Exception:
        return float(default)


def _percent_like(x, default=0.0) -> float:
    """
    Handle things like '20%', '0.2', 0.2, 20.
    Returns a decimal (0.2 for 20%).
    """
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return float(default)
        if s.endswith("%"):
            try:
                return float(s[:-1]) / 100.0
            except Exception:
                return float(default)
        try:
            v = float(s)
        except Exception:
            return float(default)
    else:
        v = _num(x, default)

    # If it looks like a percentage in whole numbers, convert (e.g. 20 → 0.2)
    if abs(v) > 1:
        return v / 100.0
    return v


def _resist_from_gear(x) -> float:
    """Gear resistances are usually 20, 40 etc → 0.2, 0.4."""
    return _percent_like(x, 0.0)


def _parse_gold_cost(x) -> int:
    """Gold cost can be '200 Gold', '200', 200, etc."""
    if isinstance(x, str):
        m = re.search(r"-?\d+", x)
        return int(m.group(0)) if m else 0
    try:
        v = int(float(x))
        return v
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

# columns for numeric stats used by both races & gear
BASE_STAT_COLS = [
    "Health", "Mana", "Defense", "Dispersion",
    "Strength", "Dexterity", "Power", "Stamina"
]

EXTRA_STAT_COLS = [
    "Mobility", "Might", "Wisdom", "Fortitude",
    "Deflection", "Faith"
]

ALL_STAT_COLS = BASE_STAT_COLS + EXTRA_STAT_COLS

# Race sheet uses these exact resistance column names (with NBSPs)
RACE_RESIST_COLUMNS = {
    "LIGHT Resistance\xa0": "Light",
    "DARK\xa0 Resistance\xa0": "Dark",
    "FIRE Resistance\xa0\xa0": "Fire",
    "FROST\xa0 Resistance\xa0": "Frost",
    "WIND\xa0 Resistance\xa0": "Wind",
    "EARTH\xa0 Resistance\xa0": "Earth",
    "LIGHTNING Resistance\xa0\xa0": "Lightning",
    "BLEED\xa0 Resistance\xa0": "Bleed",
    "POISON Resistance\xa0\xa0": "Poison",
}

# Gear sheet resistance columns
GEAR_RESIST_COLUMNS = {
    "Light Resistance": "Light",
    "Dark Resistance": "Dark",
    "Fire Resistance": "Fire",
    "Frost Resistance": "Frost",
    "Wind Resistance": "Wind",
    "Earth Resistance": "Earth",
    "Lightning Resistance": "Lightning",
    "Bleed Resistance": "Bleed",
    "Poison Resistance": "Poison",
}


@dataclass
class RaceTemplate:
    race: str
    subtype: str
    kin: str
    base_stats: Dict[str, float]
    resists: Dict[str, float]
    conditions: str


@dataclass
class GearItem:
    id: int               # index in the gear dataframe
    name: str
    rarity: str
    gear_type: str        # Weapon / Armor / Ammunition / Accessory / Artifact...
    slot_type: str        # One-handed / Two-handed / Leg Piece / Ammunition Slot ...
    faction: str
    stats: Dict[str, float]
    resists: Dict[str, float]
    gold_cost: int
    ammo_requirement: Optional[str] = None   # 'Quiver', 'Pouch', or None
    weapon_group: Optional[str] = None       # Column G (Bow / Crossbow / Pistol / Rifle / etc.)
    summary: str = ""      # NEW: text from column A


@dataclass
class SentientStats:
    race_key: str                 # e.g. "Human:Dunian"
    gear_ids: List[int]           # row indices of chosen gear
    stats: Dict[str, float]       # final stats
    resists: Dict[str, float]     # final resistances, decimals (-1..1)


# ---------------------------------------------------------------------------
# Loading from EXCEL (FUCKING KILL ME)
# ---------------------------------------------------------------------------

def load_races(excel_path: str, sheet_name: str = "Sheet1") -> Dict[str, RaceTemplate]:
    """
    Load all race/subtype combos from Sheet1 into RaceTemplate objects.
    key: "Race:Subtype"
    """
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    # KIN column in your sheet is empty for now, but we'll still propagate it
    df["KIN"] = df["KIN"].ffill()

    races: Dict[str, RaceTemplate] = {}

    for _, row in df.iterrows():
        race = str(row.get("RACES") or "").strip()
        subtype = str(row.get("SUBTYPES") or "").strip()
        if not race or not subtype:
            continue

        # Core stats
        base_stats: Dict[str, float] = {
            "Health": _num(row.get("HEALTH", 0)),
            "Mana": _num(row.get("MANA", 0)),
            "Defense": _num(row.get("DEFENSE", 0)),
            "Dispersion": _num(row.get("DISPERSION", 0)),
            "Strength": _num(row.get("STRENGTH", 0)),
            "Dexterity": _num(row.get("DEXTERITY", 0)),
            "Power": _num(row.get("POWER", 0)),
            "Stamina": _num(row.get("STAMINA", 0)),
            "Fortitude": _percent_like(row.get("FORTITUDE", 0)),
            "Deflection": _percent_like(row.get("DEFLECTION", 0)),
}

        # Resistances
        resists: Dict[str, float] = {}
        for col, key in RACE_RESIST_COLUMNS.items():
            resists[key] = _percent_like(row.get(col, 0))

        key = f"{race}:{subtype}"
        races[key] = RaceTemplate(
            race=race,
            subtype=subtype,
            kin=str(row.get("KIN") or "").strip(),
            base_stats=base_stats,
            resists=resists,
            conditions=str(row.get("CONDITIONS") or "").strip(),
        )

    return races


def load_gear(excel_path: str, sheet_name: str = "Sheet3") -> Dict[int, GearItem]:
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    items: Dict[int, GearItem] = {}

    # First column of the sheet = Excel column A
    col_a = df.columns[0]

    for idx, row in df.iterrows():
        # Column A preformatted text
        summary = str(row.get(col_a) or "").strip()

        name = str(row.get("Name.1") or row.get("Name") or "").strip()
        if not name:
            continue

        # Stats from gear
        stats: Dict[str, float] = {}
        for col in ALL_STAT_COLS:
            if col in df.columns:
                stats[col] = _num(row.get(col, 0))

        # Resistance bonuses from gear
        resists: Dict[str, float] = {}
        for col, key in GEAR_RESIST_COLUMNS.items():
            if col in df.columns:
                resists[key] = _resist_from_gear(row.get(col, 0))

        ammo_req = row.get("Ammo Requirement")
        if isinstance(ammo_req, float) and math.isnan(ammo_req):
            ammo_req = None
        elif isinstance(ammo_req, str) and not ammo_req.strip():
            ammo_req = None

        items[idx] = GearItem(
            id=int(idx),
            name=name,
            rarity=str(row.get("Rarity") or "").strip(),
            gear_type=str(row.get("Gear Type") or "").strip(),
            slot_type=str(row.get("Slot Type") or "").strip(),
            faction=str(row.get("Faction") or "").strip(),
            stats=stats,
            resists=resists,
            gold_cost=_parse_gold_cost(row.get("Gold Cost")),
            ammo_requirement=ammo_req,
            summary=summary,  # <<< use column A
        )

    return items


# ---------------------------------------------------------------------------
# Combining race + gear into a sentient stat block (END ME)
# ---------------------------------------------------------------------------

def combine_race_and_gear(
    race: RaceTemplate,
    gear_list: List[GearItem],
) -> SentientStats:
    """
    Sum up stats and resistances:
      final_stat = race_base + sum(gear_stat)
      final_resist = race_resist + sum(gear_resist), clamped to [-1, 1]
    """
    stats: Dict[str, float] = {k: float(v) for k, v in race.base_stats.items()}
    resists: Dict[str, float] = {k: float(v) for k, v in race.resists.items()}

    for item in gear_list:
        # stats
        for k, v in item.stats.items():
            stats[k] = stats.get(k, 0.0) + float(v or 0.0)

        # resistances (decimals)
        for k, v in item.resists.items():
            resists[k] = resists.get(k, 0.0) + float(v or 0.0)

    # Clamp resistances between -100% and +100% (−1.0 .. +1.0)
    for k in resists:
        resists[k] = max(-1.0, min(1.0, resists[k]))

    return SentientStats(
        race_key=f"{race.race}:{race.subtype}",
        gear_ids=[g.id for g in gear_list],
        stats=stats,
        resists=resists,
    )
