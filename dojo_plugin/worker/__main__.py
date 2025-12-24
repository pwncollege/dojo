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

logger.info("Starting stats background worker...")

from ..worker.handlers.dojo_stats import initialize_all_dojo_stats
logger.info("Performing cold start cache initialization...")

try:
    initialize_all_dojo_stats()
    logger.info("Cold start complete - all dojo stats initialized")
except Exception as e:
    logger.error(f"Error during cold start: {e}", exc_info=True)

logger.info("Starting event consumption loop...")

from ..utils.background_stats import consume_stat_events
from ..worker.handlers import handle_stat_event

try:
    consume_stat_events(
        handler=handle_stat_event,
        batch_size=10,
        block_ms=5000
    )
except KeyboardInterrupt:
    logger.info("Worker interrupted by user")
except Exception as e:
    logger.error(f"Worker crashed: {e}", exc_info=True)
    raise

logger.info("Stats background worker stopped")
