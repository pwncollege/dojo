# Development

Before you begin development, please be sure to read the [architecture](./architecture.md) and [deployment](./deployment.md) documentation.

## Testing

You can run the dojo CI testcases locally using `test/local-tester.sh`.

## Adding a config entry

1. Add it with a reasonable default in `dojo/dojo-init`
2. Propagate it to the relevant containers (typically `ctfd`) in `docker-compose.sh`
3. Load it into a global in `dojo_plugin/config.py`
4. Import it appropriately
