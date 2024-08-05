import os
import sys
import signal
import argparse
from pathlib import Path

RUN_DIR = Path("/run/dojo/var")

def daemonize(service_name, exec_command):
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #1 failed: {e.errno} ({e.strerror})\n")
        sys.exit(1)

    os.setsid()

    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #2 failed: {e.errno} ({e.strerror})\n")
        sys.exit(1)

    sys.stdout.flush()
    sys.stderr.flush()

    log_file = RUN_DIR / f"{service_name}.log"
    with open('/dev/null', 'r') as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(log_file, 'a+') as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())

    pid_file = RUN_DIR / f"{service_name}.pid"
    pid_file.write_text(str(os.getpid()))

    os.execve(exec_command[0], exec_command, os.environ)

def start_service(service_name, exec_command):
    pid_file = RUN_DIR / f"{service_name}.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text())
            os.kill(pid, 0)
        except (OSError, ValueError):
            pass
        else:
            print(f"Service {service_name} is already running.")
            return

    service_dir = (RUN_DIR / service_name).parent
    service_dir.mkdir(parents=True, exist_ok=True)

    daemonize(service_name, exec_command)
    print(f"Service {service_name} started.")

def terminate_service(service_name, signal):
    pid_file = RUN_DIR / f"{service_name}.pid"
    if not pid_file.exists():
        print(f"Service {service_name} is not running.")
        return

    try:
        pid = int(pid_file.read_text())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, ProcessLookupError):
        pass

    if pid_file.exists():
        pid_file.unlink()
    print(f"Service {service_name} stopped.")

stop_service = lambda service_name: terminate_service(service_name, signal.SIGTERM)
kill_service = lambda service_name: terminate_service(service_name, signal.SIGKILL)

def status_service(service_name):
    if (RUN_DIR / service_name).is_dir():
        for pid_file in RUN_DIR.rglob("*.pid"):
            service_name = pid_file.relative_to(RUN_DIR).with_suffix("")
            status_service(service_name)
        return

    pid_file = RUN_DIR / f"{service_name}.pid"
    if pid_file.exists():
        try:
            with pid_file.open('r') as f:
                pid = int(f.read())
            os.kill(pid, 0)
            print(f"Service {service_name} is running with PID {pid}.")
        except (OSError, ValueError):
            print(f"Service {service_name} PID file found, but process is not running.")
    else:
        print(f"Service {service_name} is not running.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Python start-stop-daemon")
    parser.add_argument("command", choices=["start", "stop", "kill", "status"], help="Command to run")
    parser.add_argument("service_name", help="Name of the service")
    parser.add_argument("exec_command", help="Command to execute for the service", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.command == "start":
        start_service(args.service_name, args.exec_command)
    elif args.command == "stop":
        stop_service(args.service_name)
    elif args.command == "kill":
        kill_service(args.service_name)
    elif args.command == "status":
        status_service(args.service_name)
