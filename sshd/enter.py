#!/usr/bin/env python3

import os
import pathlib
import sys
import time

import yaml
from kubernetes import client, config as kube_config
from kubernetes.client.rest import ApiException

KUBECONFIG_PATH = pathlib.Path("/var/kubeconfig/kube.yaml")
KUBE_CONFIG_DEFAULT_PATH = pathlib.Path(os.path.expanduser(kube_config.KUBE_CONFIG_DEFAULT_LOCATION))

kube_config_dict = yaml.safe_load(open(KUBECONFIG_PATH, "r"))
for cluster in kube_config_dict["clusters"]:
    if cluster["name"] == "default":
        cluster["cluster"]["server"] = "https://kube-server:6443"
KUBE_CONFIG_DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
kube_config.load_kube_config_from_dict(kube_config_dict)

if not KUBE_CONFIG_DEFAULT_PATH.exists():
    yaml.dump(kube_config_dict, KUBE_CONFIG_DEFAULT_PATH.open("w"))

def main():
    original_command = os.getenv("SSH_ORIGINAL_COMMAND")
    tty = os.getenv("SSH_TTY") is not None
    simple = bool(not tty or original_command)

    def print(*args, **kwargs):
        if simple:
            return
        kwargs.update(file=sys.stderr)
        return __builtins__.print(*args, **kwargs)

    if len(sys.argv) != 2:
        print(f"{sys.argv[0]} <container_name>")
        exit(1)
    pod_name = sys.argv[1]

    api_instance = client.CoreV1Api()

    try:
        pod = api_instance.read_namespaced_pod(pod_name, "default")
        status = pod.status.phase
        assert pod.status.phase not in ["Succeeded", "Failed", "Unknown"]
    except ApiException:
        status = "NotFound"
    if status in ["NotFound", "Succeeded", "Failed", "Unknown"]:
        print("No active challenge session; start a challenge!")
        exit(1)

    attempts = 0
    while attempts < 30:
        try:
            pod = api_instance.read_namespaced_pod(pod_name, "default")
            status = pod.status.phase
        except ApiException as e:
            status = "NotFound"

        if status not in ["Running"]:
            attempts += 1
            print("\033c", end="")
            print("\r", " " * 80, f"\rConnecting -- status: {status}", end="")
            time.sleep(1)
            continue

        attempts = 0
        print("\r", " " * 80, "\rConnected!")

        if not os.fork():
            ssh_entrypoint = "/opt/pwn.college/ssh-entrypoint"
            command = [ssh_entrypoint, "-c", original_command] if original_command else [ssh_entrypoint]
            os.execve(
                "/usr/bin/kubectl",
                [
                    "kubectl",
                    "exec",
                    "-it" if tty else "-i",
                    "-q",
                    pod_name,
                    "--",
                    *command,
                ],
            )

        else:
            _, status = os.wait()
            if simple or status == 0:
                break
            print()
            print("\r", " " * 80, "\rConnecting", end="")
            time.sleep(0.5)
    else:
        print("\r", " " * 80, "\rError: failed to connect!")


if __name__ == "__main__":
    main()
