import socket
import time
import os
import subprocess
from pathlib import Path

vm_hostname = "127.0.0.1"
port = 2222


def wait():
    start = time.time()
    while time.time() - start < 10 * 60:
        try:
            connection = socket.create_connection((vm_hostname, port), timeout=10)
            data = connection.recv(3)
            connection.close()
            if data == b"SSH":
                return
        except (ConnectionRefusedError, socket.timeout):
            pass
        time.sleep(0.1)
    print("Timeout expired")


def shutdown():
    subprocess.check_call(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-p",
            str(port),
            f"hacker@{vm_hostname}",
            "--",
            "Set-Service -Name sshd -StartupType Manual; "
            + "Set-Service -Name tvnserver -StartupType Manual; "
            + "Stop-Computer -Force",
        ]
    )


def qemu_running():
    procfs = Path("/proc")
    pid_dirs = [d for d in procfs.iterdir() if d.name.isdigit()]
    for pid in pid_dirs:
        try:
            exe_link = Path("/proc") / str(pid) / "exe"
            if "qemu" in os.readlink(str(exe_link)):
                return True
        except FileNotFoundError:
            pass
    return False


def wait_qemu_exit():
    start = time.time()
    while time.time() - start < 2 * 60 and qemu_running():
        time.sleep(1)


if __name__ == "__main__":
    wait()
    time.sleep(30)
    shutdown()
    wait_qemu_exit()
