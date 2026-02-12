import logging
from ...utils import get_all_containers
from ...utils.background_stats import set_cached_stat, is_event_stale
from . import register_handler

logger = logging.getLogger(__name__)

CACHE_KEY_CONTAINERS = "stats:containers"

def calculate_container_stats():
    containers = get_all_containers()
    return [{attr: container.labels.get(f"dojo.{attr}_id")
            for attr in ["dojo", "module", "challenge"]}
            for container in containers]

@register_handler("container_stats_update")
def handle_container_stats_update(payload, event_timestamp=None):
    if event_timestamp and is_event_stale(CACHE_KEY_CONTAINERS, event_timestamp):
        return

    try:
        logger.info("Calculating container stats...")
        container_data = calculate_container_stats()
        set_cached_stat(CACHE_KEY_CONTAINERS, container_data, updated_at=event_timestamp)
        container_count = len(container_data)
        logger.info(f"Successfully updated container stats cache ({container_count} containers)")
    except Exception as e:
        logger.error(f"Error calculating container stats: {e}", exc_info=True)

def initialize_all_container_stats():
    logger.info("Initializing container stats...")
    try:
        container_data = calculate_container_stats()
        set_cached_stat(CACHE_KEY_CONTAINERS, container_data)
        container_count = len(container_data)
        logger.info(f"Initialized container stats ({container_count} containers)")
    except Exception as e:
        logger.error(f"Error initializing container stats: {e}", exc_info=True)
