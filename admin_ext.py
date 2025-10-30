# admin_ext.py — env-driven admin roles (with DB toggles)
# Usage (in app.py):
#   import admin_ext
#   admin_ext.init_admin(app, get_db)   # call once after app is created

from flask import session, redirect, url_for, render_template, request
from functools import wraps
import os


def init_admin(app, get_db):
    """
    Admin model:
      - Anyone listed in ADMIN_EMAILS (comma-separated) is ALWAYS admin.
      - users.is_admin (DB) grants additional admins via /admin toggle.
      - session['is_admin'] is hydrated on every request.
      - `is_admin` is injected into templates.
      - /admin and /admin/toggle/<id> routes included.

    ADMIN_EMAILS examples:
      "you@gmail.com"
      "you@gmail.com, other@proton.me, admin@myco.co"
    """

    # ---------- helpers ----------
    def _env_admins():
        # Read fresh each time (cheap) to avoid stale values after redeploys
        return {
            e.strip().lower()
            for e in os.getenv("ADMIN_EMAILS", "").split(",")
            if e.strip()
        }

    def _ensure_is_admin_column():
        """Create users.is_admin if missing (safe if it already exists)."""
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

    def _email_from_session() -> str:
        # Common direct keys
        for key in ("email", "user_email"):
            v = (session.get(key) or "").strip()
            if v:
                return v.lower()
        # Sometimes apps stash a user dict
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
        # Prefer session; fall back to DB by user_id
        return _email_from_session() or _email_from_db()

    # ---------- hydrate session flag each request ----------
    @app.before_request
    def _hydrate_admin_flag():
        try:
            email = _current_email()
            env_admins = _env_admins()

            if email and email in env_admins:
                session["is_admin"] = True
                return

            # Not env admin: fallback to DB flag if user_id is present
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
            # Never block the request
            pass

    # ---------- expose is_admin to templates ----------
    @app.context_processor
    def _inject_is_admin():
        return {"is_admin": bool(session.get("is_admin"))}

    # ---------- decorator ----------
    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))  # change if your login endpoint differs
            if not session.get("is_admin"):
                return "Admins only.", 403
            return f(*args, **kwargs)
        return wrapper

    app.admin_required = admin_required

    # ---------- views ----------
    @app.route("/admin")
    @admin_required
    def admin_panel():
        env_admins = _env_admins()

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
            is_env = email in env_admins
            is_db = bool(r[4])
            users.append({
                "id": r[0],
                "email": r[1],
                "username": r[2],
                "created_at": r[3],
                "is_admin_env": is_env,
                "is_admin_db": is_db,
                "is_admin_effective": is_env or is_db,
            })

        return render_template(
            "admin_panel.html",
            users=users,
            env_admins=sorted(env_admins),
            error=None,
            message=request.args.get("msg", "")
        )

    @app.route("/admin/toggle/<int:user_id>", methods=["POST"])
    @admin_required
    def admin_toggle(user_id):
        """
        Toggle DB-based admin. You cannot demote:
          - an env admin (listed in ADMIN_EMAILS), or
          - the last remaining effective admin (env + db).
        """
        make = 1 if (request.form.get("make") == "1") else 0

        conn = get_db()
        cur = conn.cursor()
        try:
            # Target info
            cur.execute("SELECT email, COALESCE(is_admin,0) FROM users WHERE id=?", (user_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return redirect(url_for("admin_panel", msg="User not found."))

            target_email = (row[0] or "").strip().lower()
            target_db_admin = bool(row[1])
            env_admins = _env_admins()

            # Can't demote env admins via UI
            if make == 0 and target_email in env_admins:
                conn.close()
                return redirect(url_for("admin_panel", msg="Env admins cannot be removed here."))

            # Prevent removing the last effective admin
            if make == 0:
                # count env admins
                env_count = len(env_admins)
                # count DB admins (excluding target if they currently are one)
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

        return redirect(url_for("admin_panel", msg="Updated."))

    return app
