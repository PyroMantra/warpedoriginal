import csv
import json
import sys
from pathlib import Path

def to_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y"}

def to_nullable_str(v):
    s = str(v).strip()
    return s if s else None

def main():
    if len(sys.argv) < 3:
        print("Usage: py scripts/export_skeleton_csv_to_json.py data/map_skeletons/8p_cross_01.csv data/map_skeletons/8p_cross_01.json")
        raise SystemExit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    with src.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    cells = []
    max_row = 0
    max_col = 0
    for r in rows:
        row = int(r["row"])
        col = int(r["col"])
        max_row = max(max_row, row)
        max_col = max(max_col, col)

        cells.append({
            "row": row,
            "col": col,
            "active": to_bool(r["active"]),
            "role": str(r["role"]).strip(),
            "region": str(r["region"]).strip(),
            "spawn": to_bool(r["spawn"]),
            "special": to_nullable_str(r.get("special", "")),
            "allow_biomes": to_bool(r.get("allow_biomes", "0")),
            "allow_landmarks": to_bool(r.get("allow_landmarks", "0")),
            "allow_entities": to_bool(r.get("allow_entities", "0")),
        })

    payload = {
        "name": src.stem,
        "description": "Skeleton exported from CSV",
        "width": max_col + 1,
        "height": max_row + 1,
        "layout": "odd-r",
        "cells": cells,
    }

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {dst}")

if __name__ == "__main__":
    main()
