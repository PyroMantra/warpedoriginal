import os
from app import app, socketio

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # Use Flask-SocketIO server (threading mode in app.py)
    socketio.run(app, host="0.0.0.0", port=port)
