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

MAC_HOSTNAME = os.environ.get("MAC_HOSTNAME", "morholt")
MAC_USERNAME = os.environ.get("MAC_USERNAME", "adamd")
MAC_KEY_FILE = os.environ.get("MAC_KEY_FILE", "/opt/pwn.college/data/mac-key")
MAC_GUEST_CONTROL_FILE = os.environ.get("MAC_GUEST_CONTROL_FILE", "guest-control.py")
MAC_TIMEOUT_SECONDS = os.environ.get("MAC_TIMEOUT_SECONDS", 60*60*4)

class MacDockerClient:
    def __init__(self, hostname=None, username=None, key_filename=None, guest_key_file=None):
        self.hostname = hostname or MAC_HOSTNAME
        self.username = username or MAC_USERNAME
        self.key_filename = key_filename or MAC_KEY_FILE  # Path to the SSH key for 'fluffy'

        self.containers = MacContainerCollection(self)
        self.images = MacImageCollection(self)
        self.networks = MacNetworkCollection(self)

    def close(self):
        pass  # No persistent connection to close

    def _ssh_exec(self, command, only_stdout=True, exception_on_fail=True, input=None, capture_output=True):
        ssh_command = ['ssh',
                       "-a",
                       "-o", "StrictHostKeychecking=no",
                       "-o", "UserKnownHostsFile=/dev/null",
                       "-o", "ControlMaster=no",
                       "-o", "LogLevel=ERROR",
                       ]
        if self.key_filename:
            ssh_command.extend(['-i', self.key_filename])
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
            
        result = subprocess.run(ssh_command, stdout=stdout_loc, stderr=stderr_loc, input=input)
        if result.returncode != 0:
            if exception_on_fail:
                error_msg = result.stdout.strip()
                raise Exception(f'SSH {command=} {self.username=} {self.key_filename=} {self.hostname=} failed: {error_msg}')
        return result.returncode, result.stdout.strip() if result.stdout else b""
    


class MacContainerCollection:
    def __init__(self, client):
        self.client = client

    def get(self, name):
        # Run 'guest-control.py list-vms' and parse the output
        exitcode, output = self.client._ssh_exec(f'{MAC_GUEST_CONTROL_FILE} list-vms')
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
        exitcode, output = self.client._ssh_exec(command)
        output = output.decode('latin-1')
        # not sure if the following actually parses
        if 'Started' in output:
            unique_id = output.strip().split(' ')[1]
            # Status is always running after create
            vm = {'id': unique_id, 'status': 'running'}
            time.sleep(1)
            # set up the timeout
            container = MacContainer(self.client, vm)
            container.exec_run(f"nohup bash -c 'sleep {MAC_TIMEOUT_SECONDS} && echo \"VM and all files going away in 5 minutes, better save now\" | wall && sleep 300 && echo \"VM and all files going away in 1 minute, last warning\" | wall && sleep 60 && shutdown -h now' > /dev/null &", user="0")
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

class MacContainer:
    def __init__(self, client, vm_info):
        self.client = client
        self.id = vm_info['id']
        self.vm_info = vm_info
        self.status = vm_info.get("status", "creating")

    def remove(self, force=True):
        # Kill the VM
        command = f'{MAC_GUEST_CONTROL_FILE} kill-vm {self.id}'
        exitcode, output = self.client._ssh_exec(command)
        if b'Error' in output:
            raise Exception(f'Error removing container: {output}')

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
    def exec_run(self, cmd, user=None, input=None, capture_output=True, **kwargs):
        # SSH to the VM's IP address and run the command
        if user == "0" or user == None:
            # they want to run the command as root
            cmd = f"exec sudo su - root -c {shlex.quote(cmd)}"
        elif user == "1000":
            # they want to run the command as hacker
            cmd = f"exec sudo su - hacker -c {shlex.quote(cmd)}"
        command = f"{MAC_GUEST_CONTROL_FILE} exec {self.id} {shlex.quote(cmd)}"
        exitcode, output = self.client._ssh_exec(command, only_stdout=False, exception_on_fail=False, input=input, capture_output=capture_output)
        return exitcode, output

    # execve shell
    def execve_shell(self, cmd, user=None):
        if user == "0" or user == None:
            # they want to run the command as root
            cmd = f"exec sudo su - root -c {shlex.quote(cmd)}"
        elif user == "1000":
            # they want to run the command as hacker
            cmd = f"exec sudo su - hacker -c {shlex.quote(cmd)}"
        command = f"{MAC_GUEST_CONTROL_FILE} exec {self.id} {shlex.quote(cmd)}"
        os.execv(
            "/usr/bin/ssh",
            [
                "ssh",
                "-i", self.client.key_filename,
                "-t", # force SSH to allocate a TTY
                "-a", # prevent any SSH agent forward crazyness
                "-o", "StrictHostKeychecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ControlMaster=no",
                "-o", "LogLevel=ERROR",
                f"{self.client.username}@{self.client.hostname}",
                command
            ]
        )


    def send_flag(self, flag):
        flag = flag.strip()
        flag = flag.decode('latin-1')
        self.exec_run(f"echo '{flag}' | sudo tee /flag")

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
        pass
        
    

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
            exitcode, output = self.client._ssh_exec(command)
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
