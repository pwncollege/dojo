# Development

Before you begin development, please be sure to read the [architecture](./architecture.md) and [deployment](./deployment.md) documentation.

## Quick Development Setup

To quickly set up a development environment, use the following commands, which will build the dojo image and run it in a self-contained container:

```sh
BRANCH="master"  # or PR with "pull/N/head"

TAG="dev-$(printf '%s' "$BRANCH" | tr '/' '-' | tr -c '[:alnum:]' '-')"

docker build --build-arg BUILDKIT_CONTEXT_KEEP_GIT_DIR=1 -t "pwncollege/dojo:$TAG" "https://github.com/pwncollege/dojo.git#$BRANCH"

docker run --privileged --name "dojo-$TAG" -d "pwncollege/dojo:$TAG"
```

Start a VSCode tunnel (authenticated with your GitHub account) to this container using the following command:

```sh
docker exec -i "dojo-$TAG" dojo vscode
```

## Testing

You can run the dojo CI testcases locally using `test/local-tester.sh`.

## Adding a config entry

1. Add it with a reasonable default in `dojo/dojo-init`
2. Propagate it to the relevant containers (typically `ctfd`) in `docker-compose.sh`
3. Load it into a global in `dojo_plugin/config.py`
4. Import it appropriately
