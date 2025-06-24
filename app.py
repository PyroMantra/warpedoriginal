from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
import os
import random
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'supersecretkey'

USERS = {
    'admin': 'adminpass',
    'player1': 'playerpass'
}

EXCEL_PATH = os.path.join("data", "Layer List (7).xlsx")
sheets = pd.read_excel(EXCEL_PATH, sheet_name=None)

# Remove sheets not meant for generic viewing
sheets = {k: v for k, v in sheets.items() if k not in ["Classes", "Races", "Abilities"]}
SHEET_NAMES = list(sheets.keys())
generator_sheets = [name for name in SHEET_NAMES if "Generator" in name]

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@app.route("/")
@login_required
def home():
    user = session.get("user")
    data_buttons = [
    {"label": "The Informatorium", "endpoint": "view_sheet", "arg": "The Informatorium"},
    {"label": "Races", "endpoint": "races_table"},
    {"label": "Scaling", "endpoint": "view_notion_db", "arg": "Scaling"},
    {"label": "Damage Calculation", "endpoint": "view_notion_db", "arg": "Damage Calculation"},
    {"label": "Roll Info", "endpoint": "view_sheet", "arg": "Roll Information"},
    {"label": "Skills", "endpoint": "view_sheet", "arg": "Skills"},
    {"label": "Zones", "endpoint": "view_sheet", "arg": "Zones"},
    {"label": "Gear Set", "endpoint": "view_sheet", "arg": "Gear Set"},
    {"label": "Crafting", "endpoint": "view_sheet", "arg": "Crafting"},
    {"label": "Resonance", "endpoint": "view_sheet", "arg": "RESONANCE"},
    {"label": "Mastery", "endpoint": "view_sheet", "arg": "MASTERY"},
    {"label": "Legacy", "endpoint": "view_sheet", "arg": "LEGACY"},
    {"label": "Clarifications", "endpoint": "view_sheet", "arg": "Clarifications & Mechanics"},
    {"label": "Items", "endpoint": "view_sheet", "arg": "Items"},
    {"label": "Gear", "endpoint": "view_sheet", "arg": "Gear"}
]

    return render_template("dashboard.html", user=user, data_buttons=data_buttons, generators=generator_sheets)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if USERS.get(username) == password:
            session["user"] = username
            return redirect(url_for("home"))
        return "Invalid credentials", 401
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route("/view/<sheet>")
@login_required
def view_sheet(sheet):
    if sheet not in sheets:
        return f"Sheet '{sheet}' not found.", 404
    df = sheets[sheet].fillna("").astype(str)
    headers = df.columns.tolist()
    rows = df.values.tolist()
    return render_template("view_sheet.html", sheet=sheet, headers=headers, rows=rows)

@app.route("/generate/<sheet>")
@login_required
def generate(sheet):
    if sheet not in generator_sheets:
        return f"'{sheet}' is not a generator sheet.", 403
    df = sheets[sheet].dropna(how="all")
    if df.empty:
        return "No data to generate."
    random_row = df.sample(n=1).to_dict(orient="records")[0]
    return render_template("generator.html", sheet=sheet, row=random_row)

@app.route("/potion-generator")
@login_required
def potion_generator():
    potion_df = pd.read_excel("static/Book 10.xlsx", sheet_name="Sheet1")
    potion_map = {
        str(row["Concat"]).strip(): row["POTION"]
        for _, row in potion_df.iterrows()
        if pd.notna(row["Concat"]) and pd.notna(row["POTION"])
    }
    selected = [request.args.get(f"ingredient{i}", "Nothing") for i in range(1, 11)]
    selected = [s for s in selected if s]
    combos = set()
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            a, b = selected[i].strip(), selected[j].strip()
            combo = f"{a} + {b}" if a <= b else f"{b} + {a}"
            combos.add(combo)
    matches = sorted([
        {"mix": combo, "result": potion_map[combo]}
        for combo in combos if combo in potion_map
    ], key=lambda x: x["mix"].lower())
    ingredients = sorted({part.strip() for combo in potion_map for part in combo.split('+')} | {"Nothing"})
    return render_template(
        "potion_generator.html",
        ingredients=ingredients,
        matches=matches,
        selected_ings_map={f"ingredient{i+1}": selected[i] if i < len(selected) else "" for i in range(10)}
    )

@app.route("/races-table")
@login_required
def races_table():
    path = "static/notion/Races Main 207ec6426bd5807b925cddd6c35d0f14_all.csv"
    df = pd.read_csv(path).fillna("")
    df.columns = df.columns.str.strip()
    if "RACE" in df.columns and "SUBTYPE" in df.columns:
        df["RACE"] = df["RACE"].apply(lambda x: x.split(' (')[0] if isinstance(x, str) else x)
        cols = df.columns.tolist()
        if cols.index("RACE") > cols.index("SUBTYPE"):
            race_idx, sub_idx = cols.index("RACE"), cols.index("SUBTYPE")
            cols[race_idx], cols[sub_idx] = cols[sub_idx], cols[race_idx]
            df = df[cols]
    stamina_col = next((col for col in df.columns if col.lower() == "stamina"), None)
    if stamina_col:
        df[stamina_col] = df[stamina_col].apply(lambda x: round(float(x)) if str(x).replace('.', '', 1).isdigit() else x)
    for col in [c for c in df.columns if "resistance" in c.lower()]:
        df[col] = df[col].apply(lambda x: f"{float(x)*100:.0f}%" if str(x).replace('.', '', 1).isdigit() else x)
    return render_template("races_table.html", headers=df.columns.tolist(), rows=df.values.tolist())

@app.route("/races-gallery")
@login_required
def races_gallery():
    path = "static/notion/Races Main 207ec6426bd5807b925cddd6c35d0f14_all.csv"
    df = pd.read_csv(path).fillna("")
    STAT_LABELS = [
        "Health", "Mana", "Conditions", "Defense", "Dispersion", "Strength", "Dexterity",
        "Power", "Stamina", "Fortitude", "Light Resistance", "Dark Resistance",
        "Fire Resistance", "Frost Resistance", "Wind Resistance", "Earth Resistance",
        "Lightning Resistance", "Bleed Resistance", "Poison Resistance"
    ]
    tree = {}
    for _, row in df.iterrows():
        kin, race, subrace = row.get("KIN", "").strip(), row.get("RACE", "").split(' (')[0].strip(), row.get("SUBTYPE", "").strip()
        if not (kin and race and subrace):
            continue
        stats = [row.get(col, "") for col in df.columns if col not in ("KIN", "RACE", "SUBTYPE")]
        resistance_start = STAT_LABELS.index("Light Resistance")
        stats[8] = str(round(float(stats[8]))) if str(stats[8]).replace('.', '', 1).isdigit() else stats[8]
        resistances = [
            f"{float(val)*100:.0f}%" if str(val).replace('.', '', 1).isdigit() else val
            for val in stats[resistance_start:resistance_start+9]
        ]
        full_stats = stats[:resistance_start] + resistances
        labeled_stats = list(zip(STAT_LABELS, full_stats[:len(STAT_LABELS)]))
        tree.setdefault(kin, {}).setdefault(race, []).append({"subrace": subrace, "stats": labeled_stats})
    return render_template("races_gallery.html", tree=tree)

@app.route("/notion-db")
@login_required
def notion_db_index():
    base_path = "static/notion"
    csv_files = [f for f in os.listdir(base_path) if f.endswith(".csv")]
    databases = [f.replace(".csv", "") for f in csv_files]
    return render_template("notion_index.html", databases=databases)

@app.route("/notion-db/<db>")
@login_required
def view_notion_db(db):
    path = f"static/notion/{db}.csv"
    if not os.path.exists(path):
        return f"{db} database not found.", 404
    df = pd.read_csv(path).fillna("N/A")
    return render_template("notion_table.html", db=db, headers=df.columns.tolist(), rows=df.values.tolist())

@app.route("/classes-view")
@login_required
def classes_view():
    path = os.path.join("static", "Data", "Normalized_Abilities.xlsx")
    table_df = pd.read_excel(path, sheet_name="Table").fillna("")
    data_df = pd.read_excel(path, sheet_name="Data").fillna("")
    affinity_df = pd.read_excel(path, sheet_name="Affinities S").fillna("")
    class_df = pd.read_excel(path, sheet_name="Classes S").fillna("")

    headers = table_df.columns.tolist()
    rows = table_df.values.tolist()

    ability_data = defaultdict(lambda: defaultdict(list))
    for _, row in data_df.iterrows():
        aff, typ = row["Affinity"], row["Type"]
        entry = {
            "Rank I": row.get("Rank I", "N/A") or "N/A",
            "Rank II": row.get("Rank II", "N/A") if typ != "Innate" else "N/A",
            "Rank III": row.get("Rank III", "N/A") if typ != "Innate" else "N/A"
        }
        ability_data[aff][typ].append(entry)

    affinity_df.columns = affinity_df.columns.str.strip().str.upper()
    class_df.columns = class_df.columns.str.strip()

    affinity_info = {
        row["AFFINITY"]: {
            "difficulty": row.get("DIFFICULTY", "Unknown"),
            "description": row.get("DESCRIPTION", "")
        }
        for _, row in affinity_df.iterrows() if pd.notna(row["AFFINITY"])
    }

    class_info = {
        row["Class"]: {
            "bonus": row.get("Starting Bonus", ""),
            "weapon": row.get("Starting Weapon", "")
        }
        for _, row in class_df.iterrows() if pd.notna(row["Class"])
    }

    return render_template(
        "classes_view.html",
        headers=headers,
        rows=rows,
        ability_data=ability_data,
        affinity_info=affinity_info,
        class_info=class_info
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
