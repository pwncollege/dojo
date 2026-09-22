import importlib.util
import io
from pathlib import Path, PurePosixPath
import shlex
import tarfile
from types import SimpleNamespace

import docker.errors
import pytest


@pytest.fixture(params=["dojo_plugin/utils/mac_docker.py", "sshd/mac_docker.py"])
def mac_backend(request):
    spec = importlib.util.spec_from_file_location(
        "mac_workspace_adapter", Path(__file__).resolve().parents[1] / request.param,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.MacDockerClient("mac.example", "operator", "/test/ssh-key")
    machines = {}

    def guest_control(command, **options):
        args = shlex.split(command)[3:]
        action, *args = args
        status, output = 0, b""
        if action == "images":
            if args[0] != "ventura":
                status = 1
        elif action == "create-vm":
            image, _, machine_id = args
            if image != "ventura":
                status = 1
            else:
                machines[machine_id] = {"files": {}}
                output = f"Started {machine_id}\n".encode()
        elif action == "list-vms":
            output = ("id\tstatus\n" + "".join(f"{machine_id}\trunning\n" for machine_id in machines)).encode()
        elif action == "kill-vm":
            machines.pop(args[0], None)
        elif action == "exec":
            if args[0] == "--tty":
                args = args[1:]
            machine_id, shell_command = args
            words = shlex.split(shell_command)
            user = "admin"
            if words[:4] == ["exec", "sudo", "su", "-"]:
                user, shell_command = words[4], words[6]
            machine = machines[machine_id]
            words = shlex.split(shell_command)
            if shell_command == "/sbin/shutdown -h now":
                del machines[machine_id]
            elif shell_command == "cat - > /Users/admin/hostname":
                machine["files"]["/Users/admin/hostname"] = options["input"]
            elif shell_command == "whoami":
                output = user.encode()
            elif shell_command == "cat":
                output = options["input"]
            elif words[0] == "exit":
                status = int(words[1])
            elif words[:5] == ["cat", "-", "|", "tar", "-xvf"]:
                destination = PurePosixPath(words[-1])
                with tarfile.open(fileobj=io.BytesIO(options["input"])) as archive:
                    for member in archive.getmembers():
                        machine["files"][str(destination / member.name)] = archive.extractfile(member).read()
            elif words[:3] == ["tar", "-cf", "-"]:
                path = words[3]
                if path not in machine["files"]:
                    status = 1
                else:
                    data = machine["files"][path]
                    stream = io.BytesIO()
                    with tarfile.open(fileobj=stream, mode="w") as archive:
                        member = tarfile.TarInfo(path.lstrip("/"))
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
                    output = stream.getvalue()
            elif words[0] == "printf" and words[-1] == "/flag":
                machine["files"]["/flag"] = words[2].encode() + b"\n"
            else:
                raise AssertionError(f"Unexpected guest command: {shell_command}")
        else:
            raise AssertionError(f"Unexpected guest action: {action}")
        if status and options.get("exception_on_fail", True):
            raise RuntimeError("Guest operation failed")
        return status, output

    client._ssh_exec = guest_control
    return SimpleNamespace(client=client, machines=machines)


@pytest.mark.parametrize("force", [False, True])
def test_mac_workspace_creation_lookup_and_removal_are_independent_for_each_user(mac_backend, force):
    client = mac_backend.client
    assert client.images.get("mac:ventura").name == "ventura"
    first = client.containers.create("mac:ventura", name="user_41", hostname="hello~apple")
    second = client.containers.create("mac:ventura", name="user_42", hostname="hello~banana")
    first.start()
    second.start()

    assert client.containers.get(first.id).status == "running"
    assert client.containers.get(second.id).status == "running"
    assert mac_backend.machines[first.id]["files"]["/Users/admin/hostname"] == b"hello~apple"
    assert mac_backend.machines[second.id]["files"]["/Users/admin/hostname"] == b"hello~banana"

    first.remove(force=force)
    first.wait(condition="removed")

    with pytest.raises(docker.errors.NotFound):
        client.containers.get(first.id)
    assert client.containers.get(second.id).status == "running"


def test_mac_workspace_reports_missing_images_and_workspaces(mac_backend):
    with pytest.raises(docker.errors.NotFound):
        mac_backend.client.images.get("mac:missing")
    with pytest.raises(docker.errors.NotFound):
        mac_backend.client.images.get("ubuntu:latest")
    with pytest.raises(docker.errors.NotFound):
        mac_backend.client.containers.get("user_404")
    assert not mac_backend.machines


def test_mac_workspace_commands_use_the_requested_identity_and_preserve_results(mac_backend):
    container = mac_backend.client.containers.create("mac:ventura", name="user_41")

    assert container.exec_run("whoami", user="1000") == (0, b"hacker")
    assert container.exec_run("whoami", user="0") == (0, b"root")
    assert container.exec_run("cat", user="1000", input=b"learner input", use_tty=False) == (0, b"learner input")
    assert container.exec_run("exit 23", user="1000") == (23, b"")


def test_mac_workspace_challenge_files_and_initialization_data_reach_the_guest(mac_backend):
    container = mac_backend.client.containers.create("mac:ventura", name="user_41")
    content = b"challenge instructions\x00\xff"
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        member = tarfile.TarInfo("README")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    stream.seek(0)

    container.put_archive("/challenge", stream)
    received = container.get_archive("/challenge/README")

    with tarfile.open(fileobj=io.BytesIO(received)) as archive:
        assert archive.extractfile("challenge/README").read() == content
    socket = container.attach_socket(params={"stdin": 1, "stream": 1})
    socket._sock.sendall(b"pwn.college{practice}\n")
    socket.close()
    assert mac_backend.machines[container.id]["files"]["/flag"] == b"pwn.college{practice}\n"
    with pytest.raises(docker.errors.NotFound):
        container.get_archive("/missing")
