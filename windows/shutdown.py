import socket
import time
import os
from pathlib import Path

vm_hostname = "127.0.0.1"
port = 2222

def wait():
    start = time.time()
    while time.time() - start < 5 * 60:
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
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect("./build/monitor.sock")
    sock.sendall(b"system_powerdown\r\n")
    sock.close()


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
