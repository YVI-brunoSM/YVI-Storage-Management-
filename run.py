import os
from app import app, socketio

if __name__ == '__main__':
    if app.config['APP_ENV'] != 'development':
        raise SystemExit('Em produção, use Gunicorn conforme README.md.')
    socketio.run(app, host='127.0.0.1', port=int(os.getenv('PORT', '5000')), debug=False, allow_unsafe_werkzeug=True)
