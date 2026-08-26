# Development

Before you begin development, please be sure to read the [architecture](./architecture.md) and [deployment](./deployment.md) documentation.

## Quick Development Setup

Clone the branch or pull request you want to develop, then let the deployment helper build and import the NixOS image:

```sh
git clone https://github.com/pwncollege/dojo
cd dojo

BRANCH="master"
git switch "$BRANCH"

TAG="dev-$(printf '%s' "$BRANCH" | tr '/' '-' | tr -c '[:alnum:]' '-')"

./deploy.sh -b -p -c "dojo-$TAG"
```

For a pull request, fetch its head before building:

```sh
git fetch origin pull/NUMBER/head
git switch --detach FETCH_HEAD
```

Start a VSCode tunnel authenticated with your GitHub account:

```sh
docker exec -i "dojo-$TAG" dojo vscode
```

## Testing

Run the test suite against a newly built instance with `./deploy.sh -b -t`, or reuse an already running instance with `./deploy.sh -N -t`.
If you want to recreate the exact(ish) environment of our CI, do:

```console
apt install gh # github CLI
gh auth login # login to your github
gh extension install nektos/gh-act # a github extension to simulate github actions
gh act # run the CI
```

## Adding a config entry

1. Add its allowlisted name and a reasonable default in `dojo/dojo-config`
2. Expose it to the relevant native service in the NixOS modules under `nix/`
3. Load it into a global in `dojo_plugin/config.py`
4. Import it appropriately
