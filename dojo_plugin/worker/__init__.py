import logging

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

logger = logging.getLogger(__name__)


def setup_worker_logging(name):
    worker_logger = logging.getLogger(name)
    worker_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    worker_logger.addHandler(handler)
    return worker_logger


def run_worker():
    from . import __main__
    __main__.main()
