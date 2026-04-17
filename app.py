import os
import re
import random
import sqlite3
from datetime import datetime
from functools import wraps, lru_cache
from collections import defaultdict, deque

from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
from authlib.integrations.flask_client import OAuth
import pandas as pd

# Optional: load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ------------------------------------------------------------------------------
# Flask / App setup
# ------------------------------------------------------------------------------
app = Flask(__name__)

# Trust Railway proxy and keep https scheme/host (MUST be after app is created)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.config.setdefault("SECRET_KEY", os.environ.get("SECRET_KEY", "change-this"))
app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True,
    PREFERRED_URL_SCHEME="https",
)

# --- end proxy/cookie block ---

# ENV_WARN_INSERTED
if not os.environ.get('GOOGLE_CLIENT_ID') or not os.environ.get('GOOGLE_CLIENT_SECRET'):
    print('[WARN] GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set in your shell.')
    print('       In PowerShell, run:')
    print('       $env:GOOGLE_CLIENT_ID="your_client_id"')
    print('       $env:GOOGLE_CLIENT_SECRET="your_client_secret"')
    print('       $env:OAUTHLIB_INSECURE_TRANSPORT="1"   # local only')
app.secret_key = "supersecretkey"

# Google OAuth via env
app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_CLIENT_SECRET"] = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Debug print so you can see it on startup
print("[oauth] client_id:", (app.config["GOOGLE_CLIENT_ID"][:8] + "...") if app.config["GOOGLE_CLIENT_ID"] else "MISSING")

oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Socket.IO
# --- Socket.IO setup ---
# Use eventlet in production (Railway), fall back to threading locally (e.g., Windows + Python 3.13)
try:
    import eventlet  # will succeed on Railway
    ASYNC_MODE = "eventlet"
except Exception:
    ASYNC_MODE = "threading"

socketio = SocketIO(app, async_mode=ASYNC_MODE, cors_allowed_origins="*")
print(f"[socketio] async_mode={ASYNC_MODE}")
# --- end Socket.IO setup ---

# ---------------------------------------------------------------------------
# Auth DB
DEFAULT_DB_PATH = os.path.join("data", "auth.db")  # local default is fine
DB_PATH = os.getenv("AUTH_DB_PATH", DEFAULT_DB_PATH)

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_auth_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            username TEXT UNIQUE,
            password_hash TEXT,
            google_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

init_auth_db()

def is_admin():
    # read allow-lists from env (comma separated)
    allow_emails = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
    allow_users  = {u.strip().lower() for u in os.getenv("ADMIN_USERNAMES", "").split(",") if u.strip()}

    email = (session.get("email") or "").strip().lower()
    uname = (session.get("username") or "").strip().lower()


    return (email and email in allow_emails) or (uname and uname in allow_users)

import admin_ext
admin_ext.init_admin(app, get_db)

# ------------------------------------------------------------------------------
# Gallery folders / helpers
# ------------------------------------------------------------------------------

# Hexes images live here:
PNG_UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'pngs')
# Factions images live here:
FACTIONS_FOLDER = os.path.join(app.root_path, 'static', 'factions')

# Entities & Landmarks image folders
ENTITIES_FOLDER  = os.path.join(app.root_path, 'static', 'entities')
LANDMARKS_FOLDER = os.path.join(app.root_path, 'static', 'landmarks')
os.makedirs(ENTITIES_FOLDER, exist_ok=True)
os.makedirs(LANDMARKS_FOLDER, exist_ok=True)
XP_FOLDER = os.path.join(app.root_path, 'static', 'xp')
os.makedirs(XP_FOLDER, exist_ok=True)

# ------------------------------------------------------------------------------
# Data / Excel loading
# ------------------------------------------------------------------------------
def _find_layer_list_xlsx() -> str:
    """Best-effort resolver for the Layer List workbook.

    Supports local dev + Railway/Gunicorn where cwd can vary.
    """
    env_path = os.environ.get("LAYER_LIST_XLSX") or os.environ.get("LAYER_LIST_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "data", "Layer List (7).xlsx"),
        os.path.join(base_dir, "data", "Layer List.xlsx"),
        os.path.join(base_dir, "Layer List (7).xlsx"),
        os.path.join(base_dir, "Layer List.xlsx"),
        os.path.join("data", "Layer List (7).xlsx"),
        os.path.join("data", "Layer List.xlsx"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p

    # Last resort: pick any xlsx that starts with "Layer List".
    try:
        for root in [base_dir, os.path.join(base_dir, "data"), os.getcwd(), os.path.join(os.getcwd(), "data")]:
            if not root or not os.path.isdir(root):
                continue
            for fn in os.listdir(root):
                if fn.lower().startswith("layer list") and fn.lower().endswith(".xlsx"):
                    cand = os.path.join(root, fn)
                    if os.path.exists(cand):
                        return cand
    except Exception:
        pass

    return os.path.join("data", "Layer List (7).xlsx")


EXCEL_PATH = _find_layer_list_xlsx()

RACES_SHEET_DF = None
CONDITIONS_MAP = None
# Used to invalidate CONDITIONS_MAP when the Excel file changes.
_CONDITIONS_MAP_MTIME = None
try:
    sheets_all = pd.read_excel(EXCEL_PATH, sheet_name=None)
    RACES_SHEET_DF = sheets_all.get("Races")
    sheets = sheets_all
except Exception as e:
    print(f"Failed to load Layer List workbook '{EXCEL_PATH}': {e}")
    sheets = {}
    RACES_SHEET_DF = None
CONDITIONS_MAP = None

import merchant_ext
merchant_ext.init_merchant(app, get_db, sheets)

import forge_helper_ext
forge_helper_ext.init_forge_helper(app)

# Sentient Generator (Gear sheet-based) + respects gear presence toggles from Gear+Items
import sentient_ext
try:
    from flask_login import login_required as _login_required
except Exception:
    _login_required = (lambda f: f)

sentient_ext.init_sentient(
    app,
    get_db,
    sheets_all if 'sheets_all' in globals() else sheets,
    EXCEL_PATH,
    _login_required
)
SHEET_NAMES = list(sheets.keys())
generator_sheets = [name for name in SHEET_NAMES if "Generator" in name]

# ------------------------------------------------------------------------------
# Races (Excel-driven) helpers

@lru_cache(maxsize=4)
def _load_races_df_cached(excel_path: str, mtime: float) -> pd.DataFrame:
    """Load and sanitize the Races sheet. Cached by file mtime."""
    df = pd.read_excel(excel_path, sheet_name="Races")
    df = df.dropna(how="all")

    # The workbook can contain other tables below; keep only the actual race rows.
    if "SUBTYPES" in df.columns:
        df = df[df["SUBTYPES"].notna()].copy()

    # In case of merged cells, fill down.
    for col in ["KIN", "RACES"]:
        if col in df.columns:
            df[col] = df[col].ffill()

    return df


def load_races_excel_df() -> pd.DataFrame:
    """Return the cleaned Races dataframe from the Layer List workbook."""
    global RACES_SHEET_DF
    try:
        if RACES_SHEET_DF is not None and isinstance(RACES_SHEET_DF, pd.DataFrame) and not RACES_SHEET_DF.empty:
            df = RACES_SHEET_DF.copy()
            df = df.dropna(how="all")
            if "SUBTYPES" in df.columns:
                df = df[df["SUBTYPES"].notna()].copy()
            for col in ["KIN", "RACES"]:
                if col in df.columns:
                    df[col] = df[col].ffill()
            return df
    except Exception:
        pass

    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(
            f"Layer List workbook not found at '{EXCEL_PATH}'. Set LAYER_LIST_XLSX or place it in ./data/."
        )

    mtime = os.path.getmtime(EXCEL_PATH)
    return _load_races_df_cached(EXCEL_PATH, mtime)

# ------------------------------------------------------------------------------
# Helpers: user display name
# ------------------------------------------------------------------------------
def _display_name_from_session():
    name = session.get("username")
    if not name:
        email = session.get("email")
        if email:
            name = email.split("@")[0]
    return name or "Adventurer"



@app.before_request
def hydrate_username_in_session():
    """If we have a user_id but no username/email in session, hydrate from DB."""
    try:
        if session.get("user_id") and not session.get("username"):
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT username, email FROM users WHERE id = ?", (session["user_id"],))
            u = cur.fetchone()
            conn.close()
            if u:
                if u.get("username"):
                    session["username"] = u["username"]
                if u.get("email") and not session.get("email"):
                    session["email"] = u["email"]
    except Exception:
        # best-effort; never block request
        pass

@app.context_processor
def inject_current_user_display():
    name = session.get("username")
    if not name:
        email = session.get("email")
        if email:
            name = email.split("@")[0]
    name = name or "Adventurer"
    return {
        "current_user_name": name,   # preferred
        "username": name,            # legacy alias used by older templates
        "display_name": name,        # optional alias
    }

# ------------------------------------------------------------------------------
# Login required decorator
# ------------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
@app.route("/__envcheck")
def __envcheck():
    return {
        "GOOGLE_CLIENT_ID": (os.getenv("GOOGLE_CLIENT_ID") or "")[:8] + "..." if os.getenv("GOOGLE_CLIENT_ID") else "missing",
        "GOOGLE_CLIENT_SECRET": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
        "OAUTHLIB_INSECURE_TRANSPORT": os.getenv("OAUTHLIB_INSECURE_TRANSPORT", "missing"),
    }


# --- Biome Event Generator (reads: data/Layer List (7).xlsx -> events) -----

# Biomes list (includes Anywhere)
BIOMES = [
    "Grasslands","Sundune","Sakura","Frostreach","Volcanica",
    "Grimwell","Elysian","Desolation","Bloodgrounds","Anywhere"
]

# Exact path to your Excel (relative to the app folder)
EVENTS_XLSX = os.path.join(app.root_path, "data", "Layer List (7).xlsx")
EVENTS_SHEET = "events"  # tab name

def read_events_df() -> pd.DataFrame:
    """Read the 'events' sheet and drop blank rows."""
    if not os.path.exists(EVENTS_XLSX):
        raise FileNotFoundError(f"Excel not found at {EVENTS_XLSX}")
    try:
        df = pd.read_excel(EVENTS_XLSX, sheet_name=EVENTS_SHEET, engine="openpyxl")
    except Exception:
        # fallback if openpyxl isn't installed
        df = pd.read_excel(EVENTS_XLSX, sheet_name=EVENTS_SHEET)
    return df.dropna(how="all")

def _norm_key(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())

def _find_col(df: pd.DataFrame, candidates) -> str | None:
    """
    Find a column name ignoring case/spacing/punctuation.

    First try exact matches (normalized),
    then fall back to substring matches so things like
    'Event Description' will match 'Event' or 'Description'.
    """
    want_list = [_norm_key(c) for c in candidates]

    # exact match
    for col in df.columns:
        col_key = _norm_key(col)
        if col_key in want_list:
            return col

    # substring fallback
    for col in df.columns:
        col_key = _norm_key(col)
        for w in want_list:
            if not w:
                continue
            if w in col_key or col_key in w:
                return col

    return None


def _pick_pool_80_20(df: pd.DataFrame, selected_biome: str) -> pd.DataFrame:
    """Return either the Selected biome rows (80%) or Anywhere rows (20%)."""
    biome_col = _find_col(df, ["Biome"])
    if not biome_col:
        raise ValueError("The 'events' sheet needs a 'Biome' column.")

    key = str(selected_biome).strip().lower()
    anywhere = df[df[biome_col].astype(str).str.strip().str.lower() == "anywhere"]
    selected = df[df[biome_col].astype(str).str.strip().str.lower() == key]

    # If user picked Anywhere, it's 100% Anywhere
    if key == "anywhere":
        return anywhere

    # Graceful fallbacks if one side is empty
    if selected.empty and anywhere.empty:
        return df.iloc[0:0]
    if selected.empty:
        return anywhere
    if anywhere.empty:
        return selected

    # 80% from selected, 20% from anywhere
    return anywhere if random.random() < 0.20 else selected

def _row_to_event(row: pd.Series, df_for_headers: pd.DataFrame) -> dict:
    """Convert one Excel row into an event dictionary used by the API.

    This version is intentionally very explicit:
    - If there is a column literally called 'Event', we always take that as
      the description.
    - Otherwise we fall back to several candidate names and finally to
      a heuristic pick of the first long text cell.
    """
    import pandas as _pd

    # --- helper: first column from a list that actually exists in this row ---
    def first_present(cols):
        for c in cols:
            if c and c in row.index:
                return c
        return None

    # Prefer literal names, but still fall back to _find_col
    num_col  = first_present(["Event #", "Event No"]) or _find_col(
        df_for_headers, ["Event #", "Event Num", "Event Number", "#", "ID"]
    )
    name_col = first_present(["Name"]) or _find_col(
        df_for_headers, ["Name", "Event Name", "Title"]
    )
    bio_col  = first_present(["Biome"]) or _find_col(
        df_for_headers, ["Biome"]
    )

    # *** DESCRIPTION: ALWAYS prefer the 'Event' column ***
    txt_col  = first_present(["Event"]) or _find_col(
        df_for_headers,
        [
            "Event",
            "Event Description",
            "Description",
            "Desc",
            "Event Text",
            "Text",
            "Story",
            "Flavor",
            "Flavor Text",
        ],
    )

    o1_col   = first_present(["Option 1"]) or _find_col(
        df_for_headers, ["Option 1", "Opt 1", "Choice 1"]
    )
    o2_col   = first_present(["Option 2"]) or _find_col(
        df_for_headers, ["Option 2", "Opt 2", "Choice 2"]
    )
    o3_col   = first_present(["Option 3"]) or _find_col(
        df_for_headers, ["Option 3", "Opt 3", "Choice 3"]
    )
    o4_col   = first_present(["Option 4"]) or _find_col(
        df_for_headers, ["Option 4", "Opt 4", "Choice 4"]
    )

    def v(col):
        return (row[col] if col and col in row and not _pd.isna(row[col]) else None)

    # --- description value with a last-resort heuristic ---
    event_text = v(txt_col)

    # If description is empty, grab the first "long" text cell that isn't
    # the name, biome, number or an option.
    if event_text is None or (isinstance(event_text, str) and not event_text.strip()):
        ignore = {c for c in [num_col, name_col, bio_col, o1_col, o2_col, o3_col, o4_col] if c}
        for col in df_for_headers.columns:
            if col in ignore:
                continue
            val = row.get(col)
            if isinstance(val, str) and len(val.strip()) >= 10:
                event_text = val.strip()
                break

    return {
        "eventNumber": v(num_col),
        "name":        v(name_col),
        "biome":       v(bio_col),
        "eventText":   event_text,
        "option1":     v(o1_col),
        "option2":     v(o2_col),
        "option3":     v(o3_col),
        "option4":     v(o4_col),
    }

# ---- Page (no selection-mode dropdown needed) ----
@app.route("/event-generator")
@login_required
def event_generator():
    return render_template(
        "event_generator.html",
        biomes=BIOMES,
        selected_biome=request.args.get("biome", "Grasslands"),
    )

# ---- API: one random event as JSON, with 80/20 weighting ----
@app.route("/api/events/random")
def api_events_random():
    biome = request.args.get("biome", "Grasslands")
    df = read_events_df()
    pool = _pick_pool_80_20(df, biome)
    if pool.empty:
        return jsonify({"error": "No events found for that selection."}), 404

    row = pool.sample(1).iloc[0]
    return jsonify(_row_to_event(row, df))
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def home():
    logical = [
        {"label": "The Informatorium", "endpoint": "view_sheet", "arg": "The Informatorium"},
        {"label": "Races", "endpoint": "races_table"},
        {"label": "Classes", "endpoint": "classes_view"},
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
        {"label": "Gear + Items", "endpoint": "view_sheet", "arg": "Gear+Items"},
        # Hexes (no new tab)
        {"label": "Hexes", "endpoint": "png_gallery"},
        # Factions
        {"label": "Factions", "endpoint": "factions_gallery"},
        {"label": "Entities", "endpoint": "entities_gallery"},
        {"label": "Landmarks", "endpoint": "landmarks_gallery"},
        {"label": "Xp-Chart", "endpoint": "xp_gallery"},
        {"label": "Game Guide", "endpoint": "guide"},
        {"label": "Quests", "endpoint": "view_sheet", "arg": "Quests"},
        {"label": "Bestiary", "endpoint": "bestiary"},
        # NOTE: removed {"label": "Random Quest", "endpoint": "quest_generator"} from Data

    ]


    def _safe_url(endpoint, **kwargs):
        try:
            return url_for(endpoint, **kwargs)
        except Exception:
            if endpoint == "view_sheet" and "sheet" in kwargs:
                return f"/view/{kwargs['sheet']}"
            if endpoint == "view_notion_db" and "db" in kwargs:
                return f"/notion-db/{kwargs['db']}"
            try:
                return url_for(endpoint)
            except Exception:
                return "/"

    data_buttons = []
    for btn in logical:
        if btn.get("arg"):
            if btn["endpoint"] == "view_notion_db":
                href = _safe_url("view_notion_db", db=btn["arg"])
            elif btn["endpoint"] == "view_sheet":
                href = _safe_url("view_sheet", sheet=btn["arg"])
            else:
                href = _safe_url(btn["endpoint"])
        else:
            href = _safe_url(btn["endpoint"])
        resolved = dict(btn)
        resolved["href"] = href
        data_buttons.append(resolved)

     # Add Random Quests to the Generators section
    # and REMOVE Potions from the loop (we render it manually for admins)
    generators = [g for g in generator_sheets if g.strip().lower() != "potions"]
    generators.append("Random Quests")

    return render_template(
        "dashboard.html",
        data_buttons=data_buttons,
        generators=generators,
        show_potions=is_admin(),   # admin-only manual Potions card
    )


@app.route("/entities")
@app.route("/Entities")
@login_required
def entities_gallery():
    files = []
    if os.path.isdir(ENTITIES_FOLDER):
        files = sorted([f for f in os.listdir(ENTITIES_FOLDER) if f.lower().endswith(".png")])
    return render_template("entities_gallery.html", png_files=files)

@app.route("/landmarks")
@app.route("/Landmarks")
@login_required
def landmarks_gallery():
    files = []
    if os.path.isdir(LANDMARKS_FOLDER):
        files = sorted([f for f in os.listdir(LANDMARKS_FOLDER) if f.lower().endswith(".png")])
    return render_template("landmarks_gallery.html", png_files=files)

@app.route("/quest-generator")
@login_required
def quest_generator():
    import numpy as np
    sheet_name = "Quests"

    if sheet_name not in sheets:
        return "The 'Quests' sheet was not found in your Excel.", 404
    df = sheets[sheet_name].dropna(how="all").copy()
    if df.empty:
        return "No quests found in the 'Quests' sheet."

    # --- find columns (case-insensitive) ---
    def find_col_by_keywords(keywords):
        kws = {k.lower() for k in keywords}
        for c in df.columns:
            if str(c).strip().lower() in kws:
                return c
        return None

    # Prefer Name/Title for the card heading (template still falls back if missing)
    title_col = find_col_by_keywords({"name", "title"})

    # Objective text we want to display under the title
    objective_col = find_col_by_keywords({
        "requirement", "requirements", "objective", "objectives",
        "task", "tasks", "goal", "goals", "description"
    })
    # If none of those exist, try "Quest" (but not if it's the title itself)
    if objective_col is None:
        qcol = find_col_by_keywords({"quest"})
        if qcol and qcol != title_col:
            objective_col = qcol

    # Difficulty handling
    diff_col = find_col_by_keywords({"difficulty"})

    # formatter (hide .0)
    def fmt_cell(x):
        if pd.isna(x):
            return ""
        if isinstance(x, (int, np.integer)):
            return str(x)
        if isinstance(x, (float, np.floating)):
            if np.isfinite(x) and float(x).is_integer():
                return str(int(x))
            return str(x)
        return str(x)

    note = None
    picks = []

    if diff_col is None:
        note = "No Difficulty column found — showing any 3 quests."
        picks = df.sample(n=min(3, len(df))).to_dict(orient="records")
    else:
        # normalize difficulty
        def norm(s):
            s = str(s).strip().lower()
            if s in ("easy", "e", "ez", "beginner", "low"):
                return "Easy"
            if s in ("medium", "normal", "mid", "moderate", "m", "avg"):
                return "Medium"
            if s in ("hard", "difficult", "h", "high"):
                return "Hard"
            return str(s).title() if s else "Unspecified"

        df["_norm_diff"] = df[diff_col].apply(norm)

        targets = ["Easy", "Medium", "Hard"]
        chosen_idx = set()

        for t in targets:
            sub = df[df["_norm_diff"] == t]
            if not sub.empty:
                row = sub.sample(n=1)
                chosen_idx.add(row.index[0])
                picks.append(row.iloc[0].to_dict())

        if len(picks) < 3:
            remaining = df[~df.index.isin(chosen_idx)]
            if not remaining.empty:
                extra = remaining.sample(n=min(3 - len(picks), len(remaining)))
                for _, r in extra.iterrows():
                    picks.append(r.to_dict())

    # format & drop helper
    formatted = []
    for row in picks:
        out = {k: fmt_cell(v) for k, v in row.items()}
        out.pop("_norm_diff", None)
        formatted.append(out)

    columns = list(df.columns)  # preserve original order

    return render_template(
        "quests_random.html",
        quests=formatted,
        columns=columns,
        req_col=objective_col,   # <-- the actual “what to do”
        title_col=title_col,     # (optional, in case you want to use it)
        note=note
    )

@app.route("/xp")
@login_required
def xp_gallery():
    files = []
    if os.path.isdir(XP_FOLDER):
        files = sorted([f for f in os.listdir(XP_FOLDER) if f.lower().endswith(".png")])
    return render_template("xp.html", png_files=files)   # template is lowercase

@app.route("/bestiary")
@login_required
def bestiary():
    sheet_name = "Bestiary"

    if sheet_name not in sheets:
        return "Sheet 'Bestiary' not found in the main Excel.", 404

    df = sheets[sheet_name].copy()

    # Clean headers and drop empty rows
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")

    if "Character name" not in df.columns:
        return "The Bestiary sheet needs a 'Character name' column.", 500

    df = df[df["Character name"].notna()]


    def fmt_cell(x):
        if pd.isna(x):
            return ""
        if isinstance(x, (int, float)):
            if isinstance(x, float) and float(x).is_integer():
                return str(int(x))
            return str(x)
        return str(x)
    try:
        df = df.map(fmt_cell)  # pandas >= 3
    except AttributeError:
        df = df.applymap(fmt_cell)  # pandas < 3
    raw_creatures = df.to_dict(orient="records")

    # Excel headers for resistances
    resistance_fields = [
        "Light R", "Dark R", "Fire R", "Frost R",
        "Wind R", "Earth R", "Lightning R", "Bleed R", "Poison R",
    ]

    # Fixed colors by element (roughly matching your Excel colors)
    color_map = {
        "Light":     "text-slate-200 border-slate-400/60 bg-slate-500/10",
        "Dark":      "text-white border-white/60 bg-white/10",
        "Fire":      "text-red-400 border-red-500/60 bg-red-500/10",
        "Frost":     "text-sky-300 border-sky-500/60 bg-sky-500/10",
        "Wind":      "text-teal-300 border-teal-500/60 bg-teal-500/10",
        "Earth":     "text-amber-300 border-amber-500/60 bg-amber-500/10",
        "Lightning": "text-yellow-300 border-yellow-500/60 bg-yellow-500/10",
        "Bleed":     "text-rose-400 border-rose-500/60 bg-rose-500/10",
        "Poison":    "text-emerald-400 border-emerald-500/60 bg-emerald-500/10",
    }

    formatted_creatures = []

    for row in raw_creatures:
        res_list = []

        for key in resistance_fields:
            raw_val = row.get(key, "")
            if raw_val is None or raw_val == "":
                continue

            # parse numeric to percentage if possible
            value_str = str(raw_val)
            try:
                val = float(str(raw_val))
                pct = int(round(val * 100))    # e.g. 0.5 -> 50
                value_str = f"{pct}%"
            except ValueError:
                pass  # leave value_str as-is if not numeric

            label = key.replace(" R", "")     # "Light R" -> "Light"
            css = color_map.get(label, "text-white border-white/25 bg-white/5")

            res_list.append({
                "label": label,
                "value": value_str,
                "css": css,
            })

        row["resistances"] = res_list
        formatted_creatures.append(row)

    return render_template(
        "bestiary.html",
        creatures=formatted_creatures,
    )


# … other imports …

import numpy as np

# Backwards-compatible aliases: if legacy tabs "Gear" / "Items" are removed from Excel,
# these routes still work and simply filter the unified Gear+Items catalog.
@app.route("/view/Gear")
@login_required
def view_gear_alias():
    return redirect(url_for("view_sheet", sheet="Gear+Items", kind="Gear"))


@app.route("/view/Items")
@login_required
def view_items_alias():
    return redirect(url_for("view_sheet", sheet="Gear+Items", kind="Item"))

@app.route("/view/<sheet>")
@login_required
def view_sheet(sheet):
    if sheet not in sheets:
        return f"Sheet '{sheet}' not found.", 404

    # hide .0 for integers
    def fmt_cell(x):
        if pd.isna(x):
            return ""
        if isinstance(x, (int, np.integer)):
            return str(x)
        if isinstance(x, (float, np.floating)):
            if np.isfinite(x) and float(x).is_integer():
                return str(int(x))
            return str(x)
        return str(x)

    df = sheets[sheet].copy()
    try:
        df = df.map(fmt_cell)  # pandas >= 3
    except AttributeError:
        df = df.applymap(fmt_cell)  # pandas < 3

    # Special-case: Gear+Items is the canonical combined catalog.
    # If the user deletes the legacy "Gear" and "Items" tabs, the site still works.
    sheet_key = (sheet or "").strip().lower().replace(" ", "")
    if sheet_key in {"gear+items", "gear&items", "gearitems", "gear_and_items"} or (
        "gear" in sheet_key and "item" in sheet_key
    ):
        df_gi = df.fillna("").copy()

        # Normalize column headers defensively
        def _norm_col(s):
            return re.sub(r"[^a-z]+", "", str(s or "").lower())

        col_norm = {c: _norm_col(c) for c in df_gi.columns}
        df_gi = df_gi.rename(columns=col_norm)

        # Canonical column mapping
        colmap = {}
        wants = {
            "kind": {"kind", "type"},
            "rarity": {"rarity"},
            "name": {"name", "gearitem", "title"},
            "gold": {"gold", "price", "cost"},
            "artifact": {"artifact", "isartifact"},
        }
        for canon, candidates in wants.items():
            for c in df_gi.columns:
                if c in candidates:
                    colmap[canon] = c
                    break

        missing = [k for k in wants if k not in colmap]
        if missing:
            return (
                "Gear+Items sheet is missing required columns. Expected: Kind, Rarity, Name, Gold, Artifact.",
                500,
            )

        k, r, n, g, a = (
            colmap["kind"],
            colmap["rarity"],
            colmap["name"],
            colmap["gold"],
            colmap["artifact"],
        )
        out = df_gi[[k, r, n, g, a]].copy()

        # Clean/standardize
        out[n] = out[n].astype(str)
        out = out[out[n].str.strip().ne("")].copy()
        out = out[~out[n].str.contains(r"\*\*insert\*\*", flags=re.I, na=False)].copy()

        # Updated rarity extraction to include Astral and Ultimate
        out[r] = (
            out[r]
            .astype(str)
            .str.strip()
            .str.extract(r"(?i)(Common|Uncommon|Rare|Epic|Legendary|Mythic|Astral|Ultimate)")[0]
            .str.title()
        )
        out = out[out[r].isin([
            "Common", "Uncommon", "Rare", "Epic",
            "Legendary", "Mythic", "Astral", "Ultimate"
        ])].copy()

        # Parse gold like "600 Gold" -> 600
        out[g] = (
            out[g].astype(str)
            .str.replace("\xa0", " ", regex=False)
            .str.extract(r"(\d+)", expand=False)
            .fillna("0")
            .astype(int)
        )

        # Artifact -> bool
        out[a] = out[a].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})

        # Canonical display name (before first ':')
        def _canon_name(s):
            s = str(s or "")
            head, *_ = s.split(":", 1)
            return re.sub(r"\s+", " ", head).strip()

        # Filters (server-side) via querystring
        q = (request.args.get("q") or "").strip()
        kind = (request.args.get("kind") or "").strip().title()  # Gear / Item
        rarity = (request.args.get("rarity") or "").strip().title()
        artifact = (request.args.get("artifact") or "").strip().lower()  # any/yes/no
        sort = (request.args.get("sort") or "rarity").strip().lower()  # name/gold/rarity

        if q:
            qq = q.lower()
            out = out[out[n].str.lower().str.contains(re.escape(qq), na=False)].copy()

        if kind in {"Gear", "Item"}:
            out = out[out[k].astype(str).str.strip().str.title().eq(kind)].copy()

        # Updated rarity filter
        if rarity in {"Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Astral", "Ultimate"}:
            out = out[out[r].eq(rarity)].copy()

        if artifact in {"yes", "true", "1"}:
            out = out[out[a]].copy()
        elif artifact in {"no", "false", "0"}:
            out = out[~out[a]].copy()

        # Updated rarity order: Common lowest, Ultimate highest
        rar_order = {
            "Common": 0,
            "Uncommon": 1,
            "Rare": 2,
            "Epic": 3,
            "Legendary": 4,
            "Mythic": 5,
            "Astral": 6,
            "Ultimate": 7,
        }
        out["_rar_rank"] = out[r].map(rar_order).fillna(-1).astype(int)

        if sort == "name":
            out = out.sort_values(by=[n], key=lambda s: s.astype(str).str.lower(), ascending=True)
        elif sort == "gold":
            out = out.sort_values(by=[g, "_rar_rank", n], ascending=[True, False, True])
        else:
            out = out.sort_values(by=["_rar_rank", n], ascending=[True, True])

        items = []
        for _, row in out.iterrows():
            full = str(row[n])
            canon = _canon_name(full)
            detail = ""
            if ":" in full:
                detail = full.split(":", 1)[1].strip()
            items.append(
                {
                    "kind": str(row[k]).strip().title(),
                    "rarity": str(row[r]).strip().title(),
                    "name": canon,
                    "detail": detail,
                    "gold": int(row[g]),
                    "artifact": bool(row[a]),
                }
            )
        return render_template(
            "gear_items.html",
            sheet="Gear + Items",
            items=items,
            q=q,
            kind=kind,
            rarity=rarity,
            artifact=artifact,
            sort=sort,
        )

    # Special-case: Roll Information uses a dedicated UI (d20 selector + all outcomes)
    if sheet.strip().lower() == "roll information":
        # The sheet is arranged in blocks that start with a row where column A == "Roll".
        # Each block contains 1-20 outcomes for one or more scenarios across columns.
        df_roll = df.fillna("")

        cols = df_roll.columns.tolist()
        first_col = cols[0]

        def _group_for_col(idx: int) -> str:
            """Return the nearest non-'Unnamed' header to the left (handles merged Excel headers)."""
            if idx <= 0 or idx >= len(cols):
                return ""
            name = _norm(cols[idx])
            if name and not name.lower().startswith("unnamed"):
                return name
            j = idx - 1
            while j >= 1:
                prev = _norm(cols[j])
                if prev and not prev.lower().startswith("unnamed"):
                    return prev
                j -= 1
            return ""

        def _scale_from_group(group_header: str) -> str:
            u = (group_header or "").upper()
            if "MOBILITY" in u:
                return "Mobility"
            if "WISDOM" in u:
                return "Wisdom"
            if "MIGHT" in u:
                return "Might"
            if "NEUTRAL" in u or "NOTHING" in u:
                return "Nothing"
            return "Nothing"

        def _norm(v):
            s = str(v or "")
            # normalize non-breaking spaces from Excel exports
            s = s.replace("\xa0", " ").replace(" ", " ")
            return s.strip()

        # Find the start of each d20 block
        roll_starts = df_roll.index[df_roll[first_col].astype(str).str.strip().str.lower() == "roll"].tolist()
        roll_starts.sort()

        # Find the Status table start (if present)
        status_starts = df_roll.index[df_roll[first_col].astype(str).str.strip().str.lower() == "status roll"].tolist()
        status_start = status_starts[0] if status_starts else len(df_roll)

        roll_tables = []
        for i, start in enumerate(roll_starts):
            end = roll_starts[i + 1] if i + 1 < len(roll_starts) else status_start
            for c_idx in range(1, len(cols)):
                col = cols[c_idx]
                group_header = _group_for_col(c_idx)
                scales_with = _scale_from_group(group_header)

                label = _norm(df_roll.at[start, col])
                if not label:
                    continue
                outcomes = {}
                for r_i in range(start + 1, end):
                    roll_val = _norm(df_roll.at[r_i, first_col])
                    if roll_val.isdigit():
                        n_roll = int(roll_val)
                        if 1 <= n_roll <= 20:
                            outcomes[str(n_roll)] = _norm(df_roll.at[r_i, col])
                if outcomes:
                    roll_tables.append({"label": label, "outcomes": outcomes, "scales_with": scales_with, "group": group_header})

        status_rows = []
        if status_starts:
            s0 = status_starts[0]
            c_roll = first_col
            c_rand = cols[1] if len(cols) > 1 else None
            c_neg = cols[2] if len(cols) > 2 else None
            c_type = cols[3] if len(cols) > 3 else None

            for r_i in range(s0 + 1, len(df_roll)):
                v = _norm(df_roll.at[r_i, c_roll])
                if not v or not v.isdigit():
                    continue
                status_rows.append({
                    "status_roll": v,
                    "random_status_roll": _norm(df_roll.at[r_i, c_rand]) if c_rand else "",
                    "negative_status_roll": _norm(df_roll.at[r_i, c_neg]) if c_neg else "",
                    "type": _norm(df_roll.at[r_i, c_type]) if c_type else "",
                })

        return render_template(
            "roll_information.html",
            sheet="Roll Info",
            roll_tables=roll_tables,
            status_rows=status_rows,
        )

    # default payloads
    row_colors = None
    kin_legend = None
    col_colors = None
    headers_with_colors = None
    rows_with_colors = None

    if sheet.strip().upper() == "LEGACY":
        KIN_COLORS = {
            "LIVING":    {"bg": "#2a2a23", "border": "#494936", "chip": "#3a3a2d"},
            "FAE":       {"bg": "#232a2f", "border": "#364954", "chip": "#2b3840"},
            "CONSTRUCT": {"bg": "#2a272f", "border": "#4a4457", "chip": "#353044"},
            "UNDEAD":    {"bg": "#2f262a", "border": "#574149", "chip": "#402d34"},
            "DEMON":     {"bg": "#312524", "border": "#5a3c39", "chip": "#442f2c"},
            "DIVINE":    {"bg": "#292b2f", "border": "#434651", "chip": "#33363f"},
        }
        DEFAULT_COLOR = {"bg": "#242424", "border": "#3a3a3a", "chip": "#2c2c2c"}

        headers_list = df.columns.tolist()

        # per-column colors (keep first column neutral)
        col_colors = []
        for i, h in enumerate(headers_list):
            if i == 0:
                col_colors.append(DEFAULT_COLOR)
            else:
                key = str(h).strip().upper()
                col_colors.append(KIN_COLORS.get(key, DEFAULT_COLOR))

        # legend from headers (skip first col)
        kin_legend = [{"kin": h, **KIN_COLORS.get(str(h).strip().upper(), DEFAULT_COLOR)}
                      for h in headers_list[1:]]

        # pre-zip (no Jinja |zip needed)
        headers_with_colors = list(zip(headers_list, col_colors))
        rows_with_colors = [list(zip(row, col_colors)) for row in df.values.tolist()]

    return render_template(
        "view_sheet.html",
        sheet=sheet,
        headers=df.columns.tolist(),
        rows=df.values.tolist(),
        row_colors=row_colors,
        kin_legend=kin_legend,
        col_colors=col_colors,
        headers_with_colors=headers_with_colors,
        rows_with_colors=rows_with_colors,
    )

from urllib.parse import unquote

@app.route("/generate/<sheet>")
@login_required
def generate(sheet):
    # normalize the name coming from the URL
    s = unquote(sheet).strip().lower()

    # Special-case: our custom generator that's NOT an Excel "Generator" sheet
    if s in ("random quests", "random quest", "quests random"):
        return quest_generator()  # reuse your route that picks 3 quests

    # --- existing behavior for Excel-based generators ---
    if sheet not in generator_sheets:
        return f"'{sheet}' is not a generator sheet.", 403

    df = sheets[sheet].dropna(how="all")
    if df.empty:
        return "No data to generate."

    random_row = df.sample(n=1).to_dict(orient="records")[0]
    return render_template("generator.html", sheet=sheet, row=random_row)

@app.route("/potion-generator")
def potion_generator():
    potion_df = pd.read_excel("static/Book 10.xlsx", sheet_name="Sheet1")
    potion_map = {
        str(row["Concat"]).strip(): row["POTION"]
        for _, row in potion_df.iterrows()
        if pd.notna(row["Concat"]) and pd.notna(row["POTION"])
    }
    selected = [request.args.get(f"ingredient{i}", "Nothing") for i in range(1, 10 + 1)]
    selected = [s for s in selected if s]
    combos = set()
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            a, b = selected[i].strip(), selected[j].strip()
            combo = f"{a} + {b}" if a <= b else f"{b} + {a}"
            combos.add(combo)
    matches = sorted(
        [{"mix": combo, "result": potion_map[combo]} for combo in combos if combo in potion_map],
        key=lambda x: x["mix"].lower(),
    )
    ingredients = sorted({part.strip() for combo in potion_map for part in combo.split("+")} | {"Nothing"})
    return render_template(
        "potion_generator.html",
        ingredients=ingredients,
        matches=matches,
        selected_ings_map={f"ingredient{i+1}": selected[i] if i < len(selected) else "" for i in range(10)},
    )

# ------------------------ Galleries ------------------------

# Hexes gallery (PNG files only). Added friendly aliases /hexes and /Hexes
@app.route("/png-gallery")
@app.route("/hexes")
@app.route("/Hexes")
@login_required
def png_gallery():
    os.makedirs(PNG_UPLOAD_FOLDER, exist_ok=True)
    files = [f for f in os.listdir(PNG_UPLOAD_FOLDER) if f.lower().endswith(".png")]
    files.sort()
    return render_template("png_gallery.html", png_files=files)

# (Upload route removed per your request)

# Factions gallery (PNG files only)
@app.route("/factions")
@app.route("/Factions")  # optional alias
@login_required
def factions_gallery():
    os.makedirs(FACTIONS_FOLDER, exist_ok=True)
    files = [f for f in os.listdir(FACTIONS_FOLDER) if f.lower().endswith(".png")]
    files.sort()
    return render_template("factions_gallery.html", png_files=files)


# =====================
# ADMIN ROLES - app.py
# =====================

def _ensure_is_admin_column():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if "is_admin" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    conn.close()

_ensure_is_admin_column()

def _bootstrap_admins_from_env():
    emails = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS","").split(",") if e.strip()]
    if not emails: return
    conn = get_db()
    cur = conn.cursor()
    for e in emails:
        cur.execute("UPDATE users SET is_admin=1 WHERE lower(email)=?", (e,))
    conn.commit(); conn.close()

_bootstrap_admins_from_env()

@app.before_request
def hydrate_username_in_session():
    try:
        if session.get("user_id") and (not session.get("username") or 'is_admin' not in session):
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT username, email, is_admin FROM users WHERE id = ?", (session['user_id'],))
            u = cur.fetchone(); conn.close()
            if u:
                if u["username"]:
                    session["username"] = u["username"]
                if u["email"] and not session.get("email"):
                    session["email"] = u["email"]
                session["is_admin"] = bool(u["is_admin"])
    except Exception:
        pass

@app.context_processor
def inject_current_user_display():
    name = session.get("username") or (session.get("email").split("@")[0] if session.get("email") else "Adventurer")
    return {"current_user_name": name, "username": name, "display_name": name, "is_admin": bool(session.get("is_admin"))}

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return "Admins only.", 403
        return f(*args, **kwargs)
    return wrapper

    conn = get_db(); cur = conn.cursor()
    if make == 0:
        cur.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
        cnt = cur.fetchone()[0]
        if cnt <= 1 and user_id == me:
            conn.close()
            return redirect(url_for('admin_panel', msg="Cannot remove the last remaining admin (yourself)."))

    cur.execute("UPDATE users SET is_admin=? WHERE id=?", (make, user_id))
    conn.commit(); conn.close()

    if user_id == me:
        session["is_admin"] = bool(make)

    return redirect(url_for('admin_panel', msg="Updated."))



# ------------------------ Tables/Views ------------------------

@lru_cache(maxsize=2)
def _load_conditions_map_cached(path: str, mtime: float) -> dict:
    # Condition->Effect mapping from the Races sheet (cols A:B starting at row 111)
    try:
        # Row 111 (1-indexed) -> skip first 110 rows
        df = pd.read_excel(path, sheet_name="Races", usecols="A:B", skiprows=110)
    except Exception:
        return {}

    df = df.dropna(how="all")
    if df.empty or df.shape[1] < 2:
        return {}

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        cond = str(row.iloc[0]).strip() if row.iloc[0] is not None else ""
        eff = str(row.iloc[1]).strip() if row.iloc[1] is not None else ""
        if not cond or cond.lower() == "nan":
            continue
        if not eff or eff.lower() == "nan":
            continue
        mapping[str(cond).strip().lower()] = eff

    return mapping


def load_conditions_map() -> dict:
    global CONDITIONS_MAP
    try:
        # Conditions live in the same Layer List workbook used for races.
        mtime = os.path.getmtime(EXCEL_PATH)
    except Exception:
        mtime = 0

    cached_mtime = getattr(load_conditions_map, "_cached_mtime", None)

    if CONDITIONS_MAP is None or cached_mtime != mtime:
        if cached_mtime != mtime:
            _load_conditions_map_cached.cache_clear()
        CONDITIONS_MAP = _load_conditions_map_cached(EXCEL_PATH, mtime)
        setattr(load_conditions_map, "_cached_mtime", mtime)

    return CONDITIONS_MAP


@app.route("/races-table")
@app.route("/races")
@app.route("/races_table")
@login_required
def races_table():
    """Races page (Excel-driven).

    Uses the **Races** tab from the Layer List workbook.
    Shows columns A–V in the UI, and uses the description columns for hover.
    """

    df = load_races_excel_df().fillna("")

    # Optional search (server-side to keep rowspans consistent)
    q = (request.args.get("q") or "").strip()
    if q:
        ql = q.lower()
        def _contains(col):
            return df[col].astype(str).str.lower().str.contains(ql, na=False)
        mask = False
        for col in ["KIN", "RACES", "SUBTYPES", "CONDITIONS"]:
            if col in df.columns:
                mask = mask | _contains(col)
        df = df[mask]

    base_cols = [
        "KIN",
        "RACES",
        "SUBTYPES",
        "HEALTH",
        "MANA",
        "CONDITIONS",
        "CONDITION EFFECTS",
        "DEFENSE",
        "DISPERSION",
        "STRENGTH",
        "DEXTERITY",
        "POWER",
        "STAMINA",
        "FORTITUDE",
    ]
    # Elemental resistances (Excel columns N..V)
    # NOTE: names must match the header text in the Races sheet exactly.
    res_cols = [
        "LIGHT RESISTANCE",
        "DARK RESISTANCE",
        "FIRE RESISTANCE",
        "FROST RESISTANCE",
        "WIND RESISTANCE",
        "EARTH RESISTANCE",
        "LIGHTNING RESISTANCE",
        "BLEED RESISTANCE",
        "POISON RESISTANCE",
    ]
    hover_cols = {
        "race_desc": "Race Description",
        "subtype_desc": "Subtype Description",
    }

    keep_cols = [c for c in base_cols + res_cols if c in df.columns]
    extra_cols = [c for c in hover_cols.values() if c in df.columns]
    df_view = df[keep_cols + extra_cols].copy()

    # Condition effects map (from the Conditions block in the same Excel sheet)
    cond_effect = load_conditions_map()

    def _split_conditions(val):
        if val is None:
            return []
        s = str(val).strip()
        if not s:
            return []
        return [p.strip() for p in re.split(r'[;,\n]+', s) if p and p.strip()]


    def _as_int(v):
        try:
            if v == "" or v is None:
                return ""
            fv = float(v)
            if abs(fv - round(fv)) < 1e-9:
                return str(int(round(fv)))
            return str(fv)
        except Exception:
            return str(v)

    def _pct_str(v):
        try:
            if v == "" or v is None:
                return ""
            fv = float(v)
            return f"{int(round(fv * 100))}%"
        except Exception:
            return str(v)

    def _pct_color(v):
        try:
            fv = float(v)
        except Exception:
            return ""
        fv = max(-1.0, min(1.0, fv))
        if fv >= 0.70:
            return "#22c55e"
        if fv >= 0.40:
            return "#4ade80"
        if fv >= 0.20:
            return "#86efac"
        if fv >= 0.05:
            return "#fde047"
        if fv > -0.05:
            return "#fbbf24"
        if fv > -0.20:
            return "#fb923c"
        if fv > -0.40:
            return "#f87171"
        return "#ef4444"

    # Build rows for the template
    rows = []
    for _, r in df_view.iterrows():
        row = {
            "KIN": r.get("KIN", ""),
            "RACES": r.get("RACES", ""),
            "SUBTYPES": r.get("SUBTYPES", ""),
            "race_desc": str(r.get(hover_cols["race_desc"], "")).strip(),
            "subtype_desc": str(r.get(hover_cols["subtype_desc"], "")).strip(),
        }

        # Build hoverable condition tokens (Condition -> Effect from the Excel Conditions block).
        row['condition_effects'] = str(r.get('CONDITION EFFECTS', '')).strip()

        row['conditions_list'] = [
            {'name': c, 'effect': cond_effect.get(c.lower(), '')}
            for c in _split_conditions(r.get('CONDITIONS', ''))
        ]

        # Stats
        for c in base_cols[3:]:
            if c in ('CONDITIONS', 'CONDITION EFFECTS'):
                continue
            if c in df_view.columns:
                row[c] = _as_int(r.get(c, ""))

        # Resistances as % + heat color
        res = []
        for c in res_cols:
            if c in df_view.columns:
                val_raw = r.get(c, "")
                res.append({"key": c, "text": _pct_str(val_raw), "bg": _pct_color(val_raw)})
        row["res"] = res

        rows.append(row)

    # Compute rowspans (Excel-like merged cells for KIN and RACES)
    for row in rows:
        row["kin_rowspan"] = 0
        row["race_rowspan"] = 0

    i = 0
    while i < len(rows):
        kin = rows[i]["KIN"]
        j = i
        while j < len(rows) and rows[j]["KIN"] == kin:
            j += 1
        rows[i]["kin_rowspan"] = j - i

        k = i
        while k < j:
            race = rows[k]["RACES"]
            m = k
            while m < j and rows[m]["RACES"] == race:
                m += 1
            rows[k]["race_rowspan"] = m - k
            k = m
        i = j

    return render_template(
        "races_table.html",
        q=q,
        rows=rows,
        base_cols=[c for c in base_cols if c in keep_cols],
        res_cols=[c for c in res_cols if c in keep_cols],
    )

@app.route("/notion-db/<db>")
@login_required
def view_notion_db(db):
    path = f"static/notion/{db}.csv"
    if not os.path.exists(path):
        return f"{db} database not found.", 404
    df = pd.read_csv(path).fillna("N/A")
    return render_template("notion_table.html", db=db, headers=df.columns.tolist(), rows=df.values.tolist())

@app.route("/guide")
@login_required
def guide():
    # you can later switch to multiple files (e.g. ?p=intro.md)
    return render_template("guide.html", guide_file="guide/guide.md")


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
        aff = (row.get("Affinity") or "").strip()
        typ = (row.get("Type") or "").strip()
        if not aff or not typ:
            continue

        # Read ranks, default to empty string, then fall back to "N/A" if still blank
        r1 = (row.get("Rank I") or "").strip()
        r2 = (row.get("Rank II") or "").strip()
        r3 = (row.get("Rank III") or "").strip()

        ability_data[aff][typ].append({
            "Rank I": r1 or "N/A",
            "Rank II": r2 or "N/A",
            "Rank III": r3 or "N/A",
        })

    affinity_df.columns = affinity_df.columns.str.strip().str.upper()
    class_df.columns = class_df.columns.str.strip()

    affinity_info = {
        row["AFFINITY"]: {
            "difficulty": row.get("DIFFICULTY", "Unknown"),
            "description": row.get("DESCRIPTION", ""),
        }
        for _, row in affinity_df.iterrows()
        if pd.notna(row.get("AFFINITY"))
    }

    class_info = {
        row["Class"]: {
            "bonus": row["Starting Bonus:"],
            "weapon": row["Starting Weapon:"],
        }
        for _, row in class_df.iterrows()
    }

    return render_template(
        "classes_view.html",
        headers=headers,
        rows=rows,
        ability_data=ability_data,
        affinity_info=affinity_info,
        class_info=class_info,
    )

# ------------------------------------------------------------------------------
# Auth: register / login / logout / username
# ------------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"], endpoint="register")
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not email or not username or not password:
            return render_template("register.html", error="Email, username and password are required.")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE email = ? OR username = ?", (email, username))
        exists = cur.fetchone()
        if exists:
            conn.close()
            return render_template("register.html", error="Email or username already exists.")

        pw_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (email, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (email, username, pw_hash, datetime.utcnow().isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()

        session["user_id"] = user_id
        session["email"] = email
        session["username"] = username
        return redirect(url_for("home"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        u = cur.fetchone()
        conn.close()

        if u and u["password_hash"] and check_password_hash(u["password_hash"], password):
            session["user_id"] = u["id"]
            session["email"] = u["email"]
            session["username"] = u["username"]
            return redirect(url_for("home"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/pick-username", methods=["GET", "POST"])
@login_required
def pick_username():
    if session.get("username"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        if not re.match(r"^[A-Za-z0-9_]{3,20}$", username):
            return render_template(
                "pick_username.html",
                error="Username must be 3-20 characters (letters, numbers, underscore).",
            )

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        exists = cur.fetchone()
        if exists:
            conn.close()
            return render_template("pick_username.html", error="That username is taken, try another.")

        cur.execute("UPDATE users SET username = ? WHERE id = ?", (username, session["user_id"]))
        conn.commit()
        conn.close()

        session["username"] = username
        return redirect(url_for("home"))

    return render_template("pick_username.html")

# ------------------------------------------------------------------------------
# Google OAuth routes
# ------------------------------------------------------------------------------
@app.route("/login/google", endpoint="login_google")
def google_login_start():
    redirect_uri = url_for("auth_google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/google/callback", endpoint="auth_google_callback")
def google_login_callback():
    token = google.authorize_access_token()
    resp = google.get("https://openidconnect.googleapis.com/v1/userinfo")
    info = resp.json()

    email = (info.get("email") or "").lower()
    sub = info.get("sub")

    if not email or not sub:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    u = cur.fetchone()

    if u:
        if not u["google_id"]:
            cur.execute("UPDATE users SET google_id = ? WHERE id = ?", (sub, u["id"]))
            conn.commit()
        user_id = u["id"]
        username = u["username"]
    else:
        cur.execute(
            "INSERT INTO users (email, google_id, created_at) VALUES (?, ?, ?)",
            (email, sub, datetime.utcnow().isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid
        username = None

    conn.close()

    session["user_id"] = user_id
    session["email"] = email
    session["username"] = username

    if not username:
        return redirect(url_for("pick_username"))
    return redirect(url_for("home"))

def _healthz():
    return "ok", 200

# Register once even if code gets merged/duplicated in the future
if "healthz_ok" not in app.view_functions and "healthz" not in app.view_functions:
    app.add_url_rule("/healthz", endpoint="healthz_ok", view_func=_healthz)

# ------------------------------------------------------------------------------
# Debug / misc
# ------------------------------------------------------------------------------
@app.route("/whoami")
def whoami():
    return f"user_id={session.get('user_id')}, username={session.get('username')}, email={session.get('email')}, is_admin={is_admin()}"

@app.route("/__routes__")
def list_routes():
    lines = [f"{rule.endpoint}: {rule}" for rule in app.url_map.iter_rules()]
    return "<br>".join(sorted(lines))

@app.route("/ping")
def ping():
    return "pong"

# ------------------------------------------------------------------------------
# Global chat (Socket.IO)
# ------------------------------------------------------------------------------
CHAT_HISTORY = deque(maxlen=100)  # last 100 messages
CONNECTED = {}  # sid -> username

@socketio.on("connect")
def on_connect():
    user = _display_name_from_session()
    CONNECTED[request.sid] = user
    join_room("global")
    emit("chat_history", list(CHAT_HISTORY))
    emit("chat_message", {"user": "System", "text": f"{user} joined the chat."}, to="global")

@socketio.on("disconnect")
def on_disconnect():
    user = CONNECTED.pop(request.sid, None) or "Someone"
    emit("chat_message", {"user": "System", "text": f"{user} left the chat."}, to="global")

@socketio.on("chat_message")
def on_chat_message(data):
    text = (data.get("text") or "").strip()
    if not text:
        return
    user = CONNECTED.get(request.sid) or _display_name_from_session()
    mid = data.get("id") or f"{int(datetime.utcnow().timestamp()*1000)}-{random.randint(1000,9999)}"
    msg = {"id": mid, "user": user, "text": text, "ts": datetime.utcnow().isoformat()}
    CHAT_HISTORY.append(msg)
    emit("chat_message", msg, to="global")

# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("ATP DEBUG: starting server")
    print("--- ROUTES ---")
    for r in app.url_map.iter_rules():
        print(f"{r.endpoint}: {r}")
    print("--------------")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
