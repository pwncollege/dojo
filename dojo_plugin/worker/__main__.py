import logging
import os
import signal
import time

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

if os.environ.get("SKIP_COLD_START"):
    logger.info("SKIP_COLD_START set, skipping cache initialization")
else:
    from ..worker.handlers.dojo_stats import initialize_all_dojo_stats
    from ..worker.handlers.scoreboard import initialize_all_scoreboards
    from ..worker.handlers.scores import initialize_all_scores
    from ..worker.handlers.awards import initialize_all_belts, initialize_all_emojis
    from ..worker.handlers.containers import initialize_all_container_stats
    from ..worker.handlers.activity import initialize_all_activity

    logger.info("Performing cold start cache initialization...")

    try:
        cold_start_begin = time.time()

        step_start = time.time()
        initialize_all_dojo_stats()
        logger.info(f"Dojo stats initialization complete ({time.time() - step_start:.2f}s)")

        step_start = time.time()
        initialize_all_scoreboards()
        logger.info(f"Scoreboard initialization complete ({time.time() - step_start:.2f}s)")

        step_start = time.time()
        initialize_all_scores()
        logger.info(f"Scores initialization complete ({time.time() - step_start:.2f}s)")

        step_start = time.time()
        initialize_all_belts()
        logger.info(f"Belts initialization complete ({time.time() - step_start:.2f}s)")

        step_start = time.time()
        initialize_all_emojis()
        logger.info(f"Emojis initialization complete ({time.time() - step_start:.2f}s)")

        step_start = time.time()
        initialize_all_container_stats()
        logger.info(f"Container stats initialization complete ({time.time() - step_start:.2f}s)")

        step_start = time.time()
        initialize_all_activity()
        logger.info(f"Activity initialization complete ({time.time() - step_start:.2f}s)")

        logger.info(f"Cold start complete - all stats initialized ({time.time() - cold_start_begin:.2f}s total)")
    except Exception as e:
        logger.error(f"Error during cold start: {e}", exc_info=True)

logger.info("Starting event consumption loop...")

from ..utils.background_stats import consume_stat_events, DailyRestartException
from ..worker.handlers import handle_stat_event

try:
    consume_stat_events(
        handler=handle_stat_event,
        batch_size=10,
        block_ms=5000
    )
except KeyboardInterrupt:
    logger.info("Worker interrupted by user")
except DailyRestartException:
    logger.info("Daily restart - exiting for cold start refresh")
except Exception as e:
    logger.error(f"Worker crashed: {e}", exc_info=True)
    raise

logger.info("Stats background worker stopped")
