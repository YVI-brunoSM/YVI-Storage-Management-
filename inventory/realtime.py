import logging
from threading import Lock
from flask import request, session
from flask_socketio import SocketIO, join_room, disconnect
from .db import transaction
from .security import identity


class Realtime:
    def __init__(self, app):
        self.socket = SocketIO(app, async_mode='threading', cors_allowed_origins=None,
                               message_queue=app.config.get('REDIS_URL') or None,
                               max_http_buffer_size=16384, logger=False, engineio_logger=False)
        self.clients, self.lock = {}, Lock()

        @self.socket.on('connect')
        def connect(auth=None):
            if not isinstance(auth, dict) or not auth.get('csrf') or auth['csrf'] != session.get('csrf'):
                return False
            try:
                with transaction() as conn:
                    user = identity(conn)
                with self.lock:
                    self.clients[request.sid] = user['id']
                join_room('authenticated')
                join_room(f'user:{user["id"]}')
            except Exception:
                return False

        @self.socket.on('heartbeat')
        def heartbeat():
            try:
                with transaction() as conn:
                    identity(conn)
                return {'ok': True}
            except Exception:
                disconnect()
                return {'ok': False}

        @self.socket.on('disconnect')
        def disconnected(reason=None):
            with self.lock:
                self.clients.pop(request.sid, None)

    def changed(self):
        try:
            self.socket.emit('update_data', {'event_type': 'all'}, to='authenticated')
        except Exception:
            logging.getLogger('inventory').warning('realtime_delivery_failed')

    def revoke(self, uid):
        try:
            self.socket.emit('session_revoked', {}, to=f'user:{uid}')
            with self.lock:
                sids = [sid for sid, user_id in self.clients.items() if user_id == uid]
            for sid in sids:
                self.socket.server.disconnect(sid)
        except Exception:
            logging.getLogger('inventory').warning('realtime_revocation_delivery_failed')
