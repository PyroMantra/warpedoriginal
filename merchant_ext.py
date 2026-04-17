# merchant_ext.py — Merchant generator + admin-only unique gear toggles
# Works with a single Excel tab: "Gear+Items" with columns:
# Kind | Rarity | Name | Gold | Artifact

from flask import render_template, request, jsonify
import random
import re

RAR_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Astral", "Ultimate"]
UNIQUE_RARITIES = ("Legendary", "Mythic", "Astral")
UNIQUE_RANK = {"Legendary": 1, "Mythic": 2, "Astral": 3}


def _canon_name(s):
    """Pretty display name: keep only the base name before ':' or ';'."""
    s = str(s or "")
    s = s.replace("’", "'").replace("`", "'")
    s = re.split(r"[:;]", s, maxsplit=1)[0]
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _key_name(s):
    """Stable matching key for dedupe/toggles."""
    s = _canon_name(s).lower()
    s = s.replace("’", "'").replace("`", "'")
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def init_merchant(app, get_db, sheets):
    """Wire up merchant generator and admin toggle views. Safe against double registration."""
    if getattr(app, "_merchant_init_done", False):
        return
    app._merchant_init_done = True

    # ---------------------- DB helpers ----------------------
    def _ensure_table():
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

    # ---------------- Sheet / column helpers ----------------
    def _get_gearitems_df():
        # tolerant match for the tab name
        wanted = ["gear+items", "gear&items", "gear items", "gear_and_items"]
        for k, v in sheets.items():
            key = (k or "").strip().lower()
            if key in wanted:
                return v
        # last resort: fuzzy contains both tokens
        for k, v in sheets.items():
            key = (k or "").strip().lower()
            if "gear" in key and "item" in key:
                return v
        return None

    def _norm_cols(df):
        # Normalize headers: strip spaces/punctuation, lowercase
        def norm(s):
            return re.sub(r"[^a-z]+", "", str(s).lower())

        mapping = {c: norm(c) for c in df.columns}
        ndf = df.rename(columns=mapping)

        # Map to canonical names
        colmap = {}
        wants = {
            "kind": {"kind", "type", "what"},
            "rarity": {"rarity"},
            "name": {"name", "gearitem", "gear", "item", "title"},
            "gold": {"gold", "price", "cost"},
            "artifact": {"artifact", "isartifact", "artifactflag"},
        }
        for canon, candidates in wants.items():
            for c in ndf.columns:
                if c in candidates:
                    colmap[canon] = c
                    break

        missing = [k for k in wants if k not in colmap]
        if missing:
            raise ValueError(
                "Missing one or more required columns in Gear+Items: Kind, Rarity, Name, Gold, Artifact "
                f"(missing {missing})"
            )
        return ndf, colmap

    def _clean_normalize(df, col):
        """Return cleaned DataFrame with: kind, rarity, name, gold(int), artifact(int)."""
        k, r, n, g, a = col["kind"], col["rarity"], col["name"], col["gold"], col["artifact"]
        out = df[[k, r, n, g, a]].copy()

        # drop empty names and "**Insert**" placeholders
        out[n] = out[n].astype(str)
        mask = (
            out[n].str.strip().ne("")
            & ~out[n].str.contains(r"\*\*insert\*\*", flags=re.I, na=False)
        )
        out = out[mask].copy()

        # normalize rarity to canonical tokens
        out[r] = (
            out[r].astype(str)
            .str.extract(r"(?i)(Common|Uncommon|Rare|Epic|Legendary|Mythic|Astral|Ultimate)")[0]
            .str.title()
        )
        out = out[out[r].isin(RAR_ORDER)].copy()

        # parse gold like "200 Gold" -> 200
        out[g] = (
            out[g].astype(str)
            .str.extract(r"(\d+)", expand=False)
            .fillna("0")
            .astype(int)
        )

        # normalize artifact -> 0/1
        out[a] = out[a].astype(str).str.strip().str.lower()
        out[a] = out[a].isin({"1", "true", "yes", "y"}).astype(int)

        # normalize kind
        out[k] = out[k].astype(str).str.strip().str.lower()
        out[k] = out[k].apply(
            lambda x: "gear" if x.startswith("gear") else ("item" if x.startswith("item") else x)
        )

        return out.rename(columns={k: "kind", r: "rarity", n: "name", g: "gold", a: "artifact"})

    # ---------------- Sync unique gear from current Gear+Items sheet ----------------
    def _sync_unique_from_df(ndf):
        """
        Rebuild gear_unique from the current sheet so the admin page exactly matches Gear+Items.
        Keeps previous enabled/disabled state when names still match.
        """
        _ensure_table()

        gdf = ndf[ndf["kind"] == "gear"].copy()
        sub = gdf[gdf["rarity"].isin(UNIQUE_RARITIES)].copy()

        conn = get_db()
        cur = conn.cursor()

        try:
            existing_rows = cur.execute(
                "SELECT name, rarity, is_artifact, enabled FROM gear_unique"
            ).fetchall()
            existing_enabled = {_key_name(name): int(enabled) for name, _, _, enabled in existing_rows}

            desired = {}
            for _, row in sub.iterrows():
                display = _canon_name(row["name"])
                key = _key_name(display)
                if not key:
                    continue

                rarity = str(row["rarity"]).strip().title()
                art = int(row["artifact"])

                if key not in desired:
                    desired[key] = {
                        "name": display,
                        "rarity": rarity,
                        "is_artifact": art,
                    }
                else:
                    # prefer higher rarity if duplicate keys collide
                    if UNIQUE_RANK.get(rarity, 0) > UNIQUE_RANK.get(desired[key]["rarity"], 0):
                        desired[key]["rarity"] = rarity
                        desired[key]["name"] = display
                    desired[key]["is_artifact"] = max(desired[key]["is_artifact"], art)

            cur.execute("DELETE FROM gear_unique")

            for key, v in sorted(
                desired.items(),
                key=lambda kv: (-UNIQUE_RANK.get(kv[1]["rarity"], 0), kv[1]["name"].lower())
            ):
                cur.execute(
                    "INSERT INTO gear_unique (name, rarity, is_artifact, enabled) VALUES (?,?,?,?)",
                    (
                        v["name"],
                        v["rarity"],
                        int(v["is_artifact"]),
                        existing_enabled.get(key, 1),
                    ),
                )

            conn.commit()
        finally:
            conn.close()

    # ---------------- Build pools (respecting toggles) ----------------
    def _load_pools():
        df = _get_gearitems_df()
        if df is None:
            return None
        ndf, col = _norm_cols(df)
        ndf = _clean_normalize(ndf, col)

        _sync_unique_from_df(ndf)

        # toggles for unique gear
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT name, enabled FROM gear_unique")
        allowed = {_key_name(n): en for (n, en) in cur.fetchall()}
        conn.close()

        gear_all = ndf[ndf["kind"] == "gear"].copy()

        # respect toggles only for unique gear
        def _allow(row):
            if row["rarity"] in UNIQUE_RARITIES:
                en = allowed.get(_key_name(row["name"]))
                return (en is None) or (en == 1)
            return True

        gear_all = gear_all[gear_all.apply(_allow, axis=1)]

        item_all = ndf[ndf["kind"] == "item"].copy()

        pools = {
            "gear": {
                "common": gear_all[gear_all["rarity"] == "Common"],
                "uncommon": gear_all[gear_all["rarity"] == "Uncommon"],
                "rare": gear_all[gear_all["rarity"] == "Rare"],
                "epic": gear_all[gear_all["rarity"] == "Epic"],
                "legendary": gear_all[(gear_all["rarity"] == "Legendary") & (gear_all["artifact"] == 0)],
                "legendary_artifact": gear_all[(gear_all["rarity"] == "Legendary") & (gear_all["artifact"] == 1)],
                "mythic": gear_all[(gear_all["rarity"] == "Mythic") & (gear_all["artifact"] == 0)],
                "astral": gear_all[(gear_all["rarity"] == "Astral") & (gear_all["artifact"] == 0)],
            },
            "items": {
                "common": item_all[item_all["rarity"] == "Common"],
                "uncommon": item_all[item_all["rarity"] == "Uncommon"],
                "rare": item_all[item_all["rarity"] == "Rare"],
                "epic": item_all[item_all["rarity"] == "Epic"],
                "legendary": item_all[item_all["rarity"] == "Legendary"],
                "mythic": item_all[item_all["rarity"] == "Mythic"],
                "astral": item_all[item_all["rarity"] == "Astral"],
            },
        }
        return pools

    # ---------------- Picking & routes ----------------
    def _pick(df, n):
        if df is None or getattr(df, "empty", True) or n <= 0:
            return []
        size = len(df)
        if size <= n:
            idx = list(range(size))
            random.shuffle(idx)
            return [df.iloc[i] for i in idx]
        return [df.iloc[i] for i in random.sample(range(size), n)]

    @app.route("/merchant", endpoint="merchant_page")
    def merchant_generator():
        pools = _load_pools()
        if pools is None:
            return "Merchant generator: Could not load Gear+Items sheet.", 500

        out = {
            "gear": {k: [] for k in ["common", "uncommon", "rare", "epic", "legendary", "legendary_artifact", "mythic"]},
            "items": {k: [] for k in ["common", "uncommon", "rare", "epic", "legendary", "mythic"]},
        }

        target = {
            ("gear", "common"): 5,
            ("gear", "uncommon"): 4,
            ("gear", "rare"): 3,
            ("gear", "epic"): 2,
            ("gear", "legendary"): 1,
            ("gear", "legendary_artifact"): 1,
            ("gear", "mythic"): 1,
            ("items", "common"): 3,
            ("items", "uncommon"): 2,
            ("items", "rare"): 2,
            ("items", "epic"): 2,
            ("items", "legendary"): 1,
            ("items", "mythic"): 1,
        }

        for (kind, rar), n in target.items():
            pool = pools[kind][rar]
            picks = _pick(pool, n)
            if kind == "gear":
                out["gear"][rar] = [
                    {"name": str(r["name"]), "gold": int(r["gold"]), "rarity": rar.replace("_", " ").title()}
                    for r in picks
                ]
            else:
                out["items"][rar] = [
                    {"name": str(r["name"]), "gold": int(r["gold"]), "rarity": rar.title()}
                    for r in picks
                ]

        return render_template("merchant.html", results=out)

    @app.route("/merchant-admin", endpoint="merchant_admin_page")
    @app.admin_required
    def merchant_admin():
        df = _get_gearitems_df()
        if df is None:
            return "Gear+Items sheet not found.", 500
        ndf, col = _norm_cols(df)
        ndf = _clean_normalize(ndf, col)

        _sync_unique_from_df(ndf)

        _ensure_table()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, rarity, is_artifact, enabled
            FROM gear_unique
            ORDER BY CASE lower(rarity)
                WHEN 'astral' THEN 1
                WHEN 'mythic' THEN 2
                WHEN 'legendary' THEN 3
                ELSE 99
            END,
            name COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
        conn.close()

        data = [{
            "name": r[0],
            "display": r[0],
            "rarity": r[1],
            "is_artifact": bool(r[2]),
            "enabled": bool(r[3]),
        } for r in rows]

        return render_template("merchant_admin.html", gear=data)

    @app.route("/chest", endpoint="chest_page")
    def chest_generator():
        pools = _load_pools()
        if pools is None:
            return "Chest generator: Could not load Gear+Items sheet.", 500

        # Combine legendary + legendary_artifact into one pool for chest logic
        import pandas as _pd
        leg_frames = []
        for k in ("legendary", "legendary_artifact"):
            dfk = pools["gear"].get(k)
            if dfk is not None and not getattr(dfk, "empty", True):
                leg_frames.append(dfk)
        legendary_all = _pd.concat(leg_frames, ignore_index=True) if leg_frames else None

        def _pick_gear(rarity_key: str):
            # rarity_key in: common/uncommon/rare/epic/legendary/mythic
            label = rarity_key.replace("_", " ").title()
            if rarity_key == "legendary":
                df = legendary_all
            else:
                df = pools["gear"].get(rarity_key)
            recs = _pick(df, 1)
            if not recs:
                return {"name": "—", "gold": 0, "rarity": label}
            r = recs[0]
            return {"name": str(r["name"]), "gold": int(r["gold"]), "rarity": label}

        def _pick_item(rarity_key: str):
            label = rarity_key.title()
            df = pools["items"].get(rarity_key)
            recs = _pick(df, 1)
            if not recs:
                return {"name": "—", "gold": 0, "rarity": label}
            r = recs[0]
            return {"name": str(r["name"]), "gold": int(r["gold"]), "rarity": label}

        # Left column: "Chest"
        left_specs = [
            ("2–5",   "common",    "common"),
            ("6–9",   "uncommon",  "uncommon"),
            ("10–15", "rare",      "rare"),
            ("16–19", "epic",      "epic"),
            ("20",    "legendary", "legendary"),
        ]
        # Right column: "Legendary chest"
        right_specs = [
            ("2–5",   "legendary", "uncommon"),
            ("6–9",   "legendary", "rare"),
            ("10–15", "legendary", "epic"),
            ("16–19", "legendary", "legendary"),
            ("20",    "mythic",    "mythic"),
        ]

        def make_entry(label, gear_key, item_key):
            return {
                "range": label,
                "gear": _pick_gear(gear_key),
                "item": _pick_item(item_key),
            }

        out = {
            "left":  [make_entry(*t) for t in left_specs],
            "right": [make_entry(*t) for t in right_specs],
        }
        return render_template("chest.html", results=out)

    @app.route("/merchant-admin/toggle", methods=["POST"], endpoint="merchant_admin_toggle")
    @app.admin_required
    def merchant_admin_toggle():
        nm = (request.form.get("name") or "").strip()
        if not nm:
            return jsonify({"ok": False, "error": "Missing name"}), 400
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT enabled FROM gear_unique WHERE name=?", (nm,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "Unknown gear name"}), 404
        newv = 0 if row[0] == 1 else 1
        cur.execute("UPDATE gear_unique SET enabled=? WHERE name=?", (newv, nm))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "name": nm, "enabled": bool(newv)})

    return app