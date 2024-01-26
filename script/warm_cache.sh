#!/bin/sh

dojo flask <<END
from ..utils import scores
ds = scores.dojo_scores()
ms = scores.module_scores()
print(f"""
	  {len(ds)=}
	  {len(ms)=}
""")
END
