# Map Skeleton Starter Pack

Drop these files into your project root.

## Files included
- `data/map_skeletons/8p_cross_01.json` — starter skeleton JSON based on your cross-layout mockup
- `data/map_skeletons/8p_cross_01.csv` — same skeleton in spreadsheet-friendly CSV form
- `data/mapgen/example_params.json` — example generation parameters
- `data/generated_maps/8p_cross_01_seed_12345.json` — example generated map output
- `scripts/export_skeleton_csv_to_json.py` — converts CSV skeletons into JSON
- `scripts/generate_map_from_skeleton.py` — generates a random map spec from a skeleton + parameters

## Role legend
- `void` = black / unusable
- `outer_area` = yellow outer biome area
- `connector` = brown bridge/choke/gate area
- `core_area` = green contested area
- `center_ring` = cyan ring around center objective
- `center_core` = red center objective hex
- `spawn` = blue spawn hex

## How to use
### 1) Edit the skeleton in CSV if you want
Open:
- `data/map_skeletons/8p_cross_01.csv`

Columns:
- `row`, `col`, `active`, `role`, `region`, `spawn`, `special`, `allow_biomes`, `allow_landmarks`, `allow_entities`

### 2) Convert CSV back to JSON
```bash
py scripts/export_skeleton_csv_to_json.py data/map_skeletons/8p_cross_01.csv data/map_skeletons/8p_cross_01.json
```

### 3) Generate a map from that skeleton
```bash
py scripts/generate_map_from_skeleton.py data/map_skeletons/8p_cross_01.json data/mapgen/example_params.json data/generated_maps/8p_cross_01_seed_12345.json
```

## How generation works
1. Load skeleton
2. Assign biomes by region
3. Place landmarks/entities/loot by quotas and densities
4. Output a finished map JSON with:
   - biome
   - texture
   - zone
   - landmark
   - entity
   - defended
   - spawn

## Important note
This is a **starter skeleton pack**, not a pixel-perfect extraction of the screenshot.
It is intentionally made so you can:
- tweak the CSV easily
- regenerate JSON fast
- start plugging mapgen into your site without building an editor first
