import docker

on_demand_services = { "code", "desktop", "desktop-windows" }

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

    docker_client = docker.from_env()

    if not container:
        container = docker_client.containers.get(f"user_{user_id}")
    exit_code, output = container.exec_run(cmd, user=workspace_user, **kwargs)
    if assert_success:
        assert exit_code in (0, None), output
    return exit_code, output
