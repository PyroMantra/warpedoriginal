import random
import re
import itertools
import math
from typing import List, Dict, Set, Optional, Tuple
import pandas as pd

# ==========================================
# --- 1. FILE PATHS & CONFIGURATION ---
# ==========================================
excel_file_path = r"data\Layer List (7).xlsx"
scaling_csv_path = r"static\notion\Scaling.csv"

# --- BANNED GEAR LIST ---
PROHIBITED_GEAR = [
    "Insert Broken Item Name",
    "Debug Sword",
    "God Mode Armor"
]

# --- AMMO RULES ---
AMMO_RULES = {
    "Weakling": "Common",
    "Prime Weakling": "Common",
    "Elite": "Uncommon",
    "Prime Elite": "Uncommon",
    "Boss": "Rare",
    "Prime Boss": "Epic",
    "Guardian": "Legendary"
}

# --- PROHIBITED WEAKLING RACES ---
# These races are too powerful/rare to spawn as low-level Weaklings
PROHIBITED_WEAKLING_RACES = [
    "Patagan",
    "Steam Walker"
]

# ==========================================
# --- 2. SENTIENT SELECTOR & VALUES ---
# ==========================================
def sentientselector():
    sentientlist = ["Guardian"]
    return random.choice(sentientlist)

def get_sentient_value(sentient_type):
    """
    Takes a sentient rank as a string and returns its numerical value.
    Returns 0 if the rank is not found.
    """
    rank_values = {
        "Weakling": 1,
        "Prime Weakling": 2,
        "Elite": 4,
        "Prime Elite": 5,
        "Boss": 6,
        "Prime Boss": 7,
        "Guardian": 8
    }
    return rank_values.get(sentient_type, 0)


# ==========================================
# --- 3. DATA LOADING & DATAFRAMES ---
# ==========================================
def load_scaling_data(csv_path):
    """Reads the Scaling CSV and returns a dictionary formatted for combat math."""
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Error: Scaling file not found at '{csv_path}'")
        return {}

    new_scaling_dict = {}
    for index, row in df.iterrows():
        weapon_type = str(row.iloc[0]).strip()
        if pd.isna(row.iloc[0]) or weapon_type == "" or weapon_type.lower() == "nan":
            continue
        try:
            crit_mult = float(row.iloc[2])
        except (ValueError, TypeError):
            crit_mult = 1.0
        scaling_str = str(row.iloc[3]).strip()
        if pd.isna(row.iloc[3]) or scaling_str.lower() == "nan":
            scaling_str = "None"
        new_scaling_dict[weapon_type] = {
            'Scaling': scaling_str,
            'Critical Multiplier': crit_mult
        }
    return new_scaling_dict

try:
    # Gear and Races Sheets
    FrameG = pd.read_excel(excel_file_path, sheet_name="Gear")
    FrameR = pd.read_excel(excel_file_path, sheet_name="Races")
    # For compatibility where FrameS was used for Races
    FrameS = FrameR 

    # Ability Sheets
    Frame1 = pd.read_excel(excel_file_path, sheet_name="Bandits")
    Frame2 = pd.read_excel(excel_file_path, sheet_name="Legion")
    Frame3 = pd.read_excel(excel_file_path, sheet_name="Conclave")
except FileNotFoundError:
    print(f"Error: Excel file not found at '{excel_file_path}'")
    exit()
except ValueError as e:
    print(f"Error loading sheets: {e}")
    exit()

# Create the dictionary once when the script starts!
MASTER_SCALING_DICT = load_scaling_data(scaling_csv_path)


# ==========================================
# --- 4. ABILITIES LOGIC ---
# ==========================================
def sum_to_n_with_max3(n):
    # This function takes an input integer and splits into 3 integers that add up to n with a max of 3.
    elements = [list(t) for t in itertools.product(range(1, 4), repeat=3) if sum(t) == n]
    if not elements:
        raise ValueError(f"No combination of three integers <= 3 sums to {n}.")
    return random.choice(elements)

def ability_search(x, y, frame):
    """Plugs in coordinates X and Y to get an ability from the specified frame."""
    try:
        element = frame.iat[x - 1, y - 1]
        return str(element).strip()
    except IndexError:
        return "Unknown Ability"

def generate_abilities(rank, faction):
    """
    Selects the correct ability frame based on faction, rolls the abilities, 
    and checks the sentient value to see if they unlock an Ultimate.
    """
    # 1. Map Faction to the correct Frame
    if faction == "Bandit":
        selected_frame = Frame1
    elif faction == "Legion":
        selected_frame = Frame2
    elif faction == "Conclave":
        selected_frame = Frame3
    else:
        selected_frame = Frame1 # Default fallback

    # 2. Define the row ranges
    RangeInate = range(4, 11)
    RangeTeir1 = range(11, 19)
    RangeTeir2 = range(19, 28)
    RangeTeir3 = range(28, 34)
    RangeTeir4 = range(34, 42)

    abilities = {}
    sentient_level = get_sentient_value(rank)

    # Pathway A: Weakling (Only Innate)
    if rank == "Weakling":
        abilities["Innate"] = ability_search(random.choice(RangeInate), 1, selected_frame)

    # Pathway B: Prime Weakling (Innate + Tier 1)
    elif rank == "Prime Weakling":
        abilities["Innate"] = ability_search(random.choice(RangeInate), 1, selected_frame)
        abilities["Tier 1"] = ability_search(random.choice(RangeTeir1), 1, selected_frame)

    # Pathway C: Elite or Higher (Full Math Split)
    else:
        mylist = sum_to_n_with_max3(sentient_level)
        abilities["Innate"] = ability_search(random.choice(RangeInate), 1, selected_frame)
        abilities["Tier 1"] = ability_search(random.choice(RangeTeir1), mylist[0], selected_frame)
        abilities["Tier 2"] = ability_search(random.choice(RangeTeir2), mylist[1], selected_frame)
        abilities["Tier 3"] = ability_search(random.choice(RangeTeir3), mylist[2], selected_frame)

        # Ultimate Checks
        if 5 < sentient_level < 12:
            abilities["Ultimate"] = ability_search(random.choice(RangeTeir4), 1, selected_frame)
        elif sentient_level == 12:
            abilities["Ultimate"] = ability_search(random.choice(RangeTeir4), 2, selected_frame)

    return abilities


# ==========================================
# --- 5. GEAR GENERATION FUNCTIONS ---
# ==========================================
def Faction_Selector():
    factions = ["Conclave", "Legion", "Bandit"]
    return random.choice(factions)

def Sentient_Loot_Table(rank):
    RANK_CONFIG: Dict[str, Dict[str, int]] = {
        "Weakling": {"required_rarity": "Common", "extra_gold": 200, "Highest_Rarity": "Common"},
        "Prime Weakling": {"required_rarity": "Uncommon", "extra_gold": 200, "Highest_Rarity": "Common"},
        "Elite": {"required_rarity": "Rare", "extra_gold": 400 , "Highest_Rarity": "Uncommon"},
        "Prime Elite": {"required_rarity": "Epic", "extra_gold": 400, "Highest_Rarity": "Uncommon"},
        "Boss": {"required_rarity": "Legendary", "extra_gold": 600, "Highest_Rarity": "Rare"},
        "Prime Boss": {"required_rarity": "Legendary", "extra_gold": 800, "Highest_Rarity": "Epic"},
        "Guardian": {"required_rarity": "Mythic", "extra_gold": 1000, "Highest_Rarity": "Legendary"}
    }
    return RANK_CONFIG[rank]

def get_highest_affordable_rarity(current_gold):
    prices = {
        "Mythic": 2000, "Legendary": 1000, "Epic": 800,
        "Rare": 600, "Uncommon": 400, "Common": 200
    }
    for rarity, cost in prices.items():
        if current_gold >= cost:
            return rarity
    return "None (Too Poor)"

def Required_Gear_Roll(rank_info, faction="Neutral", force_weapon=False, force_one_handed=False, exclude_ranged=False):
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

    pool = df[mask & (df[rarity_col] == rank_info['required_rarity'])]

    if pool.empty:
        pool = df[mask & (df[rarity_col] == "Common")]
        
    if pool.empty:
        return "Empty"

    return pool[long_name_col].sample().item()

def mandotorysupplentcheck(item_name, my_box, info_dict=None, faction="Neutral"):
    df = FrameG
    item_row = df[df[df.columns[0]] == item_name]
    if item_row.empty:
        return my_box

    meta_val = str(item_row.iloc[0, 45])
    search_term = "Pouch" if "Pouch" in meta_val else "Quiver" if "Quiver" in meta_val else None

    if search_term and my_box["Supplement"] == "Empty":
        ammo_pool = df[df.iloc[:, 6].astype(str).str.contains(search_term, case=False, na=False)]
        ammo_pool = ammo_pool[~ammo_pool.iloc[:, 0].isin(PROHIBITED_GEAR)]

        if not ammo_pool.empty:
            target_rarity = AMMO_RULES.get(my_box["Rank"], "Common")
            final_pool = ammo_pool[ammo_pool.iloc[:, 1] == target_rarity]

            if final_pool.empty:
                final_pool = ammo_pool

            chosen_ammo = final_pool[df.columns[0]].sample().item()
            my_box["Supplement"] = chosen_ammo
            my_box["Rolling_Log"].append(f"Hardcoded Supplement: {chosen_ammo} ({target_rarity})")

    return my_box

def Roll_Second_Gear(remaining_gold, rank_info, target_types, faction="Neutral", force_one_handed=False, exclude_ranged=False):
    rarity_order = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]
    prices = {"Mythic": 2000, "Legendary": 1000, "Epic": 800, "Rare": 600, "Uncommon": 400, "Common": 200}

    current_tier_idx = rarity_order.index(rank_info["Highest_Rarity"])

    while current_tier_idx >= 0:
        intended_rarity = rarity_order[current_tier_idx]
        current_item_cost = prices[intended_rarity]

        if current_item_cost > remaining_gold:
            current_tier_idx -= 1
            continue

        final_rarity = intended_rarity
        downgraded = False

        rank_name = rank_info.get("Rank", "Unknown")
        is_weakling = rank_name in ["Weakling", "Prime Weakling"]

        if intended_rarity != "Common" and not is_weakling and random.random() <= 0.6:
            final_rarity = rarity_order[current_tier_idx - 1]
            downgraded = True

        df = FrameG
        mask = (df[df.columns[3]] != "**Insert**") & (df[df.columns[3]].notna())
        mask &= (~df[df.columns[0]].isin(PROHIBITED_GEAR))
        mask &= (df.iloc[:, 44].astype(str).str.contains(f"{faction}|Neutral|Global", case=False, na=False))
        mask &= (df.iloc[:, 2].astype(str).str.contains('|'.join(target_types), case=False, na=False))
        mask &= (df.iloc[:, 1] == final_rarity)

        if exclude_ranged:
            mask &= (~df.iloc[:, 45].astype(str).str.contains("Pouch|Quiver", case=False, na=False))
        if force_one_handed:
            mask &= (~df.iloc[:, 4].astype(str).str.contains("Two-handed", case=False, na=False))

        pool = df[mask]

        if not pool.empty:
            item_name = pool[df.columns[0]].sample().item()
            extra_item = None

            if downgraded:
                extra_mask = (df[df.columns[3]] != "**Insert**") & (df[df.columns[3]].notna())
                extra_mask &= (~df[df.columns[0]].isin(PROHIBITED_GEAR))
                extra_mask &= (df.iloc[:, 44].astype(str).str.contains(f"{faction}|Neutral|Global", case=False, na=False))
                extra_mask &= (df.iloc[:, 2].astype(str).str.contains('Armor|Jewelry|Jewerly', case=False, na=False))
                extra_mask &= (df.iloc[:, 1] == "Common")
                extra_pool = df[extra_mask]

                if not extra_pool.empty:
                    extra_item = extra_pool[df.columns[0]].sample().item()

            return (item_name, extra_item), (remaining_gold - current_item_cost)

        current_tier_idx -= 1

    return None, remaining_gold

def Create_Loadout_Box(rank_name="Unknown Entity", faction_name="Neutral"):
    return {
        "Rank": rank_name,
        "Faction": faction_name,
        "Main Hand 1": "Empty",
        "Off Hand": "Empty",
        "Supplement": "Empty",
        "Secondary Gear": "Empty",
        "Extra Gear": "Empty", 
        "Abilities": {},
        "Rolling_Log": []
    }

def log_roll(my_box, item_name, method_name):
    if item_name and item_name not in ["Empty", "Locked"]:
        df = FrameG
        item_row = df[df[df.columns[0]] == item_name]
        rarity = item_row.iloc[0, 1] if not item_row.empty else "Unknown"
        entry = f"[{len(my_box['Rolling_Log']) + 1}] {method_name}: {item_name} ({rarity})"
        my_box["Rolling_Log"].append(entry)
    return my_box

def check_bundle_affordability(item_name, remaining_gold):
    df = FrameG
    prices = {"Mythic": 2000, "Legendary": 1000, "Epic": 800, "Rare": 600, "Uncommon": 400, "Common": 200}

    item_row = df[df[df.columns[0]] == item_name]
    if item_row.empty:
        return False, 0

    rarity = item_row.iloc[0, 1]
    base_cost = prices.get(rarity, 200)

    meta_val = str(item_row.iloc[0, 44])
    needs_ammo = any(k in meta_val for k in ["Pouch", "Quiver"])

    total_cost = base_cost + (200 if needs_ammo else 0)
    return remaining_gold >= total_cost, total_cost

def Assign_Gear_To_Box(rolled_items, loadout_box):
    if rolled_items is None:
        return loadout_box

    if isinstance(rolled_items, (list, tuple)):
        items_to_process = rolled_items
    else:
        items_to_process = [rolled_items]

    df = FrameG
    long_name_col = df.columns[0]

    for item_name in items_to_process:
        if not item_name or isinstance(item_name, float):
            continue

        clean_name = str(item_name).strip()
        if clean_name in ["None", "Empty", "Locked", ""]:
            continue

        item_row = df[df[long_name_col] == clean_name]
        if item_row.empty or len(item_row.columns) < 7:
            continue

        try:
            item_type = str(item_row.iloc[0, 2])
            craft_type = str(item_row.iloc[0, 6])
        except IndexError:
            continue

        if any(k in craft_type for k in ["Pouch", "Quiver"]):
            loadout_box["Supplement"] = clean_name
        elif "Accessory" in item_type:
            loadout_box["Off Hand"] = clean_name
        elif "Weapon" in item_type:
            if loadout_box["Main Hand 1"] == "Empty":
                loadout_box["Main Hand 1"] = clean_name
            elif loadout_box["Off Hand"] == "Empty":
                loadout_box["Off Hand"] = clean_name
        elif any(k in item_type for k in ["Armor", "Jewerly", "Jewelry"]):
            if loadout_box["Secondary Gear"] == "Empty":
                loadout_box["Secondary Gear"] = clean_name
            elif loadout_box.get("Extra Gear", "Empty") == "Empty":
                loadout_box["Extra Gear"] = clean_name

    return loadout_box

def Fill_Remaining_Slots(my_box, remaining_gold, rank_info, faction="Neutral"):
    df = FrameG

    if my_box["Main Hand 1"] == "Empty" and remaining_gold > 0:
        affordable_tier = get_highest_affordable_rarity(remaining_gold)
        budget_info = {"required_rarity": affordable_tier}

        needs_one_handed = my_box["Off Hand"] != "Empty"

        for attempt in range(1, 11):
            wep_candidate = Required_Gear_Roll(
                budget_info,
                faction=faction,
                force_weapon=True,
                exclude_ranged=True,
                force_one_handed=needs_one_handed
            )

            if wep_candidate and wep_candidate != "Empty":
                item_row = df[df[df.columns[0]] == wep_candidate]
                if not item_row.empty:
                    meta_val = str(item_row.iloc[0, 45])
                    if any(k in meta_val for k in ["Pouch", "Quiver"]):
                        continue

                    my_box = Assign_Gear_To_Box(wep_candidate, my_box)
                    my_box = log_roll(my_box, wep_candidate, f"Forced Melee ({affordable_tier})")

                    grip_val = str(item_row.iloc[0, 4])
                    if "Two-handed" in grip_val:
                        my_box["Off Hand"] = "Locked"
                        my_box["Rolling_Log"].append("Slot Locked: 2H Weapon Equipped")

                    remaining_gold = 0
                    my_box["Rolling_Log"].append(f"Budget Cleared: {affordable_tier} weapon secured after {attempt} attempts.")
                    break

    main_wep = my_box["Main Hand 1"]
    if main_wep not in ["Empty", "Locked"]:
        item_row = df[df[df.columns[0]] == main_wep]
        if not item_row.empty and "Two-handed" in str(item_row.iloc[0, 4]):
            my_box["Off Hand"] = "Locked"

    if main_wep not in ["Empty", "Locked"] and remaining_gold > 0:
        item_row = df[df[df.columns[0]] == main_wep]
        if not item_row.empty:
            trigger_val = str(item_row.iloc[0, 45])
            if any(k in trigger_val for k in ["Pouch", "Quiver"]):
                my_box = mandotorysupplentcheck(main_wep, my_box, info_dict=rank_info, faction=faction)
                remaining_gold = 0
                my_box["Rolling_Log"].append("Budget Cleared: Ranged Supplement Assigned.")

    for slot in ["Off Hand", "Secondary Gear"]:
        if my_box[slot] == "Empty" and remaining_gold >= 200:
            targets = ["Weapon", "Accessory"] if slot == "Off Hand" else ["Armor", "Jewelry"]

            res, new_gold = Roll_Second_Gear(
                remaining_gold, rank_info, targets,
                faction=faction,
                force_one_handed=(slot == "Off Hand"),
                exclude_ranged=True
            )

            if res and isinstance(res, tuple):
                primary_item = res[0]
                bonus_item = res[1]
                
                if primary_item:
                    my_box = Assign_Gear_To_Box(primary_item, my_box)
                    remaining_gold = new_gold
                    my_box = log_roll(my_box, primary_item, f"{slot} Purchase")

                if bonus_item:
                    my_box = Assign_Gear_To_Box(bonus_item, my_box)
                    my_box = log_roll(my_box, bonus_item, f"Downgrade Bonus (Extra Armor/Jewelry)")

    return my_box, remaining_gold

def generate_single_entity():
    rank = sentientselector()  
    faction = Faction_Selector()
    rank_info = Sentient_Loot_Table(rank)

    my_box = Create_Loadout_Box(rank, faction)
    mandatory_item = Required_Gear_Roll(rank_info, faction=faction)
    
    if mandatory_item and mandatory_item != "Empty":
        my_box = Assign_Gear_To_Box(mandatory_item, my_box)
        my_box = log_roll(my_box, mandatory_item, "Mandatory Roll")
        my_box = mandotorysupplentcheck(mandatory_item, my_box, rank_info, faction=faction)

    starting_gold = rank_info['extra_gold']
    if my_box["Supplement"] != "Empty":
        starting_gold -= 200

    my_box, _ = Fill_Remaining_Slots(my_box, starting_gold, rank_info, faction=faction)
    
    # Generate Abilities
    my_box["Abilities"] = generate_abilities(rank, faction)
    
    return my_box

# ==========================================
# --- 6. STAT & COMBAT CALCULATIONS ---
# ==========================================
def get_random_race(rank="Unknown"):
    race_list = FrameS.iloc[:, 2].dropna().tolist()
    if not race_list:
        return "Unknown Race"
        
    chosen_race = random.choice(race_list)
    
    # --- PROHIBITED RACES FILTER ---
    if rank in ["Weakling", "Prime Weakling"]:
        while chosen_race.strip() in PROHIBITED_WEAKLING_RACES:
            chosen_race = random.choice(race_list)
            
    return chosen_race

def get_race_stat_values(race_name, attribute_list):
    race_row = FrameS[FrameS.iloc[:, 2].str.lower() == race_name.lower()]
    if race_row.empty: return {}
    
    # Nukes invisible spaces and ignores capitalization
    col_map = {str(c).strip().lower(): c for c in FrameS.columns}
    
    results = {}
    for attr in attribute_list:
        if attr == "Highest":
            results[attr] = 0
            continue
        attr_lower = str(attr).strip().lower()
        if attr_lower in col_map:
            results[attr] = race_row[col_map[attr_lower]].values[0]
        else:
            results[attr] = 0
    return results

def get_weapon_type_from_excel(weapon_name):
    if weapon_name in ["Empty", "Locked", None]: return "None"
    match = FrameG[FrameG.iloc[:, 0] == weapon_name]
    return str(match.iloc[0, 6]).strip() if not match.empty else "Unknown Type"

def weapon_attributes(gear_type):
    return MASTER_SCALING_DICT.get(gear_type)

def extract_primary_attributes(scaling_string):
    if not scaling_string or not isinstance(scaling_string, str): return []
    search_str = scaling_string.lower()
    if "highest attribute" in search_str: return ["Highest"]
    possible_attributes = {"strength": "Strength", "dexterity": "Dexterity", "power": "Power"}
    found = [proper for low, proper in possible_attributes.items() if low in search_str]
    return found if found else ["Unknown"]

def extract_scaling_multiplier(scaling_str):
    if not scaling_str: return 1.0
    match = re.search(r'([0-9.]+)', str(scaling_str))
    if match:
        return float(match.group(1))
    return 1.0

def sum_gear_attribute_bonuses(entity_data, scaling_list):
    total_bonuses = {attr: 0 for attr in scaling_list if attr != "Highest"}
    gear_loadout = entity_data.get('Gear', entity_data)
    
    # Nukes invisible spaces and ignores capitalization
    col_map = {str(c).strip().lower(): c for c in FrameG.columns}
    
    target_slots = ['Main Hand 1', 'Off Hand', 'Supplement', 'Secondary Gear', 'Extra Gear']
    
    for slot in target_slots:
        item_name = gear_loadout.get(slot)
        if item_name in ["Empty", "Locked", None]: continue
        item_data = FrameG[FrameG.iloc[:, 0] == item_name]
        if not item_data.empty:
            for attr in total_bonuses.keys():
                attr_lower = str(attr).strip().lower()
                if attr_lower in col_map:
                    val = item_data[col_map[attr_lower]].values[0]
                    if pd.notnull(val): 
                        try:
                            total_bonuses[attr] += float(val)
                        except ValueError:
                            pass
    return total_bonuses

def get_scaled_weapon_damage(weapon_name, scaled_bonus, crit_mult=1.0):
    if weapon_name in ["Empty", "Locked", None]: return "0 Damage"
    weapon_row = FrameG[FrameG.iloc[:, 0] == weapon_name]
    if weapon_row.empty: return "Unknown Damage"

    base_dmg_str = str(weapon_row.iloc[0, 9])
    if base_dmg_str == "nan" or base_dmg_str.strip() == "":
        return "No Base Damage"

    on_hit_val = weapon_row.iloc[0, 10]
    on_hit_suffix = ""
    if pd.notnull(on_hit_val) and str(on_hit_val).strip() not in ["", "nan", "None"]:
        on_hit_suffix = f", On Hit: {str(on_hit_val).strip()}"

    # --- MULTI-DAMAGE SPLIT FIX ---
    # Splits the string at the semicolon if there are multiple damage types
    damage_components = base_dmg_str.split(';')
    final_damage_strings = []

    for component in damage_components:
        component = component.strip()
        match = re.match(r"(\d+)(?:-(\d+))?\s+(.*)", component)

        if match:
            min_dmg = int(match.group(1))
            max_dmg = int(match.group(2)) if match.group(2) else min_dmg
            damage_type = match.group(3).strip()

            # Apply the scaling bonus to THIS specific damage type
            new_min = min_dmg + math.ceil(scaled_bonus)
            new_max = max_dmg + math.ceil(scaled_bonus)

            # Calculate Crit for THIS specific damage type
            crit_min = math.ceil(new_min * crit_mult)
            crit_max = math.ceil(new_max * crit_mult)

            if new_min == new_max:
                final_damage_strings.append(f"{new_min} {damage_type} [Crit: {crit_min}]")
            else:
                final_damage_strings.append(f"{new_min}-{new_max} {damage_type} [Crit: {crit_min}-{crit_max}]")
        else:
            # Fallback for weirdly formatted text
            final_damage_strings.append(f"{component} (+{math.ceil(scaled_bonus)})")

    # Rejoin all the scaled damage types together with a " + " sign
    combined_damage = " + ".join(final_damage_strings)

    return f"{combined_damage}{on_hit_suffix}"
def get_full_loadout_report(entity_data):
    race_name = entity_data.get('Race', 'Unknown')
    report = {
        "Rank": entity_data.get('Rank'),
        "Faction": entity_data.get('Faction'),
        "Race": race_name,
        "Slots": {}
    }

    slots_to_check = ['Main Hand 1', 'Off Hand']

    for slot in slots_to_check:
        item_name = entity_data.get('Gear', {}).get(slot) or entity_data.get(slot, "Empty")

        if item_name in ["Empty", "Locked", None]:
            report["Slots"][slot] = {"Item": item_name, "Attributes": [], "ScalingString": "None"}
            continue

        item_row = FrameG[FrameG.iloc[:, 0] == item_name]
        if item_row.empty:
            continue

        item_type = str(item_row.iloc[0, 2]).strip()
        grip_type = str(item_row.iloc[0, 4]).strip()
        weapon_type = get_weapon_type_from_excel(item_name)
        stats = weapon_attributes(weapon_type)

        if "Weapon" in item_type:
            scaling_str = stats.get('Scaling') if stats else "1 Strength"
            crit_mult = stats.get('Critical Multiplier', 1.0) if stats else 1.0

            try:
                col_v_val = str(item_row.iloc[0, 21]).strip()
                if col_v_val.lower() != "nan":
                    # Uses Regex to find the exact number, ignoring spaces or capitalization
                    crit_match = re.search(r'+\s([0-9.]+)\sCritical Multiplier', col_v_val, re.IGNORECASE)
                    if crit_match:
                        extra_crit = float(crit_match.group(1))
                        crit_mult += extra_crit
            except IndexError:
                pass # Failsafe in case your Excel sheet has missing columns
            # ----------------------------------------------------

            required_attrs = extract_primary_attributes(scaling_str)

            # --- DYNAMIC SWORD, SPEAR, & STAFF SCALING ---
            if weapon_type == "Sword":
                multiplier = extract_scaling_multiplier(scaling_str)
                if "Two-handed" in grip_type:
                    required_attrs = ["Dexterity", "Strength"]
                    scaling_str = f"{multiplier} Dexterity & Strength"
                else:
                    required_attrs = ["Dexterity"]
                    scaling_str = f"{multiplier} Dexterity"

            elif weapon_type == "Spear":
                multiplier = extract_scaling_multiplier(scaling_str)
                if "Two-handed" in grip_type:
                    # Now perfectly mirrors the Sword logic!
                    required_attrs = ["Strength", "Dexterity"]
                    scaling_str = f"{multiplier} Strength & Dexterity"
                else:
                    required_attrs = ["Strength"]
                    scaling_str = f"{multiplier} Strength"

            elif weapon_type == "Staff":
                multiplier = extract_scaling_multiplier(scaling_str)
                required_attrs = ["Highest_Str_Pow"]
                scaling_str = f"{multiplier} Strength or Power"

            report["Slots"][slot] = {
                "Item": item_name,
                "Type": weapon_type,
                "Attributes": required_attrs,
                "ScalingString": scaling_str,
                "Crit": crit_mult
            }
        else:
            report["Slots"][slot] = {
                "Item": item_name,
                "Type": item_type,
                "Attributes": [],
                "ScalingString": "None"
            }

    if report["Slots"].get('Main Hand 1', {}).get('Item') in ["Empty", "Locked", None]:
         report["Slots"]['Main Hand 1'] = {
            "Item": "Fists",
            "Type": "Unarmed",
            "Attributes": ["Highest"], 
            "ScalingString": "1.0 Highest Attribute",
            "Crit": 1.5
        }

    return report
# ==========================================
# --- 7. EXECUTION / SIMULATION LOOP ---
# ==========================================
def run_mass_simulation(total_runs=50):
    vital_stats = ["Health", "Mana", "Defense", "Dispersion"]
    aux_stats = ["Mobility", "Might", "Wisdom"] 
    resistance_stats = ["LIGHT RESISTANCE", "DARK RESISTANCE", "FIRE RESISTANCE", "FROST RESISTANCE", "WIND RESISTANCE", "EARTH RESISTANCE", "LIGHTNING RESISTANCE", "BLEED RESISTANCE", "POISON RESISTANCE"]
    
    all_defensive_stats = vital_stats + resistance_stats
    all_possible_stats = ["Strength", "Dexterity", "Power"]

    inventory_slots = ['Main Hand 1', 'Off Hand', 'Supplement', 'Secondary Gear', 'Extra Gear']

    for i in range(1, total_runs + 1):
        print(f"\n{'='*20} SIMULATION #{i} {'='*20}")

        # 1. Generate the Entity
        new_entity = generate_single_entity()
        new_entity['Race'] = get_random_race(new_entity.get('Rank'))

        # 2. Fetch Stat Data
        gear_def_bonuses = sum_gear_attribute_bonuses(new_entity, all_defensive_stats)
        race_base_def = get_race_stat_values(new_entity['Race'], all_defensive_stats)
        
        gear_aux_bonuses = sum_gear_attribute_bonuses(new_entity, aux_stats)

        # APPLY RANK MODIFIERS TO BASE HP/MANA
        rank_modifiers = {
            "Weakling": (0.50, 1.0),
            "Prime Weakling": (0.75, 1.0),
            "Elite": (1.0, 1.0),
            "Prime Elite": (1.25, 1.0),
            "Boss": (3.0, 2.0),
            "Prime Boss": (4.0, 2.5),
            "Guardian": (5.0, 3.0)
        }
        current_rank = new_entity.get('Rank', "Elite")
        hp_mult, mana_mult = rank_modifiers.get(current_rank, (1.0, 1.0))
        
        if "Health" in race_base_def:
            race_base_def["Health"] = int(race_base_def["Health"] * hp_mult)
        if "Mana" in race_base_def:
            race_base_def["Mana"] = int(race_base_def["Mana"] * mana_mult)

        gear_atk_bonuses = sum_gear_attribute_bonuses(new_entity, all_possible_stats)
        race_base_atk = get_race_stat_values(new_entity['Race'], all_possible_stats)

        # 3. Calculate Main Hand Damage
        combat_info = get_full_loadout_report(new_entity)
        main_hand = combat_info['Slots']['Main Hand 1']
        weapon_item = main_hand['Item']
        weapon_needs = main_hand['Attributes']
        scaling_str = main_hand['ScalingString']
        multiplier = extract_scaling_multiplier(scaling_str)
        main_crit = main_hand.get('Crit', 1.0)

        # --- DYNAMIC SCALING POOL CALCULATION ---
        raw_pool = 0
        if "Highest_Str_Pow" in weapon_needs:
            # If it's a Staff, check both Strength and Power, take whichever is higher
            str_total = race_base_atk.get("Strength", 0) + gear_atk_bonuses.get("Strength", 0)
            pow_total = race_base_atk.get("Power", 0) + gear_atk_bonuses.get("Power", 0)
            raw_pool = max(str_total, pow_total)
        else:
            for stat in weapon_needs:
                if stat == "2H_Bonus":
                    raw_pool += 1  # Adds the flat +1 to the stat pool!
                elif stat != "Highest" and stat != "Unknown":
                    raw_pool += (race_base_atk.get(stat, 0) + gear_atk_bonuses.get(stat, 0))

        final_scaling_bonus = raw_pool * multiplier
        
        if weapon_item == "Fists":
            highest_stat = max([race_base_atk.get(s, 0) + gear_atk_bonuses.get(s, 0) for s in all_possible_stats])
            main_hand_dmg_report = f"{highest_stat} Physical [Crit: {math.ceil(highest_stat * 1.5)}]"
        else:
            main_hand_dmg_report = get_scaled_weapon_damage(weapon_item, final_scaling_bonus, main_crit)

        # 4. Calculate Off Hand Damage
        off_hand = combat_info['Slots']['Off Hand']
        off_item = off_hand.get('Item', 'Empty')
        off_type = off_hand.get('Type', 'None')
        off_crit = off_hand.get('Crit', 1.0)
        off_hand_dmg_report = None

        if off_item not in ["Empty", "Locked", None]:
            total_str = race_base_atk.get("Strength", 0) + gear_atk_bonuses.get("Strength", 0)
            total_dex = race_base_atk.get("Dexterity", 0) + gear_atk_bonuses.get("Dexterity", 0)

            if off_type == "Sword":
                off_hand_dmg_report = get_scaled_weapon_damage(off_item, math.ceil(total_dex * 0.5), off_crit)
            elif off_type == "Axe":
                off_hand_dmg_report = get_scaled_weapon_damage(off_item, math.ceil(total_str * 0.5), off_crit)
            elif off_type == "Orb":
                item_row = FrameG[FrameG.iloc[:, 0] == off_item]
                if not item_row.empty:
                    base_dmg_str = str(item_row.iloc[0, 9])
                    orb_on_hit_val = item_row.iloc[0, 10]
                    orb_hit_str = ""
                    if pd.notnull(orb_on_hit_val) and str(orb_on_hit_val).strip() not in ["", "nan", "None"]:
                        orb_hit_str = f", Orb Effect: {str(orb_on_hit_val).strip()}"

                    match = re.match(r"(\d+)(?:-(\d+))?\s+(.*)", base_dmg_str.strip())
                    if match:
                        min_dmg = math.ceil(int(match.group(1)) * 0.5)
                        max_dmg = math.ceil(int(match.group(2)) * 0.5) if match.group(2) else min_dmg
                        dmg_type = match.group(3)
                        c_min = math.ceil(min_dmg * main_crit)
                        c_max = math.ceil(max_dmg * main_crit)

                        orb_bonus_dmg = f"{min_dmg} {dmg_type} [Crit: {c_min}]" if min_dmg == max_dmg else f"{min_dmg}-{max_dmg} {dmg_type} [Crit: {c_min}-{c_max}]"
                        main_hand_dmg_report += f" [+ {orb_bonus_dmg} from Orb{orb_hit_str}]"
            else:
                item_row = FrameG[FrameG.iloc[:, 0] == off_item]
                if not item_row.empty:
                    base_dmg_str = str(item_row.iloc[0, 9])
                    if base_dmg_str != "nan" and base_dmg_str.strip() != "":
                        off_hand_dmg_report = get_scaled_weapon_damage(off_item, 0, off_crit)

        # ------------------------------------------
        # --- PRINT OUTPUT FOR THIS ENTITY ---
        # ------------------------------------------
        race_row = FrameS[FrameS.iloc[:, 2].str.lower() == new_entity.get('Race', '').lower()]
        conditions = str(race_row.iloc[0, 5]) if not race_row.empty and pd.notnull(race_row.iloc[0, 5]) else "None"
        intelligence = random.randint(1, 20)

        print(f"Rank: {new_entity.get('Rank')}")
        print(f"Race: {new_entity.get('Race')}")
        print(f"Conditions: {conditions}")
        print(f"Faction: {new_entity.get('Faction')}")
        print(f"Intelligence: {intelligence}")
        print("-------")

        for stat in vital_stats:
            total = race_base_def.get(stat, 0) + gear_def_bonuses.get(stat, 0)
            print(f"{stat} Total: {total}")

        print("---")
        
        for stat in aux_stats:
            total = gear_aux_bonuses.get(stat, 0)
            print(f"{stat}: {int(total)}")

        print("---")
        
        for stat in all_possible_stats:
            total = race_base_atk.get(stat, 0) + gear_atk_bonuses.get(stat, 0)
            print(f"{stat} Total: {total}")
        
        total_sdp = sum([(race_base_atk.get(s, 0) + gear_atk_bonuses.get(s, 0)) for s in all_possible_stats])
        print("---")
        print(f"Main Hand Damage: {main_hand_dmg_report}")
        if off_hand_dmg_report and "nan" not in off_hand_dmg_report.lower():
            print(f"Off Hand Damage : {off_hand_dmg_report}")
        print("---")

        for stat in resistance_stats:
            raw_base = race_base_def.get(stat, 0)
            raw_bonus = gear_def_bonuses.get(stat, 0)
            
            # If Excel formatted it as a decimal (e.g. 0.20), multiply by 100
            base = int(raw_base * 100) if 0 < abs(raw_base) <= 1.0 else int(raw_base)
            bonus = int(raw_bonus * 100) if 0 < abs(raw_bonus) <= 1.0 else int(raw_bonus)

            print(f"{stat}: {base + bonus}%")

        print("------")

        for slot in inventory_slots:
            item = new_entity.get('Gear', {}).get(slot) or new_entity.get(slot, "Empty")
            print(f"{slot}: {item}")
                
        print("\n--- Abilities ---")
        for ability_tier, ability_name in new_entity.get("Abilities", {}).items():
            if str(ability_name).lower() not in ["nan", "none", "", "empty", "unknown ability"]:
                print(f"{ability_tier}: {ability_name}")

if __name__ == "__main__":
    run_mass_simulation(1)