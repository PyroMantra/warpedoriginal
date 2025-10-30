# admin_ext.py — env-driven admin roles (with optional DB toggles)
# Usage (in app.py):
#   import admin_ext
#   admin_ext.init_admin(app, get_db)   # call once after app is created

from flask import session, redirect, url_for, render_template, request
from functools import wraps
import os

def init_admin(app, get_db=None):
    """
    Admin system driven by ADMIN_EMAILS env, with optional DB support.

    - Reads ADMIN_EMAILS (comma-separated) and treats these emails as admin ALWAYS.
    - Optionally keeps/uses users.is_admin column to grant extra admins via UI toggle.
    - Keeps session['is_admin'] automatically in sync on each request.
    - Exposes app.is_admin() and app.admin_required decorator.
    - Injects `is_admin` into all templates.
    - Provides /admin and /admin/toggle/<id> views (DB optional; toggle only if DB provided).

    ENV:
      ADMIN_EMAILS = "a@x.com,b@y.com"
    """
    # ------------------- Env admins -------------------
    ENV_ADMINS = {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }

    # ------------------- Helpers ----------------------
    def _current_email():
        """
        Try a few common places to find the signed-in user's email.
        Your login flow should set one of these (session is most typical).
        """
        # Prefer explicit session keys that are already used in your app
        for key in ("email", "user_email"):
            v = (session.get(key) or "").strip()
            if v:
                return v.lower()

        # (Optional) If you store a user dict in session as 'user'
        u = session.get("user")
        if isinstance(u, dict):
            v = (u.get("email") or "").strip()
            if v:
                return v.lower()

        return ""

    def _has_db():
        return callable(get_db)

    def _ensure_is_admin_column():
        """Create users.is_admin if a users table exists and the column is missing."""
        if not _has_db():
            return
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(users)")
            cols = [r[1] for r in cur.fetchall()]  # [(cid, name, ...)]
            if "is_admin" not in cols:
                cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
                conn.commit()
        finally:
            conn.close()

    _ensure_is_admin_column()

    # ------------------- Session hydration -------------------
    @app.before_request
    def _hydrate_admin_flag():
        """
        Refresh session['is_admin'] on every request:
        - True if email is in ADMIN_EMAILS
        - Otherwise, if DB exists & user_id in session, read users.is_admin
        """
        try:
            email = _current_email()
            env_admin = email in ENV_ADMINS

            if env_admin:
                session["is_admin"] = True
                return

            # Not an env admin; check DB flag if available
            if _has_db() and session.get("user_id"):
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COALESCE(is_admin,0) FROM users WHERE id=?", (session["user_id"],))
                row = cur.fetchone()
                conn.close()
                session["is_admin"] = bool(row[0]) if row else False
            else:
                session["is_admin"] = False
        except Exception:
            # Never block the request on admin hydration
            pass

    # ------------------- Template context -------------------
    @app.context_processor
    def _inject_is_admin():
        return {"is_admin": bool(session.get("is_admin"))}

    # ------------------- Public API -------------------
    def is_admin():
        """True if current user is admin (env or DB)."""
        return bool(session.get("is_admin"))

    app.is_admin = is_admin

    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                # Adjust "login" endpoint if your app uses another name
                return redirect(url_for("login"))
            if not app.is_admin():
                return "Admins only.", 403
            return f(*args, **kwargs)
        return wrapper

    app.admin_required = admin_required

    # ------------------- Views -------------------
    @app.route("/admin")
    @admin_required
    def admin_panel():
        """
        Show users (if DB is available) and mark who is admin.
        Env admins are highlighted and cannot be changed from UI.
        """
        users = []
        if _has_db():
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, email, username, created_at, COALESCE(is_admin,0) as is_admin "
                "FROM users ORDER BY id"
            )
            for r in cur.fetchall():
                email = (r[1] or "").strip().lower()
                env_admin = email in ENV_ADMINS
                # Effective admin if env OR db flag
                effective = env_admin or bool(r[4])
                users.append({
                    "id": r[0],
                    "email": r[1],
                    "username": r[2],
                    "created_at": r[3],
                    "is_admin_db": bool(r[4]),
                    "is_admin_env": env_admin,
                    "is_admin_effective": effective,
                })
            conn.close()
        else:
            # No DB: just show env admins as a simple list
            users = []

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
        - Env admins cannot be removed here (they're always admins).
        - Prevent removing the last effective admin (env + db).
        """
        if not _has_db():
            return "No database configured for admin toggles.", 501

        make = 1 if (request.form.get("make") == "1") else 0
        me = session.get("user_id")

        conn = get_db()
        cur = conn.cursor()
        try:
            # Get the target user's email and current db flag
            cur.execute("SELECT email, COALESCE(is_admin,0) FROM users WHERE id=?", (user_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return redirect(url_for("admin_panel", msg="User not found."))

            target_email = (row[0] or "").strip().lower()
            target_is_env = target_email in ENV_ADMINS

            # You can't demote an env admin from the UI
            if make == 0 and target_is_env:
                conn.close()
                return redirect(url_for("admin_panel", msg="Env admins cannot be removed here."))

            # If demoting, ensure at least one effective admin remains
            if make == 0:
                # count effective admins: env admins + db admins (excluding this target if it's the last)
                env_count = len(ENV_ADMINS)
                cur.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
                db_count = cur.fetchone()[0] or 0

                # If target is currently a DB admin, we're about to decrement db_count by one
                # but if they're an env admin, they still remain admin regardless (already handled above)
                if row[1]:
                    db_count -= 1

                if (env_count + db_count) <= 0:
                    conn.close()
                    return redirect(url_for("admin_panel", msg="Cannot remove the last remaining admin."))

            # Do the update
            cur.execute("UPDATE users SET is_admin=? WHERE id=?", (make, user_id))
            conn.commit()
        finally:
            conn.close()

        # If you toggled yourself, refresh your session flag next request
        if user_id == me:
            # let before_request re-hydrate; we keep this minimal
            pass

        return redirect(url_for("admin_panel", msg="Updated."))

    return app  # chaining
