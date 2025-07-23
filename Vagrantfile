Vagrant.configure("2") do |config|
  config.vm.box = "debian/bookworm64"
  config.vm.define "dojo"
  config.vm.provider "libvirt" do |v|
    v.memory = 4096
    v.cpus = 4
    v.storage :file,
      #:path => '/data',
      #:device => 'vdb',	# automatically chosen if unspecified!
      :size => '256G',
      :type => 'qcow2'
  end
  config.vm.provision "shell", inline: <<-SHELL
    apt-get update
    apt-get upgrade -y
    apt-get dist-upgrade -y
    apt-get install -y curl
    curl -fsSL https://get.docker.com | /bin/sh

    mkfs.ext4 /dev/vdb
    mkdir /data
    mount /dev/vdb /data

    modprobe br_netfilter

    docker build -t dojo /vagrant
    docker run \
        --name dojo \
        --privileged \
        --detach \
        --rm \
        -v "/data:/data:shared" \
        -p 2222:22 -p 80:80 -p 443:443 \
        dojo
    docker exec dojo dojo wait
  SHELL
end
