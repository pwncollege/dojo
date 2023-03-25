# pwn.college

Deploy a pwn.college instance!

## Details

The pwn.college infrastructure is based on [CTFd](https://github.com/CTFd/CTFd).
CTFd provides for a concept of users, challenges, and users solving those challenges by submitting flags.
From there, this repository provides infrastructure which expands upon these capabilities.

The pwn.college infrastructure allows users the ability to "start" challenges, which spins up a private docker container for that user.
This docker container will have the associated challenge binary injected into the container as root-suid, as well as the flag to be submitted as readable only by the the root user.
Users may enter this container via `ssh`, by supplying a public ssh key in their profile settings, or via vscode in the browser ([code-server](https://github.com/cdr/code-server)).
The associated challenge binary may be either global, which means all users will get the same binary, or instanced, which means that different users will receive different variants of the same challenge.

## Setup

Clone the repository:
```sh
git clone https://github.com/pwncollege/dojo /opt/dojo
```

The only dependency to run the infrastructure is docker, which can be installed with:
```sh
curl -fsSL https://get.docker.com | /bin/sh
```

Now, build the container:
```sh
docker build -t pwncollege/dojo .
```

Finally, run the infrastructure which will be hosted on domain `my.domain.college` with:
```sh
docker run --privileged -d -v /opt/dojo:/opt/pwn.college --hostname my.domain.college -p 22:22 -p 80:80 -p 443:443 pwncollege/dojo
```

**TODO: VERIFY ACCURACY** If not specified, `<DOMAIN>` will default to `localhost.pwn.college`, which means you can access the infrastructure through this domain.

It will take some time to initialize everything and build the challenge docker image.
You can check on your container (and the progress of the initial build) with:
```sh
docker exec YOUR_CONTAINER_NAME dojo logs
```

Once things are setup, you should be able to access the dojo and login with the admin credentials found in `data/initial_credentials`
You can change these admin credentials in the admin panel.

## Customization

*All* dojo data will be stored in the `./data` directory.

You may customize the available global dojos by creating `.yml` files within the `./data/dojos` directory.

You may customize the available challenges by setting up challenges files within the `./data/challenges` directory.

Examples for the structure of both of these are available within [data_example](./data_example). By default, upon initializing the dojo infrastructure for the first time, if customized `./data/dojos` and `./data/challenges` are not supplied, these files will be automatically loaded.
