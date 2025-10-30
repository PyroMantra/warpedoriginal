# admin_ext.py — hardcoded admins (with optional env + DB toggles)
# Usage (in app.py):
#   import admin_ext
#   admin_ext.init_admin(app, get_db)

from flask import session, redirect, url_for, render_template, request
from functools import wraps
import os

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# EDIT THESE:
HARDCODED_ADMINS = {"danyellye99@yahoo.com"}

# If you also want to force by user_id (e.g., id=1 is always admin), add here:
FORCE_ADMIN_USER_IDS = set()  # e.g., {1}
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<


def init_admin(app, get_db):
    """
    Admin model:
      - Anyone in HARDCODED_ADMINS (or FORCE_ADMIN_USER_IDS) is ALWAYS admin.
      - ADMIN_EMAILS env is also supported (merged with hardcoded list).
      - users.is_admin (DB) grants additional admins via /admin toggle.
      - session['is_admin'] hydrated on every request.
      - is_admin injected into templates.
      - /admin and /admin/toggle/<id> included.
    """

    # -------- baseline admins: hardcoded + env (merged) --------
    ENV_ADMINS = {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    BASELINE_EMAIL_ADMINS = {e.strip().lower() for e in HARDCODED_ADMINS if e.strip()} | ENV_ADMINS
    BASELINE_ID_ADMINS = set(FORCE_ADMIN_USER_IDS)

    # ---------------- DB column ensure ----------------
    def _ensure_is_admin_column():
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(users)")
            cols = [r[1] for r in cur.fetchall()]
            if "is_admin" not in cols:
                cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
                conn.commit()
        finally:
            conn.close()

    _ensure_is_admin_column()

    # ---------------- email lookup helpers ----------------
    def _email_from_session() -> str:
        for key in ("email", "user_email"):
            v = (session.get(key) or "").strip()
            if v:
                return v.lower()
        u = session.get("user")
        if isinstance(u, dict):
            v = (u.get("email") or "").strip()
            if v:
                return v.lower()
        return ""

    def _email_from_db() -> str:
        if not session.get("user_id"):
            return ""
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT email FROM users WHERE id=?", (session["user_id"],))
            row = cur.fetchone()
            if not row:
                return ""
            v = (row[0] or "").strip()
            return v.lower() if v else ""
        finally:
            conn.close()

    def _current_email() -> str:
        return _email_from_session() or _email_from_db()

    # ---------------- hydrate session flag ----------------
    @app.before_request
    def _hydrate_admin_flag():
        try:
            uid = session.get("user_id")
            email = _current_email()

            # Hardcoded / env baseline wins
            if (email and email in BASELINE_EMAIL_ADMINS) or (uid in BASELINE_ID_ADMINS):
                session["is_admin"] = True
                return

            # Otherwise fall back to DB flag (extra admins granted via UI)
            if uid:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COALESCE(is_admin,0) FROM users WHERE id=?", (uid,))
                row = cur.fetchone()
                conn.close()
                session["is_admin"] = bool(row[0]) if row else False
            else:
                session["is_admin"] = False
        except Exception:
            # best effort, never block
            pass

    # ---------------- inject into templates ----------------
    @app.context_processor
    def _inject_is_admin():
        return {"is_admin": bool(session.get("is_admin"))}

    # ---------------- decorator ----------------
    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))  # adjust if needed
            if not session.get("is_admin"):
                return "Admins only.", 403
            return f(*args, **kwargs)
        return wrapper

    app.admin_required = admin_required

    # ---------------- views ----------------
    @app.route("/admin")
    @admin_required
    def admin_panel():
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, username, created_at, COALESCE(is_admin,0) as is_admin "
            "FROM users ORDER BY id"
        )
        rows = cur.fetchall()
        conn.close()

        users = []
        for r in rows:
            uid = r[0]
            email_raw = r[1] or ""
            email = email_raw.strip().lower()
            env_or_hard = (email in BASELINE_EMAIL_ADMINS) or (uid in BASELINE_ID_ADMINS)
            db_admin = bool(r[4])
            users.append({
                "id": uid,
                "email": email_raw,
                "username": r[2],
                "created_at": r[3],
                "is_admin_baseline": env_or_hard,   # hardcoded OR env
                "is_admin_db": db_admin,            # db toggle
                "is_admin_effective": env_or_hard or db_admin,
            })

        return render_template(
            "admin_panel.html",
            users=users,
            baseline_emails=sorted(BASELINE_EMAIL_ADMINS),
            baseline_ids=sorted(list(BASELINE_ID_ADMINS)),
            message=request.args.get("msg", ""),
            error=None,
        )

    @app.route("/admin/toggle/<int:user_id>", methods=["POST"])
    @admin_required
    def admin_toggle(user_id):
        """
        Toggle DB admin. You cannot demote:
          - a baseline admin (hardcoded or env),
          - the last remaining effective admin (baseline + db).
        """
        make = 1 if (request.form.get("make") == "1") else 0

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT email, COALESCE(is_admin,0) FROM users WHERE id=?", (user_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return redirect(url_for("admin_panel", msg="User not found."))

            target_email = (row[0] or "").strip().lower()
            target_db_admin = bool(row[1])
            target_is_baseline = (target_email in BASELINE_EMAIL_ADMINS) or (user_id in BASELINE_ID_ADMINS)

            # Can't demote baseline admin via UI
            if make == 0 and target_is_baseline:
                conn.close()
                return redirect(url_for("admin_panel", msg="Baseline admins cannot be removed here."))

            # Prevent removing the last effective admin
            if make == 0:
                baseline_count = len(BASELINE_EMAIL_ADMINS) + len(BASELINE_ID_ADMINS)
                cur.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
                db_count = (cur.fetchone()[0] or 0)
                if target_db_admin:
                    db_count -= 1
                if (baseline_count + db_count) <= 0:
                    conn.close()
                    return redirect(url_for("admin_panel", msg="Cannot remove the last remaining admin."))

            # Toggle DB flag
            cur.execute("UPDATE users SET is_admin=? WHERE id=?", (make, user_id))
            conn.commit()
        finally:
            conn.close()

        return redirect(url_for("admin_panel", msg="Updated."))

    return app
