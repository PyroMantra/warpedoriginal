import os
from app import app, socketio

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_kwargs = {
        "host": "0.0.0.0",
        "port": port,
    }
    # On hosts where eventlet is unavailable/incompatible, app.py falls back to
    # threading mode. Flask-SocketIO then uses Werkzeug, which must be
    # explicitly allowed or startup crashes before Railway can healthcheck.
    if getattr(socketio, "async_mode", None) == "threading":
        run_kwargs["allow_unsafe_werkzeug"] = True
    socketio.run(app, **run_kwargs)
