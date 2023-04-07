#!/bin/sh

DOJO_DIR=/opt/pwn.college

>> $DOJO_DIR/data/config.env

> $DOJO_DIR/data/.config.env
define () {
    name="$1"
    default="$2"
    re="^${name}=\K.*"
    current="$(env | grep -oP ${re})"
    defined="$(grep -oP ${re} $DOJO_DIR/data/config.env)"
    value="${current:-${defined:-$default}}"
    echo "${name}=${value}" >> $DOJO_DIR/data/.config.env
}
define DOJO_HOST localhost.pwn.college
define DOJO_ENV production
define DOJO_CHALLENGE challenge
define SECRET_KEY $(openssl rand -hex 16)
define DOCKER_PSLR $(openssl rand -hex 16)
define DISCORD_CLIENT_ID
define DISCORD_CLIENT_SECRET
define DISCORD_BOT_TOKEN
define DISCORD_GUILD_ID
mv $DOJO_DIR/data/.config.env $DOJO_DIR/data/config.env
. $DOJO_DIR/data/config.env

if [ ! "$(ls -A $DOJO_DIR/data/dojos $DOJO_DIR/data/challenges)" ]; then
    echo "Warning: initializing dojo for the first time and no data included, auto populating with data_example"
    cp -r $DOJO_DIR/data_example/* $DOJO_DIR/data
fi

if [ ! -f $DOJO_DIR/data/homes/homefs ]; then
    echo "[+] Creating user home structure."
    mkdir -p $DOJO_DIR/data/homes
    mkdir -p $DOJO_DIR/data/homes/data
    mkdir -p $DOJO_DIR/data/homes/nosuid
    dd if=/dev/zero of=$DOJO_DIR/data/homes/homefs bs=1M count=0 seek=1000
    mkfs.ext4 -O ^has_journal $DOJO_DIR/data/homes/homefs
    mount $DOJO_DIR/data/homes/homefs -o X-mount.mkdir $DOJO_DIR/data/homes/homefs_mount
    rm -rf $DOJO_DIR/data/homes/homefs_mount/lost+found/
    cp -a /etc/skel/. $DOJO_DIR/data/homes/homefs_mount
    chown -R hacker:hacker $DOJO_DIR/data/homes/homefs_mount
    umount $DOJO_DIR/data/homes/homefs_mount
    rm -rf $DOJO_DIR/data/homes/homefs_mount
fi

echo "[+] Creating loopback devices for home mounts. This might take a while."
for i in $(seq 1 4096); do
    if [ -e /dev/loop$i ]; then
        continue
    fi
    mknod /dev/loop$i b 7 $i
    chown --reference=/dev/loop0 /dev/loop$i
    chmod --reference=/dev/loop0 /dev/loop$i
done

if [ ! -d $DOJO_DIR/data/ssh_host_keys ]; then
    mkdir -p $DOJO_DIR/data/ssh_host_keys
    rm /etc/ssh/ssh_host_*_key*
    ssh-keygen -A -m PEM
    for key in $(ls /etc/ssh/ssh_host_*_key*); do
        cp -a $key $DOJO_DIR/data/ssh_host_keys
    done
fi
ssh-keyscan github.com > $DOJO_DIR/data/ssh_host_keys/ssh_known_hosts
for file in $(ls $DOJO_DIR/data/ssh_host_keys/*); do
    cp -a $file /etc/ssh
done

mkdir -p $DOJO_DIR/data/dms/config \
         $DOJO_DIR/data/dms/config/opendkim \
         $DOJO_DIR/data/dms/mail-data \
         $DOJO_DIR/data/dms/mail-state \
         $DOJO_DIR/data/dms/mail-logs
echo "hacker@${DOJO_HOST}|{SHA512-CRYPT}$(openssl passwd -6 hacker)" > $DOJO_DIR/data/dms/config/postfix-accounts.cf
echo "mail._domainkey.${DOJO_HOST} ${DOJO_HOST}:mail:/etc/opendkim/keys/${DOJO_HOST}/mail.private" > $DOJO_DIR/data/dms/config/opendkim/KeyTable
echo "*@${DOJO_HOST} mail._domainkey.${DOJO_HOST}" > $DOJO_DIR/data/dms/config/opendkim/SigningTable
echo -e "127.0.0.1\nlocalhost" > $DOJO_DIR/data/dms/config/opendkim/TrustedHosts
mkdir -p "$DOJO_DIR/data/dms/config/opendkim/keys/${DOJO_HOST}"
cp $DOJO_DIR/data/ssh_host_keys/ssh_host_rsa_key "$DOJO_DIR/data/dms/config/opendkim/keys/${DOJO_HOST}/mail.private"

DKIM_P=$(openssl rsa -in "$DOJO_DIR/data/dms/config/opendkim/keys/${DOJO_HOST}/mail.private" -pubout -outform dem | base64 -w0)

cat <<EOF > $DOJO_DIR/data/dns
    @                  IN    MX     10 ${DOJO_HOST}.
    @                  IN    TXT    "v=spf1 mx ~all"
    _dmarc             IN    TXT    "v=DMARC1; p=none; rua=mailto:dmarc.report@${DOJO_HOST}; ruf=mailto:dmarc.report@${DOJO_HOST}; sp=none; ri=86400"
    mail._domainkey    IN    TXT    "v=DKIM1; h=sha256; k=rsa; p=${DKIM_P}"
EOF

mkdir -p $DOJO_DIR/data/logging

sysctl -w kernel.pty.max=1048576
echo core > /proc/sys/kernel/core_pattern

iptables -N DOCKER-USER
iptables -I DOCKER-USER -i user_firewall -j DROP
for host in $(cat $DOJO_DIR/user_firewall.allowed); do
    iptables -I DOCKER-USER -i user_firewall -d $(host $host | awk '{print $NF; exit}') -j ACCEPT
done
