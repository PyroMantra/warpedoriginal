# merchant_ext.py — Merchant generator + admin-only unique gear toggles
# Works with a single Excel tab: "Gear+Items" with columns:
# Kind | Rarity | Name | Gold | Artifact

from flask import render_template, request, jsonify
import random
import re
import pandas as pd

RAR_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]


def _canon_name(s):
    """Only the name before the first ':'; trim + collapse whitespace."""
    s = str(s or "")
    s = s.split(":", 1)[0]
    s = re.sub(r"\s+", " ", s).strip()
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
            .str.extract(r"(?i)(Common|Uncommon|Rare|Epic|Legendary|Mythic)")[0]
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

    # ---------------- Seed toggles from Legendary/Mythic gear ----------------
    def _seed_leg_myth_from_df(ndf):
        _ensure_table()
        gdf = ndf[ndf["kind"] == "gear"]
        sub = gdf[gdf["rarity"].isin(["Legendary", "Mythic"])]
        conn = get_db()
        cur = conn.cursor()
        try:
            for _, row in sub.iterrows():
                nm = _canon_name(row["name"])
                rar = str(row["rarity"]).strip()
                art = int(row["artifact"])
                if nm:
                    cur.execute(
                        "INSERT OR IGNORE INTO gear_unique (name, rarity, is_artifact, enabled) VALUES (?,?,?,1)",
                        (nm, rar, art),

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

        _seed_leg_myth_from_df(ndf)

        # toggles for legendary/mythic gear
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT name, enabled FROM gear_unique")
        allowed = {_canon_name(n): en for (n, en) in cur.fetchall()}
        conn.close()

        gear_all = ndf[ndf["kind"] == "gear"].copy()

        # respect toggles only for legendary/mythic gear
        def _allow(row):
            if row["rarity"] in ("Legendary", "Mythic"):
                en = allowed.get(_canon_name(row["name"]))
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
            },
            "items": {
                "common": item_all[item_all["rarity"] == "Common"],
                "uncommon": item_all[item_all["rarity"] == "Uncommon"],
                "rare": item_all[item_all["rarity"] == "Rare"],
                "epic": item_all[item_all["rarity"] == "Epic"],
                "legendary": item_all[item_all["rarity"] == "Legendary"],
                "mythic": item_all[item_all["rarity"] == "Mythic"],
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
        # Build latest list from sheet so admin sees new myth/leg gear
        df = _get_gearitems_df()
        if df is None:
            return "Gear+Items sheet not found.", 500
        ndf, col = _norm_cols(df)
        ndf = _clean_normalize(ndf, col)
        _seed_leg_myth_from_df(ndf)
        # --- ONE-TIME DEDUPE: collapse old long names into canonical keys ---
        _ensure_table()
        conn = get_db(); cur = conn.cursor()
        rows = cur.execute("SELECT name, rarity, is_artifact, enabled FROM gear_unique").fetchall()

        def _rar_rank(r):
            return 1 if str(r).strip().lower() == "mythic" else 2  # mythic preferred over legendary

        agg = {}
        for name, rar, art, en in rows:
            key = _canon_name(name)
            if key in agg:
                a = agg[key]
                a["enabled"] = a["enabled"] or bool(en)          # keep enabled if any duplicate was enabled
                a["is_artifact"] = a["is_artifact"] or bool(art)  # keep artifact flag if any said true
                if _rar_rank(rar) < _rar_rank(a["rarity"]):       # prefer Mythic over Legendary
                    a["rarity"] = rar
            else:
                agg[key] = {"rarity": rar, "is_artifact": bool(art), "enabled": bool(en)}

        cur.execute("DELETE FROM gear_unique")
        for key, v in agg.items():
            cur.execute(
                "INSERT OR REPLACE INTO gear_unique (name, rarity, is_artifact, enabled) VALUES (?,?,?,?)",
                (key, v["rarity"], 1 if v["is_artifact"] else 0, 1 if v["enabled"] else 0),
            )
        conn.commit(); conn.close()
        # --- END ONE-TIME DEDUPE ---

        # --- OPTIONAL: one-time normalize stored names to canonical form ---
        # Uncomment this block, load /merchant-admin once, then re-comment it.
        # _ensure_table()
        # conn = get_db(); cur = conn.cursor()
        # rows = cur.execute("SELECT name, rarity, is_artifact, enabled FROM gear_unique").fetchall()
        # cur.execute("DELETE FROM gear_unique")
        # for name, rar, art, en in rows:
        #     cur.execute(
        #         "INSERT OR REPLACE INTO gear_unique (name, rarity, is_artifact, enabled) VALUES (?,?,?,?)",
        #         (_canon_name(name), rar, art, en)
        #     )
        # conn.commit(); conn.close()
        # --- end optional normalize ---

        _ensure_table()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, rarity, is_artifact, enabled
            FROM gear_unique
            ORDER BY CASE lower(rarity) WHEN 'mythic' THEN 1 ELSE 2 END,
                     name COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
        conn.close()
        data = [{
            "name": r[0],                 # DB key (may include ': ...')
            "display": _canon_name(r[0]), # pretty label
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
