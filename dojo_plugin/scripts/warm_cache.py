import os
os.environ["CACHE_WARMER"] = "1"

from ..utils import scores
ds = scores.dojo_scores()
ms = scores.module_scores()

from ..utils import stats
cs = stats.container_stats()
for d in Dojos.query_all():
	ds = stats.dojo_stats(d)
