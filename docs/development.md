# Development

Before you begin development, please be sure to read the [architecture](./architecture.md) and [deployment](./deployment.md) documentation.

## Quick Development Setup

To quickly set up a development environment, you can use the provided [dev/setup.sh](../dev/setup.sh) script:

```sh
curl -fsSL https://raw.githubusercontent.com/pwncollege/dojo/master/dev/setup.sh | /bin/sh
```

You may optionally specify a specific branch or pull request number to checkout:

```sh
BRANCH="master"  # or PR number
curl -fsSL https://raw.githubusercontent.com/pwncollege/dojo/master/dev/setup.sh | /bin/sh -s -- "$BRANCH"
```

## Testing

You can run the dojo CI testcases locally using `test/local-tester.sh`.

## Adding a config entry

1. Add it with a reasonable default in `dojo/dojo-init`
2. Propagate it to the relevant containers (typically `ctfd`) in `docker-compose.sh`
3. Load it into a global in `dojo_plugin/config.py`
4. Import it appropriately
