# pwn-college

This repository has the artifacts necessary for deploying a pwn.college instance.

## Setup

```bash
docker build -t pwncollege_challenge containers/pwncollege_challenge

cp -r CTFd-pwn-college-plugin CTFd/CTFd/plugins

docker-compose up -d

docker run --detach --name nginx-proxy --publish 80:80 --publish 443:443 --volume /etc/nginx/certs --volume conf/nginx/vhost.d:/etc/nginx/vhost.d --volume /usr/share/nginx/html --volume /var/run/docker.sock:/tmp/docker.sock:ro jwilder/nginx-proxy

docker run --detach --name nginx-proxy-letsencrypt --volumes-from nginx-proxy --volume /var/run/docker.sock:/var/run/docker.sock:ro --env "DEFAULT_EMAIL=example@example.com" jrcs/letsencrypt-nginx-proxy-companion

docker network connect ctfd_default nginx-proxy
```
It may be something other than ctfd_default, depending on instance.

For container access (/etc/ssh/sshd_config):
```
Match User ctf
      AuthorizedKeysCommand /opt/pwn-college/auth.py ctfd_db_1 ctf
      AuthorizedKeysCommandUser root
      X11Forwarding no
      AllowTcpForwarding no
```
It may be something other than ctfd_db_1, depending on instance.
It may be something other than ctf, depending on instance.

Persistent mounts (in /opt/pwn-college/persistent):
```bash
sudo su ubuntu
cp -r data/0 data/$i
mkdir data-nosuid/$i
sudo mount --bind data/$i data-nosuid/$i
sudo mount -o remount,nosuid data-nosuid/$i
```

## Global Resources

```sh
sysctl -w kernel.pty.max=1048576
```
