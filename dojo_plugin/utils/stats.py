import docker

def container_stats():
    user_containers = docker.from_env().containers.list(filters={
        "name": "user_",
        #"label": [ f"dojo.dojo_id={dojo.reference_id}", f"dojo.module_id={module.id}" ]
    }, ignore_removed=True)
    return [ {
            'user': c.name.split("_")[-1],
            'dojo': c.labels['dojo.dojo_id'],
            'module': c.labels['dojo.module_id'],
            'challenge': c.labels['dojo.challenge_id']
    } for c in user_containers ]
