"""sentient_ext.py

Website integration for the Sentient generator.

Goals
-----
* Provide a /sentient-generator page that renders a creature-style card.
* Uses the "Gear" sheet (as your generator logic expects).
* Respects the Merchant/Admin "gear presence" toggles (gear_unique table) that
  are sourced from the "Gear+Items" tab.
* Works both locally and on Railway/Gunicorn without path assumptions.
"""

from __future__ import annotations

import math
import os
import random
import re
import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
from flask import render_template, request


# ------------------------------
# Config (safe defaults)
# ------------------------------

PROHIBITED_GEAR = {
    "Insert Broken Item Name",
    "Debug Sword",
    "God Mode Armor",
}

PROHIBITED_WEAKLING_RACES = {
    "Patagan",
    "Steam Walker",
}

RANKS: List[str] = [
    "Weakling",
    "Prime Weakling",
    "Elite",
    "Prime Elite",
    "Boss",
    "Prime Boss",
    "Guardian",
]

RANK_CONFIG: Dict[str, Dict[str, object]] = {
    "Weakling": {"required_rarity": "Common", "extra_gold": 200, "Highest_Rarity": "Common"},
    "Prime Weakling": {"required_rarity": "Uncommon", "extra_gold": 200, "Highest_Rarity": "Common"},
    "Elite": {"required_rarity": "Rare", "extra_gold": 400, "Highest_Rarity": "Uncommon"},
    "Prime Elite": {"required_rarity": "Epic", "extra_gold": 400, "Highest_Rarity": "Uncommon"},
    "Boss": {"required_rarity": "Legendary", "extra_gold": 600, "Highest_Rarity": "Rare"},
    "Prime Boss": {"required_rarity": "Legendary", "extra_gold": 800, "Highest_Rarity": "Epic"},
    "Guardian": {"required_rarity": "Mythic", "extra_gold": 1000, "Highest_Rarity": "Legendary"},
}

RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Astral", "Ultimate"]
RARITY_PRICE = {
    "Common": 200,
    "Uncommon": 400,
    "Rare": 600,
    "Epic": 800,
    "Legendary": 1000,
    "Mythic": 2000,
    # (kept for completeness)
    "Astral": 0,
    "Ultimate": 0,
}
UNIQUE_RARITIES = {"Legendary", "Mythic", "Astral"}

AMMO_RULES = {
    "Weakling": "Common",
    "Prime Weakling": "Common",
    "Elite": "Uncommon",
    "Prime Elite": "Uncommon",
    "Boss": "Rare",
    "Prime Boss": "Epic",
    "Guardian": "Legendary",
}


# ------------------------------
# Canon name matching (must match merchant_ext)
# ------------------------------

def _canon_name(s: str) -> str:
    """Keep only the base name before ':' or ';'."""
    s = str(s or "")
    s = s.replace("’", "'").replace("`", "'")
    s = re.split(r"[:;]", s, maxsplit=1)[0]
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _key_name(s: str) -> str:
    """Stable matching key for dedupe/toggles."""
    s = _canon_name(s).lower()
    s = s.replace("’", "'").replace("`", "'")
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


# ------------------------------
# DB: gear presence toggles (gear_unique)
# ------------------------------

def _ensure_gear_unique_table(get_db) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gear_unique (
            name TEXT PRIMARY KEY,
            rarity TEXT,
            is_artifact INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.commit()
    conn.close()


def _load_unique_enabled_map(get_db) -> Dict[str, int]:
    """Return key_name -> enabled (1/0)."""
    _ensure_gear_unique_table(get_db)
    conn = get_db()
    cur = conn.cursor()
    try:
        rows = cur.execute("SELECT name, enabled FROM gear_unique").fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    return {_key_name(r[0]): int(r[1]) for r in rows if r and r[0]}


def _sync_unique_from_gearitems(get_db, sheets_all: Dict[str, pd.DataFrame]) -> None:
    """Populate gear_unique using Gear+Items, preserving previous enabled states."""
    _ensure_gear_unique_table(get_db)

    # Find Gear+Items tab
    gearitems = None
    for k, v in (sheets_all or {}).items():
        kk = (k or "").strip().lower()
        if kk in {"gear+items", "gear&items", "gear items", "gear_and_items"}:
            gearitems = v
            break
    if gearitems is None:
        for k, v in (sheets_all or {}).items():
            kk = (k or "").strip().lower()
            if "gear" in kk and "item" in kk:
                gearitems = v
                break

    if gearitems is None or getattr(gearitems, "empty", True):
        return

    # Normalize columns like merchant_ext
    def norm(s: str) -> str:
        return re.sub(r"[^a-z]+", "", str(s).lower())

    df = gearitems.copy()
    df = df.rename(columns={c: norm(c) for c in df.columns})

    def pick(cols: List[str]) -> Optional[str]:
        for c in df.columns:
            if c in cols:
                return c
        return None

    c_kind = pick(["kind", "type", "what"])
    c_rar = pick(["rarity"])
    c_name = pick(["name", "gearitem", "gear", "item", "title"])
    c_art = pick(["artifact", "isartifact", "artifactflag"])
    if not (c_kind and c_rar and c_name):
        return
    if not c_art:
        df["artifact"] = 0
        c_art = "artifact"

    sub = df[[c_kind, c_rar, c_name, c_art]].copy()
    sub[c_name] = sub[c_name].astype(str)
    sub[c_kind] = sub[c_kind].astype(str).str.strip().str.lower()
    sub = sub[sub[c_kind].str.startswith("gear")].copy()

    sub[c_rar] = (
        sub[c_rar]
        .astype(str)
        .str.extract(r"(?i)(Common|Uncommon|Rare|Epic|Legendary|Mythic|Astral|Ultimate)")[0]
        .str.title()
    )
    sub = sub[sub[c_rar].isin(UNIQUE_RARITIES)].copy()

    sub[c_art] = sub[c_art].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"}).astype(int)

    conn = get_db()
    cur = conn.cursor()
    try:
        existing = cur.execute("SELECT name, enabled FROM gear_unique").fetchall()
        prev_enabled = {_key_name(n): int(en) for (n, en) in existing}

        desired: Dict[str, Tuple[str, str, int]] = {}
        for _, row in sub.iterrows():
            disp = _canon_name(row[c_name])
            key = _key_name(disp)
            if not key:
                continue
            rarity = str(row[c_rar] or "").strip().title()
            art = int(row[c_art] or 0)
            # keep first seen
            if key not in desired:
                desired[key] = (disp, rarity, art)

        cur.execute("DELETE FROM gear_unique")
        for key, (disp, rarity, art) in sorted(desired.items(), key=lambda kv: (kv[1][1], kv[1][0].lower())):
            cur.execute(
                "INSERT INTO gear_unique (name, rarity, is_artifact, enabled) VALUES (?,?,?,?)",
                (disp, rarity, art, prev_enabled.get(key, 1)),
            )

        conn.commit()
    finally:
        conn.close()


# ------------------------------
# Scaling CSV
# ------------------------------

@dataclass
class WeaponScaling:
    scaling: str
    crit_mult: float


def _load_scaling_csv(path: str) -> Dict[str, WeaponScaling]:
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}

    out: Dict[str, WeaponScaling] = {}
    for _, row in df.iterrows():
        weapon_type = str(row.iloc[0]).strip()
        if not weapon_type or weapon_type.lower() == "nan":
            continue
        try:
            crit = float(row.iloc[2])
        except Exception:
            crit = 1.0
        scaling_str = str(row.iloc[3]).strip()
        if not scaling_str or scaling_str.lower() == "nan":
            scaling_str = "None"
        out[weapon_type] = WeaponScaling(scaling=scaling_str, crit_mult=crit)
    return out


def _extract_scaling_multiplier(s: str) -> float:
    m = re.search(r"([0-9.]+)", str(s or ""))
    try:
        return float(m.group(1)) if m else 1.0
    except Exception:
        return 1.0


def _intelligence_label(roll: int) -> str:
    if 1 <= roll <= 4:
        return "Bestial"
    if 5 <= roll <= 8:
        return "Dim"
    if 9 <= roll <= 13:
        return "Average"
    if 14 <= roll <= 17:
        return "Cunning"
    return "Genius"


def _get_highest_affordable_rarity(gold: int) -> str:
    for r in ["Mythic", "Legendary", "Epic", "Rare", "Uncommon", "Common"]:
        if gold >= RARITY_PRICE.get(r, 10**9):
            return r
    return "Common"


# ------------------------------
# Flask integration
# ------------------------------

def init_sentient(app, get_db, sheets_all: Dict[str, pd.DataFrame], excel_path: str, login_required=None) -> None:
    """Register /sentient-generator route."""
    if getattr(app, "_sentient_init_done", False):
        return
    app._sentient_init_done = True

    _login_required = login_required or (lambda f: f)

    try:
        _sync_unique_from_gearitems(get_db, sheets_all)
    except Exception:
        # best effort
        pass

    def sget(name: str) -> Optional[pd.DataFrame]:
        for k, v in (sheets_all or {}).items():
            if (k or "").strip().lower() == name.strip().lower():
                return v
        return None

    FrameG = sget("Gear")
    FrameS = sget("Races")
    Frame1 = sget("Bandits")
    Frame2 = sget("Legion")
    Frame3 = sget("Conclave")

    missing = [
        n
        for n, df in [
            ("Gear", FrameG),
            ("Races", FrameS),
            ("Bandits", Frame1),
            ("Legion", Frame2),
            ("Conclave", Frame3),
        ]
        if df is None
    ]

    scaling_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "notion", "Scaling.csv")
    if os.path.exists(scaling_path):
        scaling_dict = _load_scaling_csv(scaling_path)
    else:
        scaling_dict = _load_scaling_csv("static/notion/Scaling.csv")

    # ------------------------------
    # Abilities
    # ------------------------------

    def _sentient_value(rank: str) -> int:
        vals = {"Weakling": 1, "Prime Weakling": 2, "Elite": 4, "Prime Elite": 5, "Boss": 6, "Prime Boss": 7, "Guardian": 8}
        return vals.get(rank, 0)

    def sum_to_n_with_max3(n: int) -> List[int]:
        elements = [list(t) for t in itertools.product(range(1, 4), repeat=3) if sum(t) == n]
        return random.choice(elements) if elements else [1, 1, 1]

    def ability_search(x: int, y: int, frame: pd.DataFrame) -> str:
        try:
            return str(frame.iat[x - 1, y - 1]).strip()
        except Exception:
            return "Unknown Ability"

    def generate_abilities(rank: str, faction: str) -> Dict[str, str]:
        if faction == "Bandit":
            selected = Frame1
        elif faction == "Legion":
            selected = Frame2
        else:
            selected = Frame3

        RangeInate = range(5, 12)
        RangeTier1 = range(12, 20)
        RangeTier2 = range(20, 29)
        RangeTier3 = range(29, 35)
        RangeTier4 = range(35, 44)

        abilities: Dict[str, str] = {}
        lvl = _sentient_value(rank)

        if rank == "Weakling":
            abilities["Innate"] = ability_search(random.choice(RangeInate), 1, selected)
        elif rank == "Prime Weakling":
            abilities["Innate"] = ability_search(random.choice(RangeInate), 1, selected)
            abilities["Tier I"] = ability_search(random.choice(RangeTier1), 1, selected)
        else:
            mylist = sum_to_n_with_max3(lvl)
            abilities["Innate"] = ability_search(random.choice(RangeInate), 1, selected)
            abilities["Tier I"] = ability_search(random.choice(RangeTier1), mylist[0], selected)
            abilities["Tier II"] = ability_search(random.choice(RangeTier2), mylist[1], selected)
            abilities["Tier III"] = ability_search(random.choice(RangeTier3), mylist[2], selected)
            if 5 < lvl < 12:
                abilities["Ultimate"] = ability_search(random.choice(RangeTier4), 1, selected)
            elif lvl == 12:
                abilities["Ultimate"] = ability_search(random.choice(RangeTier4), 2, selected)

        return abilities

    # ------------------------------
    # Gear selection (respects gear_unique)
    # ------------------------------

    def faction_selector() -> str:
        return random.choice(["Conclave", "Legion", "Bandit"])

    def _is_allowed_unique(item_name: str, rarity: str, enabled_map: Dict[str, int]) -> bool:
        r = str(rarity or "").strip().title()
        if r not in UNIQUE_RARITIES:
            return True
        en = enabled_map.get(_key_name(item_name))
        return (en is None) or (en == 1)

    def required_gear_roll(rank_info: Dict[str, object], enabled_map: Dict[str, int], faction: str = "Neutral",
                           force_weapon: bool = False, force_one_handed: bool = False, exclude_ranged: bool = False) -> str:
        df = FrameG
        long_name_col = df.columns[0]
        rarity_col = df.columns[1]
        type_col = df.columns[2]
        short_name_col = df.columns[3]
        grip_col = df.columns[4]
        meta_col = df.columns[44]

        mask = (df[short_name_col] != "**Insert**") & (df[short_name_col].notna())
        mask &= (~df[long_name_col].isin(PROHIBITED_GEAR))
        mask &= (df[meta_col].astype(str).str.contains(faction, case=False, na=False))

        if force_weapon:
            mask &= df[type_col].astype(str).str.contains("Weapon", case=False, na=False)
        if force_one_handed:
            mask &= (~df[grip_col].astype(str).str.contains("Two-handed", case=False, na=False))
        if exclude_ranged:
            mask &= (~df[meta_col].astype(str).str.contains("Pouch|Quiver", case=False, na=False))

        pool = df[mask & (df[rarity_col] == rank_info["required_rarity"])].copy()
        if pool.empty:
            pool = df[mask & (df[rarity_col] == "Common")].copy()
        if pool.empty:
            return "Empty"

        # Apply unique toggles
        pool = pool[pool.apply(lambda r: _is_allowed_unique(r[long_name_col], r[rarity_col], enabled_map), axis=1)]
        if pool.empty:
            return "Empty"

        return str(pool[long_name_col].sample().item())

    def mandatory_supplement_check(item_name: str, my_box: Dict[str, object], enabled_map: Dict[str, int]) -> Dict[str, object]:
        df = FrameG
        item_row = df[df[df.columns[0]] == item_name]
        if item_row.empty:
            return my_box

        meta_val = str(item_row.iloc[0, 45])
        search_term = "Pouch" if "Pouch" in meta_val else "Quiver" if "Quiver" in meta_val else None
        if not search_term:
            return my_box
        if my_box.get("Supplement") != "Empty":
            return my_box

        ammo_pool = df[df.iloc[:, 6].astype(str).str.contains(search_term, case=False, na=False)]
        ammo_pool = ammo_pool[~ammo_pool.iloc[:, 0].isin(PROHIBITED_GEAR)]
        if ammo_pool.empty:
            return my_box

        # Apply unique toggles
        ammo_pool = ammo_pool[ammo_pool.apply(lambda r: _is_allowed_unique(r.iloc[0], r.iloc[1], enabled_map), axis=1)]

        target_rarity = AMMO_RULES.get(my_box.get("Rank", ""), "Common")
        final_pool = ammo_pool[ammo_pool.iloc[:, 1] == target_rarity]
        if final_pool.empty:
            final_pool = ammo_pool
        if final_pool.empty:
            return my_box

        chosen = str(final_pool[df.columns[0]].sample().item())
        my_box["Supplement"] = chosen
        my_box["Rolling_Log"].append(f"Hardcoded Supplement: {chosen} ({target_rarity})")
        return my_box

    def roll_second_gear(remaining_gold: int, rank_info: Dict[str, object], target_types: List[str], enabled_map: Dict[str, int],
                         faction: str = "Neutral", force_one_handed: bool = False, exclude_ranged: bool = False) -> Tuple[Optional[str], int]:
        df = FrameG
        current_tier_idx = RARITY_ORDER.index(str(rank_info["Highest_Rarity"]))

        while current_tier_idx >= 0:
            intended_rarity = RARITY_ORDER[current_tier_idx]
            cost = RARITY_PRICE.get(intended_rarity, 10**9)
            if cost > remaining_gold:
                current_tier_idx -= 1
                continue

            mask = (df[df.columns[3]] != "**Insert**") & (df[df.columns[3]].notna())
            mask &= (~df[df.columns[0]].isin(PROHIBITED_GEAR))
            mask &= (df.iloc[:, 44].astype(str).str.contains(f"{faction}|Neutral|Global", case=False, na=False))
            mask &= (df.iloc[:, 2].astype(str).str.contains("|".join(target_types), case=False, na=False))
            mask &= (df.iloc[:, 1] == intended_rarity)
            if exclude_ranged:
                mask &= (~df.iloc[:, 45].astype(str).str.contains("Pouch|Quiver", case=False, na=False))
            if force_one_handed:
                mask &= (~df.iloc[:, 4].astype(str).str.contains("Two-handed", case=False, na=False))

            pool = df[mask].copy()
            pool = pool[pool.apply(lambda r: _is_allowed_unique(r.iloc[0], r.iloc[1], enabled_map), axis=1)]

            if not pool.empty:
                item_name = str(pool[df.columns[0]].sample().item())
                return item_name, (remaining_gold - cost)

            current_tier_idx -= 1

        return None, remaining_gold

    def create_loadout_box(rank_name: str, faction_name: str) -> Dict[str, object]:
        return {
            "Rank": rank_name,
            "Faction": faction_name,
            "Main Hand 1": "Empty",
            "Off Hand": "Empty",
            "Supplement": "Empty",
            "Secondary Gear": "Empty",
            "Extra Gear": "Empty",
            "Rolling_Log": [],
            "Abilities": {},
        }

    def assign_gear_to_box(item_name: str, box: Dict[str, object]) -> Dict[str, object]:
        df = FrameG
        if not item_name or item_name in {"Empty", "Locked"}:
            return box
        item_row = df[df[df.columns[0]] == item_name]
        if item_row.empty:
            return box
        item_type = str(item_row.iloc[0, 2])
        craft_type = str(item_row.iloc[0, 6])
        if any(k in craft_type for k in ["Pouch", "Quiver"]):
            box["Supplement"] = item_name
        elif "Accessory" in item_type:
            box["Off Hand"] = item_name
        elif "Weapon" in item_type:
            if box["Main Hand 1"] == "Empty":
                box["Main Hand 1"] = item_name
            elif box["Off Hand"] == "Empty":
                box["Off Hand"] = item_name
        elif any(k in item_type for k in ["Armor", "Jewerly", "Jewelry"]):
            if box["Secondary Gear"] == "Empty":
                box["Secondary Gear"] = item_name
            elif box["Extra Gear"] == "Empty":
                box["Extra Gear"] = item_name
        return box

    def log_roll(box: Dict[str, object], item_name: str, method: str) -> None:
        if not item_name or item_name in {"Empty", "Locked"}:
            return
        try:
            row = FrameG[FrameG.iloc[:, 0] == item_name]
            rarity = str(row.iloc[0, 1]) if not row.empty else "Unknown"
        except Exception:
            rarity = "Unknown"
        box["Rolling_Log"].append(f"[{len(box['Rolling_Log']) + 1}] {method}: {item_name} ({rarity})")

    def fill_remaining_slots(box: Dict[str, object], gold: int, rank_info: Dict[str, object], enabled_map: Dict[str, int], faction: str) -> Tuple[Dict[str, object], int]:
        df = FrameG

        if box["Main Hand 1"] == "Empty" and gold > 0:
            affordable = _get_highest_affordable_rarity(gold)
            budget_info = {"required_rarity": affordable, "Highest_Rarity": affordable}
            needs_one_handed = box["Off Hand"] != "Empty"
            for _ in range(10):
                cand = required_gear_roll(
                    budget_info,
                    enabled_map,
                    faction=faction,
                    force_weapon=True,
                    exclude_ranged=True,
                    force_one_handed=needs_one_handed,
                )
                if cand and cand != "Empty":
                    item_row = df[df[df.columns[0]] == cand]
                    if not item_row.empty:
                        meta_val = str(item_row.iloc[0, 45])
                        if any(k in meta_val for k in ["Pouch", "Quiver"]):
                            continue
                        assign_gear_to_box(cand, box)
                        log_roll(box, cand, f"Forced Melee ({affordable})")
                        grip_val = str(item_row.iloc[0, 4])
                        if "Two-handed" in grip_val:
                            box["Off Hand"] = "Locked"
                            box["Rolling_Log"].append("Slot Locked: 2H Weapon Equipped")
                        gold = 0
                        break

        main_wep = box["Main Hand 1"]
        if main_wep not in {"Empty", "Locked"}:
            item_row = df[df[df.columns[0]] == main_wep]
            if not item_row.empty and "Two-handed" in str(item_row.iloc[0, 4]):
                box["Off Hand"] = "Locked"

        if main_wep not in {"Empty", "Locked"} and gold > 0:
            item_row = df[df[df.columns[0]] == main_wep]
            if not item_row.empty:
                trigger_val = str(item_row.iloc[0, 45])
                if any(k in trigger_val for k in ["Pouch", "Quiver"]):
                    box = mandatory_supplement_check(main_wep, box, enabled_map)
                    gold = 0
                    box["Rolling_Log"].append("Budget Cleared: Ranged Supplement Assigned.")

        for slot in ["Off Hand", "Secondary Gear"]:
            if box[slot] == "Empty" and gold >= 200:
                targets = ["Weapon", "Accessory"] if slot == "Off Hand" else ["Armor", "Jewelry"]
                item_name, new_gold = roll_second_gear(
                    gold,
                    rank_info,
                    targets,
                    enabled_map,
                    faction=faction,
                    force_one_handed=(slot == "Off Hand"),
                    exclude_ranged=True,
                )
                if item_name:
                    assign_gear_to_box(item_name, box)
                    gold = new_gold
                    log_roll(box, item_name, f"{slot} Purchase")

        return box, gold

    def generate_single_entity(rank: str, enabled_map: Dict[str, int]) -> Dict[str, object]:
        faction = faction_selector()
        rank_info = dict(RANK_CONFIG.get(rank, RANK_CONFIG["Elite"]))

        box = create_loadout_box(rank, faction)
        mandatory_item = required_gear_roll(rank_info, enabled_map, faction=faction)
        if mandatory_item and mandatory_item != "Empty":
            assign_gear_to_box(mandatory_item, box)
            log_roll(box, mandatory_item, "Mandatory Roll")
            box = mandatory_supplement_check(mandatory_item, box, enabled_map)

        gold = int(rank_info.get("extra_gold", 0))
        if box["Supplement"] != "Empty":
            gold -= 200

        box, _ = fill_remaining_slots(box, gold, rank_info, enabled_map, faction=faction)
        box["Abilities"] = generate_abilities(rank, faction)
        return box

    # ------------------------------
    # Stats and damage
    # ------------------------------

    def get_random_race(rank: str) -> str:
        race_list = FrameS.iloc[:, 2].dropna().tolist()
        if not race_list:
            return "Unknown Race"
        chosen = random.choice(race_list)
        if rank in {"Weakling", "Prime Weakling"}:
            tries = 0
            while str(chosen).strip() in PROHIBITED_WEAKLING_RACES and tries < 50:
                chosen = random.choice(race_list)
                tries += 1
        return str(chosen)

    def get_race_stat_values(race_name: str, attrs: List[str]) -> Dict[str, float]:
        race_row = FrameS[FrameS.iloc[:, 2].astype(str).str.lower() == str(race_name).lower()]
        if race_row.empty:
            return {}
        col_map = {str(c).strip().lower(): c for c in FrameS.columns}
        out: Dict[str, float] = {}
        for a in attrs:
            al = str(a).strip().lower()
            if al in col_map:
                v = race_row[col_map[al]].values[0]
                try:
                    out[a] = float(v) if pd.notnull(v) else 0.0
                except Exception:
                    out[a] = 0.0
            else:
                out[a] = 0.0
        return out

    def sum_gear_attribute_bonuses(entity: Dict[str, object], attrs: List[str]) -> Dict[str, float]:
        total = {a: 0.0 for a in attrs}
        col_map = {str(c).strip().lower(): c for c in FrameG.columns}
        for slot in ["Main Hand 1", "Off Hand", "Supplement", "Secondary Gear", "Extra Gear"]:
            item_name = entity.get(slot)
            if item_name in {"Empty", "Locked", None}:
                continue
            row = FrameG[FrameG.iloc[:, 0] == item_name]
            if row.empty:
                continue
            for a in attrs:
                al = str(a).strip().lower()
                if al in col_map:
                    v = row[col_map[al]].values[0]
                    try:
                        total[a] += float(v) if pd.notnull(v) else 0.0
                    except Exception:
                        pass
        return total

    def get_weapon_type(weapon_name: str) -> str:
        if weapon_name in {"Empty", "Locked", None}:
            return "None"
        row = FrameG[FrameG.iloc[:, 0] == weapon_name]
        if row.empty:
            return "Unknown"
        return str(row.iloc[0, 6]).strip()

    def get_scaled_weapon_damage(weapon_name: str, scaled_bonus: float, crit_mult: float) -> str:
        if weapon_name in {"Empty", "Locked", None}:
            return "0 Damage"
        row = FrameG[FrameG.iloc[:, 0] == weapon_name]
        if row.empty:
            return "Unknown Damage"
        base_dmg_str = str(row.iloc[0, 9] or "").strip()
        if not base_dmg_str or base_dmg_str.lower() == "nan":
            return "No Base Damage"

        on_hit_val = row.iloc[0, 10]
        on_hit_suffix = ""
        if pd.notnull(on_hit_val):
            on_hit_txt = str(on_hit_val).strip()
            if on_hit_txt not in {"", "nan", "None"}:
                on_hit_txt = re.sub(r"^\s*On\s*Hit\s*:\s*", "", on_hit_txt, flags=re.IGNORECASE)
                on_hit_suffix = f", On Hit: {on_hit_txt}"

        bonus = math.ceil(scaled_bonus)
        parts = [p.strip() for p in re.split(r"\s*;\s*", base_dmg_str) if p.strip()]
        out_parts: List[str] = []
        for part in parts:
            normalized = part.replace("–", "-").replace("—", "-")
            m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s+(.+?)\s*$", normalized)
            if not m:
                out_parts.append(f"{part}{f' (+{bonus})' if bonus != 0 else ''}")
                continue
            mn = int(m.group(1))
            mx = int(m.group(2)) if m.group(2) else mn
            dmg_type = m.group(3).strip()
            new_mn = mn + bonus
            new_mx = mx + bonus
            c_mn = math.ceil(new_mn * crit_mult)
            c_mx = math.ceil(new_mx * crit_mult)
            if new_mn == new_mx:
                out_parts.append(f"{new_mn} {dmg_type} [Crit: {c_mn}]")
            else:
                out_parts.append(f"{new_mn}-{new_mx} {dmg_type} [Crit: {c_mn}-{c_mx}]")

        return " + ".join(out_parts) + on_hit_suffix

    def _parse_number_like(val) -> Optional[float]:
        """Parse a float from a cell that may be numeric or text like '+0.5 Crit multiplier'."""
        if val is None:
            return None
        try:
            # pandas may give NaN floats
            if isinstance(val, float) and math.isnan(val):
                return None
        except Exception:
            pass
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        s = str(val).strip()
        if not s or s.lower() == "nan":
            return None
        m = re.search(r"([+-]?\d+(?:\.\d+)?)", s)
        if not m:
            return None
        try:
            return float(m.group(1))
        except Exception:
            return None

    def _apply_item_crit_bonus(item_row: pd.DataFrame, base_crit: float) -> float:
        """Return crit multiplier including item-specific bonus from Gear column or name text.

        Rules:
        - If Gear column 'Critical Multiplier' exists and is filled, use that value.
        - Otherwise, try to parse '+X Critical Multiplier' from the item's display text.
        - If parsed value looks like a *bonus* (abs <= 1.5), add it to base_crit.
          If it looks like an absolute multiplier (> 1.5), treat it as the full multiplier.
        """
        if item_row is None or getattr(item_row, "empty", True):
            return float(base_crit or 1.0)

        crit_col = None
        for c in item_row.columns:
            if str(c).strip().lower() == "critical multiplier":
                crit_col = c
                break

        parsed: Optional[float] = None
        if crit_col is not None:
            parsed = _parse_number_like(item_row.iloc[0][crit_col])

        # Fallback: parse from the item's full text (Final Name)
        if parsed is None:
            txt = str(item_row.iloc[0, 0] or "")
            m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:crit|critical)\s*mult", txt, flags=re.I)
            if m:
                try:
                    parsed = float(m.group(1))
                except Exception:
                    parsed = None

        if parsed is None:
            return float(base_crit or 1.0)

        # Heuristic: small numbers are bonuses, big numbers are absolute multipliers
        if abs(parsed) <= 1.5:
            return float(base_crit or 1.0) + float(parsed)
        return float(parsed)

    def get_full_loadout_report(entity: Dict[str, object]):
        report = {"Slots": {}}
        for slot in ["Main Hand 1", "Off Hand"]:
            item_name = entity.get(slot, "Empty")
            if item_name in {"Empty", "Locked", None}:
                report["Slots"][slot] = {"Item": item_name, "Type": "None", "Attributes": [], "ScalingString": "None", "Crit": 1.0}
                continue

            row = FrameG[FrameG.iloc[:, 0] == item_name]
            if row.empty:
                report["Slots"][slot] = {"Item": item_name, "Type": "Unknown", "Attributes": [], "ScalingString": "None", "Crit": 1.0}
                continue

            item_type = str(row.iloc[0, 2]).strip()
            grip_type = str(row.iloc[0, 4]).strip()
            weapon_type = get_weapon_type(item_name)
            stats = scaling_dict.get(weapon_type)
            scaling_str = stats.scaling if stats else "1 Strength"
            crit_mult = float(stats.crit_mult) if stats else 1.0
            crit_mult = _apply_item_crit_bonus(row, crit_mult)
            mult = _extract_scaling_multiplier(scaling_str)

            if "Weapon" in item_type:
                # Your requested rules:
                if weapon_type == "Sword":
                    if "Two-handed" in grip_type:
                        required_attrs = ["Dexterity", "Strength"]
                        scaling_str = f"{mult} Dexterity & Strength"
                    else:
                        required_attrs = ["Dexterity"]
                        scaling_str = f"{mult} Dexterity"
                elif weapon_type == "Spear":
                    if "Two-handed" in grip_type:
                        required_attrs = ["Strength", "Dexterity"]
                        scaling_str = f"{mult} Strength & Dexterity"
                    else:
                        required_attrs = ["Strength"]
                        scaling_str = f"{mult} Strength"
                elif weapon_type == "Staff":
                    required_attrs = ["Highest_Str_Pow"]
                    scaling_str = f"{mult} Strength or Power"
                else:
                    # fallback parser
                    ss = str(scaling_str).lower()
                    if "highest attribute" in ss:
                        required_attrs = ["Highest"]
                    else:
                        required_attrs = []
                        if "strength" in ss:
                            required_attrs.append("Strength")
                        if "dexterity" in ss:
                            required_attrs.append("Dexterity")
                        if "power" in ss:
                            required_attrs.append("Power")
                        if not required_attrs:
                            required_attrs = ["Unknown"]

                report["Slots"][slot] = {
                    "Item": item_name,
                    "Type": weapon_type,
                    "Attributes": required_attrs,
                    "ScalingString": scaling_str,
                    "Crit": crit_mult,
                }
            else:
                report["Slots"][slot] = {"Item": item_name, "Type": item_type, "Attributes": [], "ScalingString": "None", "Crit": 1.0}

        if report["Slots"].get("Main Hand 1", {}).get("Item") in {"Empty", "Locked", None}:
            report["Slots"]["Main Hand 1"] = {
                "Item": "Fists",
                "Type": "Unarmed",
                "Attributes": ["Highest"],
                "ScalingString": "1.0 Highest Attribute",
                "Crit": 1.5,
            }
        return report

    def build_result(rank: str) -> Dict[str, object]:
        if missing:
            return {"error": f"Missing Excel sheets: {', '.join(missing)}"}

        enabled_map = _load_unique_enabled_map(get_db)
        entity = generate_single_entity(rank, enabled_map)
        entity["Race"] = get_random_race(rank)

        vital_stats = ["Health", "Mana", "Defense", "Dispersion"]
        aux_stats = ["Mobility", "Might", "Wisdom"]
        res_stats = [
            "LIGHT RESISTANCE", "DARK RESISTANCE", "FIRE RESISTANCE", "FROST RESISTANCE",
            "WIND RESISTANCE", "EARTH RESISTANCE", "LIGHTNING RESISTANCE", "BLEED RESISTANCE", "POISON RESISTANCE",
        ]
        atk_stats = ["Strength", "Dexterity", "Power"]

        gear_def = sum_gear_attribute_bonuses(entity, vital_stats + res_stats)
        race_def = get_race_stat_values(entity["Race"], vital_stats + res_stats)
        gear_aux = sum_gear_attribute_bonuses(entity, aux_stats)
        gear_atk = sum_gear_attribute_bonuses(entity, atk_stats)
        race_atk = get_race_stat_values(entity["Race"], atk_stats)

        # Rank modifiers (HP/Mana)
        rank_mod = {
            "Weakling": (0.50, 1.0),
            "Prime Weakling": (0.75, 1.0),
            "Elite": (1.0, 1.0),
            "Prime Elite": (1.25, 1.0),
            "Boss": (3.0, 2.0),
            "Prime Boss": (4.0, 2.5),
            "Guardian": (5.0, 3.0),
        }
        hp_mult, mana_mult = rank_mod.get(rank, (1.0, 1.0))
        if "Health" in race_def:
            race_def["Health"] = float(race_def.get("Health", 0.0)) * hp_mult
        if "Mana" in race_def:
            race_def["Mana"] = float(race_def.get("Mana", 0.0)) * mana_mult

        # Damage
        combat = get_full_loadout_report(entity)
        main = combat["Slots"]["Main Hand 1"]
        weapon_item = main["Item"]
        needs = main["Attributes"]
        scaling_str = main["ScalingString"]
        mult = _extract_scaling_multiplier(scaling_str)
        main_crit = float(main.get("Crit", 1.0))

        raw_pool = 0.0
        if "Highest_Str_Pow" in needs:
            str_total = race_atk.get("Strength", 0.0) + gear_atk.get("Strength", 0.0)
            pow_total = race_atk.get("Power", 0.0) + gear_atk.get("Power", 0.0)
            raw_pool = max(str_total, pow_total)
        elif "Highest" in needs:
            raw_pool = max([race_atk.get(s, 0.0) + gear_atk.get(s, 0.0) for s in atk_stats])
        else:
            for s in needs:
                if s in {"Strength", "Dexterity", "Power"}:
                    raw_pool += race_atk.get(s, 0.0) + gear_atk.get(s, 0.0)

        final_scaling_bonus = raw_pool * mult
        if weapon_item == "Fists":
            highest_stat = max([race_atk.get(s, 0.0) + gear_atk.get(s, 0.0) for s in atk_stats])
            main_dmg = f"{int(highest_stat)} Physical [Crit: {math.ceil(highest_stat * 1.5)}]"
        else:
            main_dmg = get_scaled_weapon_damage(weapon_item, final_scaling_bonus, main_crit)

        # Off-hand
        off = combat["Slots"]["Off Hand"]
        off_item = off.get("Item", "Empty")
        off_type = off.get("Type", "None")
        off_crit = float(off.get("Crit", 1.0))
        off_dmg = None
        if off_item not in {"Empty", "Locked", None}:
            total_str = race_atk.get("Strength", 0.0) + gear_atk.get("Strength", 0.0)
            total_dex = race_atk.get("Dexterity", 0.0) + gear_atk.get("Dexterity", 0.0)
            if off_type == "Sword":
                off_dmg = get_scaled_weapon_damage(off_item, math.ceil(total_dex * 0.5), off_crit)
            elif off_type == "Axe":
                off_dmg = get_scaled_weapon_damage(off_item, math.ceil(total_str * 0.5), off_crit)
            else:
                off_dmg = get_scaled_weapon_damage(off_item, 0, off_crit)

        # Conditions (from race sheet col 5)
        conditions = "None"
        try:
            rrow = FrameS[FrameS.iloc[:, 2].astype(str).str.lower() == str(entity["Race"]).lower()]
            if not rrow.empty:
                cval = rrow.iloc[0, 5]
                if pd.notnull(cval) and str(cval).strip():
                    conditions = str(cval).strip()
        except Exception:
            pass

        intel_roll = random.randint(1, 20)
        intel_label = _intelligence_label(intel_roll)

        stats: Dict[str, float] = {}
        for k in vital_stats:
            stats[k] = float(race_def.get(k, 0.0) + gear_def.get(k, 0.0))
        for k in aux_stats:
            stats[k] = float(gear_aux.get(k, 0.0))
        for k in atk_stats:
            stats[k] = float(race_atk.get(k, 0.0) + gear_atk.get(k, 0.0))

        resists: Dict[str, int] = {}
        for r in res_stats:
            base = float(race_def.get(r, 0.0))
            bonus = float(gear_def.get(r, 0.0))
            b = int(base * 100) if 0 < abs(base) <= 1.0 else int(base)
            g = int(bonus * 100) if 0 < abs(bonus) <= 1.0 else int(bonus)
            label = r.replace(" RESISTANCE", "").title()
            resists[label] = b + g

        gear_slots = {
            "Main Hand 1": entity.get("Main Hand 1"),
            "Off Hand": entity.get("Off Hand"),
            "Supplement": entity.get("Supplement"),
            "Secondary Gear": entity.get("Secondary Gear"),
            "Extra Gear": entity.get("Extra Gear"),
        }

        return {
            "rank": rank,
            "faction": entity.get("Faction"),
            "race": entity.get("Race"),
            "conditions": conditions,
            "intelligence_roll": intel_roll,
            "intelligence_label": intel_label,
            "main_hand_damage": main_dmg,
            "off_hand_damage": off_dmg,
            "stats": stats,
            "resists": resists,
            "gear": gear_slots,
            "abilities": entity.get("Abilities", {}),
            "rolling_log": entity.get("Rolling_Log", []),
        }

    @app.route("/sentient-generator", methods=["GET", "POST"])
    @_login_required
    def sentient_generator_page():
        selected_rank = request.form.get("rank") if request.method == "POST" else "Elite"
        if selected_rank not in RANKS:
            selected_rank = "Elite"

        result = None
        error = None
        if request.method == "POST":
            try:
                result = build_result(selected_rank)
                if isinstance(result, dict) and result.get("error"):
                    error = result["error"]
                    result = None
            except Exception as e:
                error = f"Sentient generator error: {e}"
                result = None

        return render_template(
            "sentient_generator.html",
            ranks=RANKS,
            selected_rank=selected_rank,
            result=result,
            error=error,
        )
