import docker
docker_client = docker.from_env()

def exec_run(cmd, *, shell=False, assert_success=True, workspace_user="root", user_id=None, container=None, **kwargs):

	if shell:
		cmd = f"""/bin/sh -c \"
		{cmd}
		\""""

	if not container:
		container = docker_client.containers.get(f"user_{user_id}")
	exit_code, output = container.exec_run(cmd, user=workspace_user, **kwargs)
	if assert_success:
		assert exit_code in (0, None), output
	return exit_code, output
