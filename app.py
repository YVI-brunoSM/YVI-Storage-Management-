from inventory import create_app

app = create_app()
socketio = app.extensions['realtime'].socket
