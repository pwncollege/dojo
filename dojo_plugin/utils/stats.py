from CTFd.cache import cache
from CTFd.models import Solves

from . import force_cache_updates, get_all_containers

@cache.memoize(timeout=300, forced_update=force_cache_updates)
def get_container_stats():
    containers = get_all_containers()
    return [{attr: container.labels[f"dojo.{attr}_id"]
            for attr in ["dojo", "module", "challenge"]}
            for container in containers]


@cache.memoize(timeout=300, forced_update=force_cache_updates)
def get_dojo_stats(dojo):
    return dict(
        users=dojo.solves().group_by(Solves.user_id).count(),
        challenges=len(dojo.challenges),
        visible_challenges=len([challenge for challenge in dojo.challenges if challenge.visible()]),
        solves=dojo.solves().count(),
    )
