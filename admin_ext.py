# admin_ext.py — env-driven admin roles (with optional DB toggles)
# Usage (in app.py):
#   import admin_ext
#   admin_ext.init_admin(app, get_db)   # call once after app is created

from flask import session, redirect, url_for, render_template, request
from functools import wraps
import os


def init_admin(app, get_db):
    """
    Admin system driven by ADMIN_EMAILS env, with DB-backed toggles.

    - ADMIN_EMAILS: comma-separated list of emails (case-insensitive)
      Example: "you@gmail.com, other@proton.me"
    - Env admins are ALWAYS admins (cannot be removed via UI).
    - DB column users.is_admin is used for extra admins.
    - session['is_admin'] is hydrated on each request.
    - `is_admin` available in templates.
    - Provides /admin and /admin/toggle/<id>.
    """

    # -------------------- ENV ADMINS --------------------
    ENV_ADMINS = {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }

    # -------------------- HELPERS -----------------------
    def _ensure_is_admin_column():
        """Create users.is_admin if missing."""
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

    def _current_email() -> str:
        """Find logged-in user's email from common session places."""
        # common keys your app likely uses
        for k in ("email", "user_email"):
            v = (session.get(k) or "").strip()
            if v:
                return v.lower()
        # optional nested dict
        u = session.get("user")
        if isinstance(u, dict):
            v = (u.get("email") or "").strip()
            if v:
                return v.lower()
        return ""

    def _is_env_admin(email: str) -> bool:
        return email in ENV_ADMINS if email else False

    _ensure_is_admin_column()

    # ----------------- HYDRATE SESSION FLAG -----------------
    @app.before_request
    def _hydrate_admin_flag():
        """Set session['is_admin'] = env_admin OR db_admin (every request)."""
        try:
            email = _current_email()
            if _is_env_admin(email):
                session["is_admin"] = True
                return
            if session.get("user_id"):
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COALESCE(is_admin,0) FROM users WHERE id=?", (session["user_id"],))
                row = cur.fetchone()
                conn.close()
                session["is_admin"] = bool(row[0]) if row else False
            else:
                session["is_admin"] = False
        except Exception:
            # best effort: never block requests
            pass

    # ----------------- TEMPLATE INJECTION -------------------
    @app.context_processor
    def _inject_is_admin():
        return {"is_admin": bool(session.get("is_admin"))}

    # ----------------- PUBLIC DECORATOR ---------------------
    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))  # adjust if your login endpoint differs
            if not session.get("is_admin"):
                return "Admins only.", 403
            return f(*args, **kwargs)
        return wrapper

    app.admin_required = admin_required  # expose for reuse

    # ----------------------- VIEWS --------------------------
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
            email = (r[1] or "").strip().lower()
            env_admin = _is_env_admin(email)
            users.append({
                "id": r[0],
                "email": r[1],
                "username": r[2],
                "created_at": r[3],
                "is_admin_db": bool(r[4]),
                "is_admin_env": env_admin,
                "is_admin_effective": env_admin or bool(r[4]),
            })

        return render_template(
            "admin_panel.html",
            users=users,
            env_admins=sorted(ENV_ADMINS),
            error=None,
            message=request.args.get("msg", "")
        )

    @app.route("/admin/toggle/<int:user_id>", methods=["POST"])
    @admin_required
    def admin_toggle(user_id):
        """
        Toggle DB-based admin for a user.
        - Cannot demote an env admin (they're always admins).
        - Cannot remove the last remaining effective admin (env + db).
        """
        make = 1 if (request.form.get("make") == "1") else 0
        me = session.get("user_id")

        conn = get_db()
        cur = conn.cursor()
        try:
            # Get target user's email & current db flag
            cur.execute("SELECT email, COALESCE(is_admin,0) FROM users WHERE id=?", (user_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return redirect(url_for("admin_panel", msg="User not found."))

            target_email = (row[0] or "").strip().lower()
            target_db_admin = bool(row[1])
            target_env_admin = _is_env_admin(target_email)

            # Can't demote env admins from the UI
            if make == 0 and target_env_admin:
                conn.close()
                return redirect(url_for("admin_panel", msg="Env admins cannot be removed here."))

            # If demoting, ensure at least one effective admin remains
            if make == 0:
                env_count = len(ENV_ADMINS)
                cur.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
                db_count = (cur.fetchone()[0] or 0)
                if target_db_admin:
                    db_count -= 1
                if (env_count + db_count) <= 0:
                    conn.close()
                    return redirect(url_for("admin_panel", msg="Cannot remove the last remaining admin."))

            # Apply DB toggle
            cur.execute("UPDATE users SET is_admin=? WHERE id=?", (make, user_id))
            conn.commit()
        finally:
            conn.close()

        # If you toggled yourself, the before_request will re-hydrate next time
        return redirect(url_for("admin_panel", msg="Updated."))

    return app  # for chaining
