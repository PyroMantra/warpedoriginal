import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from flask import render_template, request


# -----------------------------------------------------------------------------
# Forge Helper extension
# -----------------------------------------------------------------------------

RARITY_ORDER_DEFAULT = [
    "Common",
    "Uncommon",
    "Rare",
    "Epic",
    "Legendary",
    "Mythic",
]

# Exclude these from the rarity dropdown / filtering
RARITY_EXCLUDE = {"astral", "ultimate", "ultimate:"}

MATERIAL_MAP = {
    "Ore": "Metal",
    "Fabric": "Cloth",
}

# Only allow grouping by these fields (per UI)
GROUP_BY_ALLOWED = {"Gear Type", "Slot Type", "Crafting Type"}

# Remove these from the Slot Type FILTER dropdown (still allowed to appear in results)
SLOT_TYPE_FILTER_EXCLUDE = {
    "artifact",
    "artifact/necklace",
    "artifact/two-handed",
    "artifact/two-handed",  # keep duplicate-safe
    "artifact/two-handed".lower(),
    "artifact/two-handed".replace("–", "-").lower(),  # defensive
    "artifact/two-handed".replace("—", "-").lower(),  # defensive
    "artifact/two-handed".replace("‑", "-").lower(),  # defensive
    "artifact/two-handed".replace("−", "-").lower(),  # defensive
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
    # include the exact strings you'll see in the dropdown too
    "artifact/two-handed".lower(),
    "artifact/two-handed".replace("two-handed", "two-handed").lower(),
}

# Also add a normalized variant with the common dash characters replaced.
def _slot_exclude_norm(s: str) -> str:
    return (
        (s or "")
        .strip()
        .lower()
        .replace("–", "-")
        .replace("—", "-")
        .replace("‑", "-")
        .replace("−", "-")
    )


SLOT_TYPE_FILTER_EXCLUDE |= {
    _slot_exclude_norm("Artifact"),
    _slot_exclude_norm("Artifact/Necklace"),
    _slot_exclude_norm("Artifact/Two-Handed"),
    _slot_exclude_norm("Artifact/Two-handed"),
    _slot_exclude_norm("Artifact/Two‑Handed"),
}


def _norm(s: object) -> str:
    if s is None:
        return ""
    return str(s).strip()


def _normalize_piece_set_label(label: str) -> str:
    """Merge 'X Set Piece' into 'X Piece' (case-insensitive)."""
    if not label:
        return label
    return re.sub(r"\s+Set\s+Piece\s*$", " Piece", str(label).strip(), flags=re.IGNORECASE)


def _rarity_allowed(r: str) -> bool:
    rl = (r or "").strip().lower()
    if not rl:
        return False
    if rl in RARITY_EXCLUDE:
        return False
    if rl.startswith("ultimate"):
        return False
    return True


def _load_forge_df(app_root: str) -> pd.DataFrame:
    """Load the forge helper spreadsheet.

    Priority:
      1) FORGE_HELPER_XLSX env var
      2) data/forge_helper_gear.xlsx
      3) data/naming_format_colA_numbers_labeled_no_gold.xlsx
    """
    env_path = os.getenv("FORGE_HELPER_XLSX", "").strip()

    candidates: List[str] = []
    if env_path:
        candidates.append(env_path)

    candidates.extend(
        [
            os.path.join(app_root, "data", "forge_helper_gear.xlsx"),
            os.path.join(app_root, "data", "naming_format_colA_numbers_labeled_no_gold.xlsx"),
        ]
    )

    chosen: Optional[str] = None
    for p in candidates:
        try:
            if p and Path(p).exists():
                chosen = p
                break
        except Exception:
            continue

    if not chosen:
        raise FileNotFoundError(
            "Forge Helper could not find an Excel file. "
            "Put your sheet at data/forge_helper_gear.xlsx or set FORGE_HELPER_XLSX."
        )

    df = pd.read_excel(chosen, sheet_name=0)

    if "Final Name" not in df.columns:
        raise KeyError("Forge Helper sheet must include a 'Final Name' column.")

    # Critical cleanup: drop NaNs before casting to str so we don't create literal 'nan'
    df = df[df["Final Name"].notna()]

    df["Final Name"] = df["Final Name"].astype(str).map(lambda x: x.strip() if isinstance(x, str) else x)

    # Drop blanks + literal "nan"
    df = df[df["Final Name"].astype(str).str.strip().ne("")]
    df = df[df["Final Name"].astype(str).str.strip().str.lower().ne("nan")]

    # Ignore "**Insert**" rows if present in the Name column
    if "Name" in df.columns:
        df = df[~df["Name"].astype(str).str.contains(r"\*\*Insert\*\*", case=False, na=False)]

    # Normalized slot type for UI + filtering (merges Set Piece into Piece)
    if "Slot Type" in df.columns:
        df["_SlotTypeNorm"] = (
            df["Slot Type"]
            .fillna("")
            .astype(str)
            .map(_normalize_piece_set_label)
            .map(lambda x: x.strip())
        )
    else:
        df["_SlotTypeNorm"] = ""

    return df


def _unique_sorted(series: pd.Series) -> List[str]:
    vals = (
        series.dropna()
        .astype(str)
        .map(lambda x: x.strip())
        .loc[lambda s: s.ne("")]
        .unique()
        .tolist()
    )
    return sorted(vals)


def _unique_sorted_slot_types(series: pd.Series) -> List[str]:
    vals = (
        series.dropna()
        .astype(str)
        .map(lambda x: x.strip())
        .loc[lambda s: s.ne("")]
        .unique()
        .tolist()
    )
    # Exclude artifact slot types from the FILTER dropdown
    cleaned: List[str] = []
    for v in vals:
        if _slot_exclude_norm(v) in SLOT_TYPE_FILTER_EXCLUDE:
            continue
        cleaned.append(v)
    return sorted(cleaned)


def _build_rarity_order(df: pd.DataFrame) -> List[str]:
    found_all = _unique_sorted(df.get("Rarity", pd.Series([], dtype=object)))
    found = [r for r in found_all if _rarity_allowed(r)]

    ordered: List[str] = []
    for r in RARITY_ORDER_DEFAULT:
        if r in found:
            ordered.append(r)
    for r in found:
        if r not in ordered:
            ordered.append(r)
    return ordered or RARITY_ORDER_DEFAULT


def init_forge_helper(app):
    """Register Forge Helper routes on the Flask app."""

    df = _load_forge_df(app.root_path)
    rarity_order = _build_rarity_order(df)

    # Only keep filters you want in the UI
    options = {
        "gear_types": _unique_sorted(df.get("Gear Type", pd.Series([], dtype=object))),
        # Slot Type options use normalized values (Piece + Set Piece merged) and exclude artifacts
        "slot_types": _unique_sorted_slot_types(df.get("_SlotTypeNorm", pd.Series([], dtype=object))),
        "crafting_types": _unique_sorted(df.get("Crafting Type", pd.Series([], dtype=object))),
    }

    @app.route("/forge-helper", methods=["GET"])
    def forge_helper():
        selected_material = _norm(request.args.get("material")) or "Ore"

        requested_rarity = _norm(request.args.get("rarity"))
        if requested_rarity and not _rarity_allowed(requested_rarity):
            requested_rarity = ""

        selected_rarity = requested_rarity or (rarity_order[0] if rarity_order else "Common")

        selected_filters = {
            "q": _norm(request.args.get("q")),
            "gear_type": _norm(request.args.get("gear_type")),
            "slot_type": _norm(request.args.get("slot_type")),
            "crafting_type": _norm(request.args.get("crafting_type")),
            "group_by": _norm(request.args.get("group_by")),
        }

        filtered = df.copy()

        if "Rarity" in filtered.columns and selected_rarity:
            filtered = filtered[filtered["Rarity"].astype(str).str.strip().str.lower() == selected_rarity.lower()]

        wanted_material = MATERIAL_MAP.get(selected_material, "")
        if wanted_material and "Material Type" in filtered.columns:
            filtered = filtered[
                filtered["Material Type"].astype(str).str.strip().str.lower() == wanted_material.lower()
            ]

        def apply_eq(col: str, key: str):
            val = selected_filters.get(key, "")
            if val and col in filtered.columns:
                return filtered[filtered[col].astype(str).str.strip().str.lower() == val.lower()]
            return filtered

        filtered = apply_eq("Gear Type", "gear_type")
        filtered = apply_eq("Crafting Type", "crafting_type")

        # Slot Type filter uses normalized value so "X Piece" includes both "X Piece" and "X Set Piece"
        slot_val = selected_filters.get("slot_type", "")
        if slot_val and _slot_exclude_norm(slot_val) not in SLOT_TYPE_FILTER_EXCLUDE:
            filtered = filtered[filtered["_SlotTypeNorm"].astype(str).str.strip().str.lower() == slot_val.lower()]
        else:
            # If user tries to request excluded slot types via URL, ignore
            selected_filters["slot_type"] = ""

        q = selected_filters.get("q", "")
        if q:
            ql = q.lower()
            cols = [c for c in ["Final Name", "Name", "Keyword"] if c in filtered.columns]
            mask = None
            for c in cols:
                m = filtered[c].astype(str).str.lower().str.contains(ql, na=False)
                mask = m if mask is None else (mask | m)
            if mask is not None:
                filtered = filtered[mask]

        names = (
            filtered["Final Name"]
            .dropna()
            .astype(str)
            .map(lambda x: x.strip())
            .loc[lambda s: s.ne("")]
            .loc[lambda s: s.str.lower().ne("nan")]
            .tolist()
        )

        group_by = selected_filters.get("group_by")
        if group_by not in GROUP_BY_ALLOWED:
            group_by = ""

        grouped: Optional[Dict[str, List[str]]] = None
        if group_by:
            grouped = {}
            for _, row in filtered.iterrows():
                if group_by == "Slot Type":
                    grp_raw = _norm(row.get("_SlotTypeNorm")) or "Other"
                else:
                    grp_raw = _norm(row.get(group_by)) or "Other"

                grp = _normalize_piece_set_label(grp_raw)

                nm = _norm(row.get("Final Name"))
                if not nm or nm.lower() == "nan":
                    continue

                grouped.setdefault(grp, []).append(nm)

            grouped = {k: grouped[k] for k in sorted(grouped.keys())}

        result_count = sum(len(v) for v in grouped.values()) if grouped else len(names)

        return render_template(
            "forge_helper.html",
            rarity_order=rarity_order,
            selected_material=selected_material,
            selected_rarity=selected_rarity,
            selected_filters=selected_filters,
            options=options,
            names=names,
            grouped=grouped,
            result_count=result_count,
        )
