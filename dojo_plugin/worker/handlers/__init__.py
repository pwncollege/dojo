import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

EVENT_HANDLERS = {}
_handlers_loaded = False

def register_handler(event_type: str):
    def decorator(func):
        EVENT_HANDLERS[event_type] = func
        return func
    return decorator

def _load_handlers():
    global _handlers_loaded
    if not _handlers_loaded:
        from . import dojo_stats, scoreboard
        _handlers_loaded = True

def handle_stat_event(event_type: str, payload: Dict[str, Any]):
    _load_handlers()
    handler = EVENT_HANDLERS.get(event_type)
    if handler:
        try:
            handler(payload)
        except Exception as e:
            logger.error(f"Error handling event {event_type}: {e}", exc_info=True)
    else:
        logger.warning(f"No handler registered for event type: {event_type}")
