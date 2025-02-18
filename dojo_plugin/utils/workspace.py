import docker
from CTFd.models import Users

from . import user_docker_client

on_demand_services = { "code", "desktop"}

def start_on_demand_service(user, service_name):
    if service_name not in on_demand_services:
        return
    try:
        exec_run(
            f"/run/current-system/sw/bin/dojo-{service_name}",
            workspace_user="hacker",
            user_id=user.id,
            assert_success=True,
        )
    except docker.errors.NotFound:
        return False
    return True


def exec_run(cmd, *, shell=False, assert_success=True, workspace_user="root", user_id=None, container=None, **kwargs):
    # TODO: Cleanup this interface
    if workspace_user == "root":
        workspace_user = "0"
    if workspace_user == "hacker":
        workspace_user = "1000"

    if shell:
        cmd = f"""/bin/sh -c \"
        {cmd}
        \""""

    if not container:
        docker_client = user_docker_client(Users.query.get(user_id))
        container = docker_client.containers.get(f"user_{user_id}")
    exit_code, output = container.exec_run(cmd, user=workspace_user, **kwargs)
    if assert_success:
        assert exit_code in (0, None), output
    return exit_code, output

def reset_home(user_id):
    exec_run(f"/bin/tar cvzf /tmp/home-backup.tar.gz /home/hacker", user_id=user_id, shell=True, workspace_user="hacker")
    exec_run(f"find /home/hacker -mindepth 1 -delete", user_id=user_id, shell=True, workspace_user="root")
    exec_run(f"chown hacker:hacker /home/hacker", user_id=user_id, shell=True, workspace_user="root")
    exec_run(f"cp /tmp/home-backup.tar.gz /home/hacker/", user_id=user_id, shell=True, workspace_user="hacker")