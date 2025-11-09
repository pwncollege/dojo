import os
import shlex
import subprocess
import time

import docker.errors

# docker.DockerClient compatible interface for spining up stuff on our mac hardware

# mac image spec is: mac:<image_name>

# Need to support:
# - docker_client.containers.get(container_name(user))
# - container.remove
# - container.wait(condition="removed")
# - docker_client.images.get(dojo_challenge.image)
# - image.attrs["Config"].get("Env") or []
# - docker_client.containers.create(image, entrypoint=, name=, hostname=, user=, working_dir=, environment=, labels=, mounts=, devices=, network=, extra_hosts=, auto_remove=, ...)
# - docker_client.networks.get("workspace_net")
#     - workspace_net.connect(container, ipv4_address=user_ipv4(user), aliases=[container_name(user)])
# - docker_client.networks.get("bridge")
# - default_network.disconnect(container)
# - container.start()
# - container.exec_run(cmd, user=workspace_user, **kwargs)
# - container.attach_socket(params=dict(stdin=1, stream=1))
# - container.put_archive(directory, tarbar)

MAC_GUEST_CONTROL_FILE = "MACOSVM=/usr/local/bin/macosvm /usr/bin/python3 ./mac-host/guest-control.py"
MAC_TIMEOUT_SECONDS = 60 * 60 * 4

class MacDockerClient:
    def __init__(self, hostname, username, key_path):
        self.hostname = hostname
        self.username = username
        self.key_path = key_path

        self.containers = MacContainerCollection(self)
        self.images = MacImageCollection(self)
        self.networks = MacNetworkCollection(self)
        self.volumes = MacVolumeCollection(self)

        # this insanity is required b/c of some high level code
        class MyAPIThing:
            def __init__(self):
                self.base_url = "localhost"
        self.api = MyAPIThing()

    def close(self):
        pass  # No persistent connection to close

    def _ssh_exec(self, command, only_stdout=True, exception_on_fail=True, input=None, capture_output=True, timeout_seconds=None):
        ssh_command = ['ssh',
                       "-a",
                       "-o", "StrictHostKeychecking=no",
                       "-o", "UserKnownHostsFile=/dev/null",
                       "-o", "ControlMaster=no",
                       "-o", "LogLevel=ERROR",
                       ]
        if self.key_path:
            ssh_command.extend(['-i', self.key_path])
        if self.username:
            ssh_command.append(f'{self.username}@{self.hostname}')
        else:
            ssh_command.append(self.hostname)
        ssh_command.append(command)
        if capture_output:
            stdout_loc = subprocess.PIPE
            stderr_loc = subprocess.PIPE
            if not only_stdout:
                stderr_loc = subprocess.STDOUT
        else:
            stdout_loc = None
            stderr_loc = None

        result = subprocess.run(ssh_command, stdout=stdout_loc, stderr=stderr_loc, input=input, timeout=timeout_seconds)
        if result.returncode != 0:
            if exception_on_fail:
                error_msg = result.stdout.strip()
                raise Exception(f'SSH {ssh_command=} {self.username=} {self.key_path=} {self.hostname=} {result=} {result.returncode=} failed: {error_msg}')
        return result.returncode, result.stdout.strip() if result.stdout else b""



class MockDetachedContainer:
    """Mock container for detach=True mode compatibility"""
    def wait(self):
        pass

    def logs(self):
        return b""

    def remove(self):
        pass

class MacContainerCollection:
    def __init__(self, client):
        self.client = client

    def get(self, name):
        # Run 'guest-control.py list-vms' and parse the output
        exitcode, output = self.client._ssh_exec(f'{MAC_GUEST_CONTROL_FILE} list-vms', input=b"", timeout_seconds=10)
        output = output.decode('latin-1')
        vms = self.parse_list_vms(output)
        for vm in vms:
            if vm['id'] == name:
                return MacContainer(self.client, vm)
        raise docker.errors.NotFound(f'Container {name} not found')

    def create(self, image, entrypoint=None, name=None, hostname=None, user=None,
               working_dir=None, environment=None, labels=None, mounts=None, devices=None,
               network=None, extra_hosts=None, auto_remove=None, **kwargs):
        # Create a VM with the given parameters
        assert image.startswith("mac:")
        image = image.split("mac:", maxsplit=1)[-1]
        command = f'{MAC_GUEST_CONTROL_FILE} create-vm {image}'
        if name:
            command += f' --id {name}'
        exitcode, output = self.client._ssh_exec(command, input=b"")
        output = output.decode('latin-1')
        # not sure if the following actually parses
        if 'Started' in output:
            unique_id = output.strip().split(' ')[1]
            # Status is always running after create
            vm = {'id': unique_id, 'status': 'running'}
            # set up the timeout
            container = MacContainer(self.client, vm)
            # we want to setup the hostname if it exists
            if hostname:
                container.exec_run("cat - > /Users/admin/hostname", input=hostname.encode())
            return container
        else:
            raise Exception(f'Error creating container: {image=} {name=} {output}')

    def parse_list_vms(self, output):
        # Parse the output of 'guest-control.py list-vms' and return a list of dicts
        lines = output.strip().split('\n')
        if not lines:
            return []
        header = lines[0].split('\t')
        vms = []
        for line in lines[1:]:
            fields = line.split('\t')
            vm_info = dict(zip(header, fields))
            vms.append(vm_info)
        return vms

    # ------------------------------------------------------------------
    # NEW: stub implementation of Docker SDK-style `.run`
    # ------------------------------------------------------------------
    # docker-py exposes `run(image, command=None, **kwargs)` on
    # `ContainerCollection`, providing the familiar `docker run` behaviour. :contentReference[oaicite:0]{index=0}
    # It normally returns the container’s logs (bytes) unless `detach=True`,
    # in which case it yields a `Container` object. :contentReference[oaicite:1]{index=1}
    # For our mac-backed shim we only need interface compatibility, so we
    # accept the same parameters and immediately return an empty byte string. :contentReference[oaicite:2]{index=2}
    def run(self, image, command=None, **kwargs):
        if kwargs.get('detach', False):
            return MockDetachedContainer()
        return b""

class MacContainer:
    def __init__(self, client, vm_info):
        self.client = client
        self.id = vm_info['id']
        self.vm_info = vm_info
        self.status = vm_info.get("status", "creating")

    def logs(self, stream, follow):
        # Very hacky thing, just return the other hacky thing that we did
        return self.attach(stream)

    def attach(self, stream):
        # Super hacky thing, this just needs to return [b"Initialized.\n"]
        return [b"Initialized.\n", b"Ready.\n"]

    def remove(self, force=True):
        # Kill the VM

        # first try to shutdown the VM
        timeout_hit = False
        try:
            self.exec_run("/sbin/shutdown -h now", "0", timeout_seconds=8, input=b"")
        except subprocess.TimeoutExpired:
            # if that didn't work, kill it
            timeout_hit = True

        if force or timeout_hit:
            command = f'{MAC_GUEST_CONTROL_FILE} kill-vm {self.id}'
            exitcode, output = self.client._ssh_exec(command, exception_on_fail=False, input=b"", timeout_seconds=5)

    def wait(self, condition='removed'):
        # Wait until the VM is removed
        if condition == "removed":
            while True:
                try:
                    container = self.client.containers.get(self.id)
                    time.sleep(1)
                except docker.errors.NotFound:
                    # Container not found, assume removed
                    break
        else:
            raise NotImplementedError

    def start(self):
        # VMs are started upon creation
        pass

    # returns exit_code, output
    def exec_run(self, cmd, user=None, input=None, capture_output=True, timeout_seconds=None, use_tty=True, **kwargs):
        # SSH to the VM's IP address and run the command
        if user == "0" or user == None:
            # they want to run the command as root
            cmd = f"exec sudo su - root -c {shlex.quote(cmd)}"
        elif user == "1000":
            # they want to run the command as hacker
            cmd = f"exec sudo su - hacker -c {shlex.quote(cmd)}"
        tty_arg = '--tty' if use_tty else ''
        command = f"{MAC_GUEST_CONTROL_FILE} exec {tty_arg} {self.id} {shlex.quote(cmd)}"
        exitcode, output = self.client._ssh_exec(command, only_stdout=False, exception_on_fail=False, input=input, capture_output=capture_output, timeout_seconds=timeout_seconds)
        return exitcode, output

    # execve shell
    def execve_shell(self, cmd, user=None, use_tty=True):

        if user == "0" or user == None:
            # they want to run the command as root
            cmd = f"exec sudo su - root -c {shlex.quote(cmd)}"
        elif user == "1000":
            # they want to run the command as hacker
            cmd = f"exec sudo su - hacker -c {shlex.quote(cmd)}"
        tty_arg = '--tty' if use_tty else ''
        command = f"{MAC_GUEST_CONTROL_FILE} exec {tty_arg} {self.id} {shlex.quote(cmd)}"
        to_exec = [
            "ssh",
            "-i", self.client.key_path,
            "-a", # prevent any SSH agent forward crazyness
            "-o", "StrictHostKeychecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ControlMaster=no",
            "-o", "LogLevel=ERROR",
        ]
        if use_tty:
            to_exec.append("-t")
        to_exec.append(f"{self.client.username}@{self.client.hostname}")
        to_exec.append(command)
        os.execv(
            "/usr/bin/ssh",
            to_exec,
        )


    def send_flag(self, flag):
        flag = flag.strip()
        flag = flag.decode('latin-1')
        self.exec_run(f"echo '{flag}' | sudo tee /flag", input=b"")

    def attach_socket(self, params=None):
        class MySendall:
            def __init__(self, container):
                self.sendall = lambda flag: container.send_flag(flag)

        class MySock:
            def __init__(self, container):
                self._sock = MySendall(container)
            def close(self):
                pass
        return MySock(self)

    def put_archive(self, path, data):
        self.exec_run(f"cat - | tar -xvf - -C {shlex.quote(path)}", input=data.read())

    def get_archive(self, path):
        exitcode, output = self.exec_run(f"tar -cf - {shlex.quote(path)}", input=b"")
        if exitcode != 0:
            raise docker.errors.NotFound(f'Getting archive {path=} failed {exitcode=} {output=}')
        return output



class MacImageCollection:
    def __init__(self, client):
        self.client = client

    def get(self, image_name):
        # Check if the image exists on 'fluffy'
        if not image_name.startswith("mac:"):
            raise docker.errors.NotFound(f'Image {image_name} is not compatible')
        image_name = image_name.split("mac:", maxsplit=1)[-1]
        command = f"{MAC_GUEST_CONTROL_FILE} images {image_name}"
        try:
            exitcode, output = self.client._ssh_exec(command, input=b"", timeout_seconds=10)
        except Exception as e:
            raise docker.errors.NotFound(f'Image {image_name} not found: {e}')

        attrs = {'Config': {}}
        return MacImage(image_name, attrs)


class MacImage:
    def __init__(self, name, attrs):
        self.name = name
        self.attrs = attrs


class MacNetworkCollection:
    def __init__(self, client):
        self.client = client

    def get(self, network_name):
        # Simulate network operations
        return MacNetwork(network_name)

class MacNetwork:
    def __init__(self, name):
        self.name = name

    def connect(self, container, ipv4_address=None, aliases=None):
        # Simulate network connection
        pass

    def disconnect(self, container):
        # Simulate network disconnection
        pass



class MacVolumeCollection:
    def __init__(self, client):
        self.client = client

    def get(self, volume_name):
        # Simulate volume operations
        return MacVolume(volume_name)


class MacVolume:
    def __init__(self, name):
        self.name = name

    def remove(self):
        # Simulate volume removal
        pass
