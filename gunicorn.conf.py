import os

bind = '0.0.0.0:' + os.getenv('PORT', '8080')
# Socket.IO polling requires a single process; threads serve concurrent users.
workers = 1
worker_class = 'gthread'
threads = 64
timeout = 60
graceful_timeout = 30
keepalive = 5
preload_app = False
accesslog = None  # Application logs omit cookies, query strings and payloads.
errorlog = '-'
capture_output = True
