import os
import argparse
from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on')
    args = parser.parse_args()
    debug_mode = os.getenv("FLASK_DEBUG", "1") == "1"
    socketio.run(app, host="0.0.0.0", port=args.port, debug=debug_mode, allow_unsafe_werkzeug=debug_mode)
