
import os
import re
import html
import random
import sqlite3
from pathlib import Path
from datetime import datetime
from functools import wraps
from collections import defaultdict, deque

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, render_template, redirect, url_for, session, request
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_socketio import SocketIO, emit, join_room, leave_room
from authlib.integrations.flask_client import OAuth

import pandas as pd

# Optional: load .env again (env_boot already does this, but harmless)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ------------------------------------------------------------------------------
# Flask / App setup
# ------------------------------------------------------------------------------
app = Flask(__name__)
# --- Proxy & cookie settings for OAuth behind Railway ---
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
    print('       $env:GOOGLE_CLIENT_ID=\"your_client_id\"')
    print('       $env:GOOGLE_CLIENT_SECRET=\"your_client_secret\"')
    print('       $env:OAUTHLIB_INSECURE_TRANSPORT=\"1\"   # local only')
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
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# Healthcheck endpoint for Railway
@app.route('/healthz')
def healthz():
    return 'ok', 200


# ------------------------------------------------------------------------------
# Auth DB
# ------------------------------------------------------------------------------
DB_PATH = os.path.join("data", "auth.db")
os.makedirs("data", exist_ok=True)

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

# ------------------------------------------------------------------------------
# Data / Excel loading
# ------------------------------------------------------------------------------
EXCEL_PATH = os.path.join("data", "Layer List (7).xlsx")
sheets = pd.read_excel(EXCEL_PATH, sheet_name=None)

# Remove non-generic sheets from general viewer:
sheets = {k: v for k, v in sheets.items() if k not in ["Classes", "Races", "Abilities"]}

SHEET_NAMES = list(sheets.keys())
generator_sheets = [name for name in SHEET_NAMES if "Generator" in name]

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

@app.route("/")
@login_required
def home():
    data_buttons = [
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
        {"label": "Items", "endpoint": "view_sheet", "arg": "Items"},
        {"label": "Gear", "endpoint": "view_sheet", "arg": "Gear"},
    ]
    return render_template("dashboard.html", data_buttons=data_buttons, generators=generator_sheets)

@app.route("/view/<sheet>")
@login_required
def view_sheet(sheet):
    if sheet not in sheets:
        return f"Sheet '{sheet}' not found.", 404
    df = sheets[sheet].fillna("").astype(str)
    return render_template("view_sheet.html", sheet=sheet, headers=df.columns.tolist(), rows=df.values.tolist())

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

@app.route("/races-table")
@login_required
def races_table():
    path = "static/notion/Races Main 207ec6426bd5807b925cddd6c35d0f14_all.csv"
    df = pd.read_csv(path).fillna("")
    df.columns = df.columns.str.strip()

    if "RACE" in df.columns and "SUBTYPE" in df.columns:
        df["RACE"] = df["RACE"].apply(lambda x: x.split(" (")[0] if isinstance(x, str) else x)
        cols = df.columns.tolist()
        if cols.index("RACE") > cols.index("SUBTYPE"):
            race_idx, sub_idx = cols.index("RACE"), cols.index("SUBTYPE")
            cols[race_idx], cols[sub_idx] = cols[sub_idx], cols[race_idx]
            df = df[cols]

    stamina_col = next((c for c in df.columns if c.lower() == "stamina"), None)
    if stamina_col:
        df[stamina_col] = df[stamina_col].apply(lambda x: round(float(x)) if str(x).replace(".", "", 1).isdigit() else x)

    for col in [c for c in df.columns if "resistance" in c.lower()]:
        df[col] = df[col].apply(lambda x: f"{float(x)*100:.0f}%" if str(x).replace(".", "", 1).isdigit() else x)

    return render_template("races_table.html", headers=df.columns.tolist(), rows=df.values.tolist())

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
        aff = row.get("Affinity", "").strip()
        typ = row.get("Type", "").strip()
        if not aff or not typ:
            continue
        ability_data[aff][typ].append({
            "Rank I": row.get("Rank I", "N/A") or "N/A",
            "Rank II": row.get("Rank II", "N/A") if typ != "Innate" else "N/A",
            "Rank III": row.get("Rank III", "N/A") if typ != "Innate" else "N/A",
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

# ------------------------------------------------------------------------------
# Debug / misc
# ------------------------------------------------------------------------------
@app.route("/whoami")
def whoami():
    return f"logged in as: {session.get('username') or session.get('email') or 'anonymous'}"

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




@app.route("/healthz")
def healthz():
    return "ok", 200

