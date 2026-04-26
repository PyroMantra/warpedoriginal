# Step-By-Step Asset Catalog Guide

This guide shows you how to use the Skeleton Editor JSONs together with your Figma exports.

You do **not** need to be good at coding to start. For now, you only need to:

1. export images from Figma
2. place them in the right folders
3. add simple entries into `data/mapgen/asset_catalog.json`

## 1. What Each File Does

- `data/map_skeletons/*.json`
  These are your skeleton blueprints from the Skeleton Editor.
- `data/mapgen/example_params.json`
  These are the generation rules for one map run.
- `data/mapgen/asset_catalog.json`
  This is the library of textures, landmarks, and entities the generator is allowed to use.
- `data/generated_maps/*.json`
  These are the finished generated maps.

Think of it like this:

- Skeleton = where things are allowed to go
- Params = how much of each thing should be generated
- Asset catalog = what actual art/assets exist

## 2. Recommended Folder Setup

Use these dedicated folders for map generation only:

- `static/mapgen/textures/` for textures
- `static/mapgen/landmarks/` for landmarks
- `static/mapgen/entities/` for entities

This keeps your map-generation assets separate from the rest of the site, so they do not get mixed into existing galleries or other pages by accident.

## 3. Export From Figma

For each asset in Figma:

1. Select the texture, landmark, or entity.
2. Export it as PNG.
3. Give it a clear file name.

Good examples:

- `grass_01.png`
- `grass_02.png`
- `desert_01.png`
- `minor_shrine.png`
- `gold_chest.png`
- `bandit.png`
- `undead_elite.png`

Avoid names like:

- `Frame 123.png`
- `Export.png`
- `Group 7 final final.png`

## 4. Put The Files In The Right Folder

Use this rule:

- textures go into `static/mapgen/textures/`
- landmarks go into `static/mapgen/landmarks/`
- entities go into `static/mapgen/entities/`

Example:

- `static/mapgen/textures/grass_01.png`
- `static/mapgen/landmarks/minor_shrine.png`
- `static/mapgen/entities/bandit.png`

## 5. Open The Asset Catalog

Open:

- [asset_catalog.json](/abs/c:/Users/Yak/Desktop/Perfection/data/mapgen/asset_catalog.json)

It has 3 sections:

- `textures`
- `landmarks`
- `entities`

Each item in those lists is one asset the generator can use.

## 6. How To Add A Texture

Copy one texture entry and edit the values.

Example:

```json
{
  "id": "grass_02",
  "label": "Grass Texture 02",
  "image": "static/mapgen/textures/grass_02.png",
  "biomes": ["grass"],
  "roles": ["outer_area", "core_area"],
  "regions": [],
  "weight": 3,
  "tags": ["nature"]
}
```

What the fields mean:

- `id`: a unique name for the asset
- `label`: human-friendly name
- `image`: where the PNG lives
- `biomes`: which biomes can use this asset
- `roles`: which skeleton roles can use it
- `regions`: leave empty for now unless you want a specific region only
- `weight`: bigger number means "pick this more often"
- `tags`: optional labels for filtering later

## 7. How To Add A Landmark

Example:

```json
{
  "id": "ruined_tower",
  "label": "Ruined Tower",
  "image": "static/mapgen/landmarks/ruined_tower.png",
  "biomes": ["grass", "forest"],
  "roles": ["outer_area", "core_area"],
  "regions": [],
  "specials": [],
  "weight": 2,
  "min_distance_from_same": 4,
  "min_distance_from_spawn": 2,
  "unique": false,
  "tags": ["tower", "poi"]
}
```

Important fields:

- `min_distance_from_same`: avoids two of the same landmark spawning too close together
- `min_distance_from_spawn`: keeps it away from player spawn
- `unique`: if `true`, only one copy should appear on the whole map

## 8. How To Add An Entity

Example:

```json
{
  "id": "legion_scout",
  "label": "Legion Scout",
  "image": "static/mapgen/entities/legion_scout.png",
  "biomes": ["desert", "grass"],
  "roles": ["outer_area", "connector"],
  "regions": [],
  "specials": [],
  "weight": 3,
  "difficulty": "outer",
  "min_distance_from_spawn": 2,
  "unique": false,
  "tags": ["legion", "humanoid"]
}
```

Use `difficulty` like this:

- `outer` for easier entities
- `core` for stronger entities
- `boss` for center or special entities

## 9. How To Use Regions

Leave `regions: []` empty at first.

Only use regions if you want an asset to appear in a very specific part of the map, for example:

```json
"regions": ["northwest_outer"]
```

That means the asset can only appear in that named region from the Skeleton Editor.

## 10. How To Use Specials

Use `specials` only for forced or special content.

Examples:

- `"specials": ["boss"]`
- `"specials": ["relic"]`
- `"specials": ["player_spawn"]`

If an asset is normal/random, keep:

```json
"specials": []
```

## 11. Your First Safe Workflow

Do this first:

1. Export 3 textures from Figma
2. Export 3 landmarks from Figma
3. Export 3 entities from Figma
4. Put them into the correct `static/mapgen/` folders
5. Add them into `asset_catalog.json`
6. Keep regions empty for now
7. Keep only simple biome and role rules

That will give you a small, manageable starting set.

## 12. Suggested First Biomes

To keep things simple, start with only:

- `grass`
- `desert`
- `corruption`

Then later add:

- `forest`
- `frostreach`
- `sundune`

## 13. Suggested First Rules

Use simple rules at first:

- outer areas: easy textures, easy entities, common landmarks
- connectors: fewer landmarks, some entities
- core area: stronger entities, rarer landmarks
- center ring: special landmarks or elite entities
- center core: boss/relic/objective only

## 14. Very Important Rule

Do not try to make the catalog perfect on day one.

Start with a tiny catalog that is clean and understandable.

Small and clean is much better than big and confusing.

## 15. What You Should Do Next

Follow these steps in order:

1. Pick 3 textures from Figma and export them
2. Pick 3 landmarks from Figma and export them
3. Pick 3 entities from Figma and export them
4. Rename the files clearly
5. Put them into the correct folders in `static/`
6. Replace the starter entries in `asset_catalog.json` with your real file names
7. Tell me which biomes you want first
8. Then I can help wire the generator to use this catalog automatically

## 16. If You Feel Unsure

The easiest path is:

1. send me the names of the first assets you export
2. tell me which ones are textures, landmarks, and entities
3. tell me which biome each one belongs to

Then I can fill in the JSON for you.
