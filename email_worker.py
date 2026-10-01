"""Run as a separate Railway service: python email_worker.py."""
import signal
from threading import Event
from inventory import create_app
from inventory.mail_worker import process_once


def main():
    app = create_app()
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        with app.app_context():
            while not stop.is_set():
                try:
                    worked = process_once()
                except Exception:
                    app.logger.error('email_worker_cycle_failed', exc_info=True)
                    worked = False
                stop.wait(2 if worked else 10)
    finally:
        app.extensions['db'].close()


if __name__ == '__main__':
    main()
