import docker

from CTFd.cache import cache
from CTFd.models import Users, Solves

from . import force_cache_updates

@cache.memoize(timeout=300, forced_update=force_cache_updates)
def container_stats():
    user_containers = docker.from_env().containers.list(filters={
        "name": "user_",
    }, ignore_removed=True)
    return [ {
            'user': int(c.name.split("_")[-1]),
            'dojo': c.labels['dojo.dojo_id'],
            'module': c.labels['dojo.module_id'],
            'challenge': c.labels['dojo.challenge_id']
    } for c in user_containers if not Users.query.where(Users.id==int(c.name.split("_")[-1])).one().hidden ]

@cache.memoize(timeout=300, forced_update=force_cache_updates)
def dojo_stats(dojo):
    docker_client = docker.from_env()
    filters = {
        "name": "user_",
        "label": f"dojo.dojo_id={dojo.reference_id}"
    }
    containers = docker_client.containers.list(filters=filters, ignore_removed=True)

    return {
        "active": len(containers),
        "users": int(dojo.solves().group_by(Solves.user_id).count()),
        "challenges": int(len(dojo.challenges)),
        "visible_challenges": int(len([c for c in dojo.challenges if c.visible()])),
        "solves": int(dojo.solves().count()),
    }
