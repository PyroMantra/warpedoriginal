# admin_ext.py — drop-in admin roles for your Flask app
# Usage (in app.py):
#   import admin_ext
#   admin_ext.init_admin(app, get_db)   # call once after app is created

from flask import session, redirect, url_for, render_template, request
from functools import wraps
import os

def init_admin(app, get_db):
    """Wire admin features into an existing app with minimal edits.
       - Ensures users.is_admin column exists
       - Optional bootstrap from ADMIN_EMAILS env
       - Adds 'is_admin' to templates via a context_processor
       - Hydrates session['is_admin'] automatically
       - Registers /admin and /admin/toggle/<id> routes
       - Exposes app.admin_required decorator
    """

    # --- Ensure DB column exists ---
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

    # --- Optional: seed admins from env ---
    def _bootstrap_admins_from_env():
        emails = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
        if not emails:
            return
        conn = get_db()
        cur = conn.cursor()
        try:
            for e in emails:
                cur.execute("UPDATE users SET is_admin=1 WHERE lower(email)=?", (e,))
            conn.commit()
        finally:
            conn.close()

    _bootstrap_admins_from_env()

    # --- Keep session['is_admin'] in sync (always refresh) ---
    @app.before_request
    def _hydrate_admin_flag():
        try:
            if session.get("user_id"):
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COALESCE(is_admin,0) FROM users WHERE id=?", (session["user_id"],))
                row = cur.fetchone()
                conn.close()
                session["is_admin"] = bool(row[0]) if row is not None else False
        except Exception:
            # best effort; never block the request
            pass

    # --- Expose 'is_admin' to all templates ---
    @app.context_processor
    def _inject_is_admin():
        return {"is_admin": bool(session.get("is_admin"))}

    # --- Decorator ---
    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if not session.get("is_admin"):
                return "Admins only.", 403
            return f(*args, **kwargs)
        return wrapper

    # make it reachable from app if you want to reuse it
    app.admin_required = admin_required

    # --- Views ---
    @app.route("/admin")
    @admin_required
    def admin_panel():
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, username, created_at, COALESCE(is_admin,0) as is_admin "
            "FROM users ORDER BY id"
        )
        users = [
            {"id": r[0], "email": r[1], "username": r[2], "created_at": r[3], "is_admin": r[4]}
            for r in cur.fetchall()
        ]
        conn.close()
        return render_template(
            "admin_panel.html", users=users, error=None, message=request.args.get("msg", "")
        )

    @app.route("/admin/toggle/<int:user_id>", methods=["POST"])
    @admin_required
    def admin_toggle(user_id):
        make = 1 if (request.form.get("make") == "1") else 0
        me = session.get("user_id")

        conn = get_db()
        cur = conn.cursor()
        try:
            if make == 0:
                # how many admins exist now?
                cur.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
                cnt = cur.fetchone()[0] or 0

                # don't allow removing the last remaining admin (even if it's not you)
                if cnt <= 1:
                    return redirect(url_for("admin_panel", msg="Cannot remove the last remaining admin."))

            # do the update
            cur.execute("UPDATE users SET is_admin=? WHERE id=?", (make, user_id))
            conn.commit()
        finally:
            conn.close()

        # refresh your own session flag if you toggled yourself
        if user_id == me:
            session["is_admin"] = bool(make)

        return redirect(url_for("admin_panel", msg="Updated."))

    return app  # for chaining
