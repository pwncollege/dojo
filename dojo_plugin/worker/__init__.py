import logging

logger = logging.getLogger(__name__)

def run_worker():
    from . import __main__
    __main__.main()
