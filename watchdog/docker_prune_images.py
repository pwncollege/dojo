#!/usr/local/bin/python3

import argparse
from contextlib import closing
import fcntl
import json
import logging
from pathlib import Path
import re

import docker
import psycopg2


logger = logging.getLogger(__name__)
LOCK_PATH = "/run/docker-image-prune.lock"
LEGACY_IMAGE = "pwncollege/challenge-legacy"


def normalize_reference(reference):
    if not isinstance(reference, str) or not reference or any(c.isspace() for c in reference):
        raise ValueError("Invalid image reference")
    if re.fullmatch(r"(?:sha256:)?[0-9a-f]{12,64}", reference):
        return reference if reference.startswith("sha256:") else "sha256:" + reference
    name, separator, digest = reference.partition("@")
    repository, tag = docker.utils.parse_repository_tag(name)
    first, slash, remainder = repository.partition("/")
    if slash and ("." in first or ":" in first or first == "localhost"):
        registry, repository = first.lower(), remainder
    else:
        registry = "docker.io"
    if registry in {"docker.io", "index.docker.io", "registry-1.docker.io"}:
        registry = "docker.io"
        if "/" not in repository:
            repository = "library/" + repository
    return registry + "/" + repository + ("@" + digest if separator else ":" + (tag or "latest"))


def challenge_references(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT data->'image' FROM dojo_challenges")
        rows = cursor.fetchall()
    if not rows:
        raise ValueError("Challenge image inventory is empty")
    references = {normalize_reference(LEGACY_IMAGE)}
    for (image,) in rows:
        if image is not None and image != "":
            if not isinstance(image, str):
                raise ValueError("Invalid challenge image")
            if not image.startswith("mac:"):
                references.add(normalize_reference(image))
    return references


def container_references(client):
    containers = client.api.containers(all=True)
    return ({container["ImageID"] for container in containers},
            {normalize_reference(container["Image"]) for container in containers})


def protected(image, references, used_ids):
    labels = image.get("Labels") or image.get("Config", {}).get("Labels") or {}
    aliases = {normalize_reference(ref)
               for ref in (image.get("RepoTags") or []) + (image.get("RepoDigests") or [])
               if ref not in ("<none>:<none>", "<none>@<none>")}
    return (image["Id"] in used_ids
            or any(image["Id"].startswith(ref) for ref in references if ref.startswith("sha256:"))
            or bool(aliases & references)
            or any(key in labels for key in ("com.docker.compose.project",
                                             "com.docker.compose.service", "pwn.college.gc.keep")))


def collect_images(client, read_references, *, apply=False):
    images = client.api.images(all=True)
    used_ids, used_references = container_references(client)
    references = read_references() | used_references
    candidates = [image for image in images if not protected(image, references, used_ids)]
    node = client.api.base_url
    logger.info("%s: %d images, %d candidates", node, len(images), len(candidates))
    for candidate in candidates:
        tags = [tag for tag in candidate.get("RepoTags") or [] if tag != "<none>:<none>"]
        for target in tags or [candidate["Id"]]:
            used_ids, used_references = container_references(client)
            references = read_references() | used_references
            try:
                current = client.api.inspect_image(target)
                if current["Id"] != candidate["Id"] or protected(current, references, used_ids):
                    logger.info("%s: skipping changed or protected image %s", node, target)
                    continue
                if apply:
                    client.api.remove_image(target, force=False, noprune=True)
                logger.info("%s: %s %s (%s)", node, "removed" if apply else "would remove", target, current["Id"])
            except docker.errors.APIError as error:
                if error.status_code not in (404, 409):
                    raise
                logger.info("%s: skipping %s: %s", node, target, error)
    logger.info("%s: complete", node)


def main():
    parser = argparse.ArgumentParser(description="Collect unused images not referenced by challenges")
    parser.add_argument("--apply", action="store_true", help="Remove images (default: dry run)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [image-gc] %(levelname)s %(message)s")
    with open(LOCK_PATH, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("Another image cleanup is running; skipping")
            return 0
        nodes = json.loads(Path("/var/workspace_nodes.json").read_text())
        urls = [f"tcp://192.168.42.{int(node) + 1}:2375" for node in nodes] or ["unix:///var/run/docker.sock"]
        with closing(psycopg2.connect(connect_timeout=10, options="-c default_transaction_read_only=on -c statement_timeout=10000")) as connection:
            connection.autocommit = True
            failed = False
            for url in urls:
                try:
                    with closing(docker.DockerClient(base_url=url, timeout=60)) as client:
                        collect_images(client, lambda: challenge_references(connection), apply=args.apply)
                except Exception:
                    logger.exception("%s: stopping node cleanup", url)
                    failed = True
            return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
