import logging
import signal

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

shutdown_requested = False

def signal_handler(signum, frame):
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_requested = True

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

logger.info("Starting image pull worker...")

from ..utils.image_pulls import consume_image_pull_events
from ..worker.handlers.image_pulls import handle_image_pull_event

try:
    consume_image_pull_events(
        handler=handle_image_pull_event,
        batch_size=5,
        block_ms=5000
    )
except KeyboardInterrupt:
    logger.info("Image pull worker interrupted by user")
except Exception as e:
    logger.error(f"Image pull worker crashed: {e}", exc_info=True)
    raise

logger.info("Image pull worker stopped")
