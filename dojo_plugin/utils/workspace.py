import docker
docker_client = docker.from_env()

def exec_run(cmd, *, shell=False, assert_success=True, user="root", pwncollege_uid=None, container=None, **kwargs):

	if shell:
		cmd = f"""/bin/sh -c \"
		{cmd}
		\""""

	if not container:
		container = docker_client.containers.get(f"user_{pwncollege_uid}")
	exit_code, output = container.exec_run(cmd, user=user, **kwargs)
	if assert_success:
		assert exit_code in (0, None), output
	return exit_code, output
