# Common DOJO Errors

## Non-readable build context

```
ERROR: failed to solve: error from sender: open docker: permission denied
```

Some directory in your git repo is not readable.
This can happen if you've used `$PWD/data` as your data volume (this is okay --- `data` is in the `.dockerignore`, so it is not accessed when building) and then moved your `data` dir to, e.g., `data.bak` (which would no longer match the `.dockerignore`, causing the docker daemon to try, and fail, to access it).


## Shared mount woes

In the docker-compose logs:

```
Error response from daemon: path /run/homefs is mounted on /run/homefs but it is not a shared mount
```

This means that your `/data` directory is not a shared mount.
If you are mounting it into the outer docker via `-v`, do:

`-v /host/path:/data:shared`
