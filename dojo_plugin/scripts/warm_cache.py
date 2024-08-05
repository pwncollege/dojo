import os
import logging

os.environ["CACHE_WARMER"] = "1"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from ..utils import scores
scores.dojo_scores()
logger.info("Dojo scores cache warmed.")
scores.module_scores()
logger.info("Module scores cache warmed.")

from ..utils import stats
stats.container_stats()
logger.info("Container stats cache warmed.")
for dojo in Dojos.query:
	stats.dojo_stats(dojo)
	logger.info(f"Dojo stats cache warmed for {dojo.reference_id}.")
