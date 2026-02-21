import multiprocessing
import os
import signal

from CTFd.plugins.dojo_plugin.worker import setup_worker_logging

logger = setup_worker_logging(__name__)

shutdown_event = multiprocessing.Event()


def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_event.set()


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def worker_process(app, shutdown_event):
    with app.app_context():
        from CTFd.models import db
        db.engine.dispose()
        from CTFd.plugins.dojo_plugin.worker.container_start import consume_container_starts
        try:
            consume_container_starts(shutdown_event=shutdown_event)
        except Exception as e:
            logger.error(f"Worker process crashed: {e}", exc_info=True)


from flask import current_app
app = current_app._get_current_object()

from CTFd.plugins.dojo_plugin.config import CONTAINER_WORKERS
num_workers = CONTAINER_WORKERS
logger.info(f"Starting container worker with {num_workers} processes...")

processes = []
for i in range(num_workers):
    p = multiprocessing.Process(target=worker_process, args=(app, shutdown_event), daemon=True)
    p.start()
    processes.append(p)
    logger.info(f"Started worker process {i+1}/{num_workers} (pid={p.pid})")

try:
    while not shutdown_event.is_set():
        for i, p in enumerate(processes):
            if not p.is_alive():
                logger.warning(f"Worker process {i+1} (pid={p.pid}) died, restarting...")
                new_p = multiprocessing.Process(target=worker_process, args=(app, shutdown_event), daemon=True)
                new_p.start()
                processes[i] = new_p
                logger.info(f"Restarted worker process {i+1} (pid={new_p.pid})")
        shutdown_event.wait(timeout=5)
except KeyboardInterrupt:
    logger.info("Interrupted, shutting down...")
    shutdown_event.set()

for p in processes:
    p.join(timeout=30)
    if p.is_alive():
        logger.warning(f"Force killing worker process pid={p.pid}")
        p.kill()

logger.info("Container worker stopped")
