#!/usr/bin/env python3

import sys

import docker


def main():
    client = docker.from_env()
    for event in client.events(decode=True):
        if event["Type"] != "container":
            continue
        if event["status"] != "create":
            continue
        container_id = event["id"]
        time = event["time"]
        name = event["Actor"]["Attributes"]["name"]
        try:
            container = client.containers.get(container_id)
            challenge_id = int(container.attrs["Config"]["Env"][0].split("=")[1])
            print(time, container_id, name, challenge_id, flush=True)
        except Exception as e:
            print(e, file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
