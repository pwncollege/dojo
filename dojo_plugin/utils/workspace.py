import requests
import logging
import docker
import time
from .request_logging import log_generator_output
from CTFd.models import Users

from . import user_docker_client

logger = logging.getLogger(__name__)

on_demand_services = { "terminal", "code", "desktop"}

def start_on_demand_service(user, service_name, theme_data=None):
    if service_name not in on_demand_services:
        return None
    try:
        # Prepare environment variables for theme data
        env_vars = {}
        if service_name in ["terminal", "code"] and theme_data:
            env_vars["TERMINAL_THEME_NAME"] = theme_data
            print(f"[WORKSPACE] Setting TERMINAL_THEME_NAME={theme_data} for {service_name}")
        elif service_name in ["terminal", "code"]:
            print(f"[WORKSPACE] No theme data provided for {service_name}, using default")

        exec_run(
            f"/run/current-system/sw/bin/timeout -k 10 30 /run/current-system/sw/bin/dojo-{service_name}",
            workspace_user="hacker",
            user_id=user.id,
            assert_success=True,
            log=True,
            environment=env_vars if env_vars else None,
        )
    except (docker.errors.NotFound, AssertionError, requests.HTTPError) as exception:
        logger.warning(f"start_on_demand_service failure: {service_name=} {exception=}")
        return False
    return True


def exec_run(cmd, *, shell=False, assert_success=True, workspace_user="root", user_id=None, container=None, log=False, **kwargs):
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

    start_time = time.time()
    if log:
        # Extract environment variables from kwargs for exec_create
        environment = kwargs.get('environment', None)
        exec_create_kwargs = {
            "privileged": False,
            "user": workspace_user
        }
        if environment:
            exec_create_kwargs["environment"] = environment

        exec_id = docker_client.api.exec_create(container.id, cmd, **exec_create_kwargs)["Id"]
        out_stream = docker_client.api.exec_start(exec_id, stream=True, demux=False)
        output = b"".join(log_generator_output(f"exec_run {cmd=} ", out_stream, start_time=start_time))
        exit_code = docker_client.api.exec_inspect(exec_id)['ExitCode']
    else:
        exit_code, output = container.exec_run(cmd, user=workspace_user, **kwargs)

    logger.info(f"exec_run finished {cmd=} {workspace_user=} elapsed={time.time()-start_time:.1f}s {exit_code=} output={output[:13337]}")

    if assert_success:
        assert exit_code in (0, None), output
    return exit_code, output

def reset_home(user_id):
    exec_run("/bin/tar cvzf /tmp/home-backup.tar.gz /home/hacker", user_id=user_id, shell=True, workspace_user="hacker")
    exec_run("find /home/hacker -mindepth 1 -delete", user_id=user_id, shell=True, workspace_user="root")
    exec_run("chown hacker:hacker /home/hacker", user_id=user_id, shell=True, workspace_user="root")
    exec_run("cp /tmp/home-backup.tar.gz /home/hacker/", user_id=user_id, shell=True, workspace_user="hacker")
