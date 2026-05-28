import argparse
from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on')
    args = parser.parse_args()
    socketio.run(app, host='0.0.0.0', port=args.port, debug=True, allow_unsafe_werkzeug=True)
