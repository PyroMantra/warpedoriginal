# admin_ext.py — baseline (hardcoded/env) admins + DB toggles
# Usage in app.py:
#   import admin_ext
#   admin_ext.init_admin(app, get_db)

from flask import session, redirect, url_for, render_template, request
from functools import wraps
import os

# ---------------------------------------------------------------------------
# EDIT THESE (put your real emails here; you can list multiple):
HARDCODED_ADMINS = {
    "danyellye99@yahoo.com",
    # "second@example.com",
}
# Force certain user IDs to be admin as well (optional), e.g. {1, 7}
FORCE_ADMIN_USER_IDS = set()
# ---------------------------------------------------------------------------


def init_admin(app, get_db):
    """Wire admin features (baseline admins + DB toggles) into the app."""

    # ---------- Baseline admins (hardcoded + env) ----------
    ENV_ADMINS = {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    BASELINE_EMAIL_ADMINS = {e.strip().lower() for e in HARDCODED_ADMINS if e.strip()} | ENV_ADMINS
    BASELINE_ID_ADMINS = set(FORCE_ADMIN_USER_IDS)

    # ---------- Ensure users.is_admin exists (safe if users is missing) ----------
    def _ensure_is_admin_column():
        conn = get_db()
        cur = conn.cursor()
        try:
            # Only if users table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cur.fetchone():
                return
            cur.execute("PRAGMA table_info(users)")
            cols = [r[1] for r in cur.fetchall()]
            if "is_admin" not in cols:
                cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
                conn.commit()
        except Exception:
            # Never block startup
            pass
        finally:
            conn.close()

    _ensure_is_admin_column()

    # ---------- Current email helpers ----------
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
        uid = session.get("user_id")
        if not uid:
            return ""
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT email FROM users WHERE id=?", (uid,))
            row = cur.fetchone()
            if not row:
                return ""
            v = (row[0] or "").strip()
            return v.lower() if v else ""
        finally:
            conn.close()

    def _current_email() -> str:
        return _email_from_session() or _email_from_db()

    # ---------- Hydrate session['is_admin'] each request ----------
    @app.before_request
    def _hydrate_admin_flag():
        try:
            uid = session.get("user_id")
            email = _current_email()

            # Baseline (hardcoded/env) wins
            if (email and email in BASELINE_EMAIL_ADMINS) or (uid in BASELINE_ID_ADMINS):
                session["is_admin"] = True
                return

            # Otherwise check DB flag (extra admins)
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
            # best effort; never block
            pass

    # ---------- Expose is_admin to templates ----------
    @app.context_processor
    def _inject_is_admin():
        return {"is_admin": bool(session.get("is_admin"))}

    # ---------- Decorator ----------
    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if not session.get("is_admin"):
                return "Admins only.", 403
            return f(*args, **kwargs)
        return wrapper

    app.admin_required = admin_required  # make reusable elsewhere

    # ---------- Views ----------
    @app.route("/admin")
    @admin_required
    def admin_panel():
        """Manage users. Supplies user.is_admin for your existing template."""
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
            email_lc = email_raw.strip().lower()

            baseline = (email_lc in BASELINE_EMAIL_ADMINS) or (uid in BASELINE_ID_ADMINS)
            db_admin = bool(r[4])
            effective = baseline or db_admin

            users.append({
                "id": uid,
                "email": email_raw,
                "username": r[2],
                "created_at": r[3],

                # Back-compat with your template:
                "is_admin": effective,

                # Extra (keep if you want to show badges):
                "is_admin_db": db_admin,
                "is_admin_baseline": baseline,
                "is_admin_effective": effective,
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
          - a baseline admin (hardcoded/env),
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
            target_baseline = (target_email in BASELINE_EMAIL_ADMINS) or (user_id in BASELINE_ID_ADMINS)

            # Can't demote baseline admin via UI
            if make == 0 and target_baseline:
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
