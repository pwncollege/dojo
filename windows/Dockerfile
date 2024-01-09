FROM ubuntu:20.04 AS full

RUN echo 'APT::Install-Recommends 0;' >> /etc/apt/apt.conf.d/01norecommends \
  && echo 'APT::Install-Suggests 0;' >> /etc/apt/apt.conf.d/01norecommends \
  && apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates apt-transport-https curl \
    xorriso mtools dosfstools qemu-utils qemu-kvm python3 openssh-client \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# IDA Freeware: only permissible for free and open deployments of the dojo!
ARG INSTALL_IDA=False

# we create a floppy disk that will hold our Autounattend.xml in the root which will
#  allow windows install to proceed automatically.
# We require privileges to create a loop device
COPY ./Autounattend.xml ./setup.ps1 ./startup.ps1 ./sshd_config ./
COPY ./challenge-proxy ./challenge-proxy
RUN sed -i 's/{INSTALLIDA}/'"$INSTALL_IDA"'/g' ./setup.ps1 \
  && touch ./practice-mode-enabled \
  && mkfs.fat -F 12 -C ./floppy.img 1440 \
  && mcopy -si ./floppy.img \
    ./Autounattend.xml ./setup.ps1 ./startup.ps1 ./practice-mode-enabled ./sshd_config ./challenge-proxy/ :: \
  && rm -rf ./Autounattend.xml ./setup.ps1 ./startup.ps1 ./practice-mode-enabled ./sshd_config ./challenge-proxy/

VOLUME /app/build

COPY ./shutdown.py .
# we have to repackage the ISO file into the correct format for windows to accept it
# we create a virtio-win directory in the root of the ISO here. This isn't *strictly*
#  necessary but it has to correspond with the paths in the Autounattend.xml
# careful... if the drivers can't load for some reason, install will fail with the
#  cryptic error "Failed to applay DriveConfiguration". This is because the drivers
#  are required to write to the qcow2 image. 
CMD \
  ( [ -f ./build/virtio-win-processed.iso ] || ( \
    echo "Building virtio drivers disk" \
    && curl -Lo virtio-win-raw.iso \
      'https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/latest-virtio/virtio-win.iso' \
    && WORKDIR="$(mktemp -d --suffix=.img-extract)" \
    && EXTRACT_DIR="$WORKDIR/virtio-win" \
    && mkdir -p "$EXTRACT_DIR" \
    && xorriso -report_about SORRY -osirrox on -indev ./virtio-win-raw.iso -extract / "$EXTRACT_DIR" \
    && rm ./virtio-win-raw.iso \
    && xorriso \
      -as genisoimage -rock -joliet -volid VIRTIO \
      -output ./build/virtio-win-processed.iso \
      "$WORKDIR" \
    && rm -rf "$WORKDIR" virtio-win-raw.iso \
  ) ) \
  && ( [ -f ./build/server-2022.iso ] || ( \
    echo "Downloading Windows Server ISO" \
    && curl -Lo ./build/server-2022.iso \
      'https://software-static.download.prss.microsoft.com/sg/download/888969d5-f34g-4e03-ac9d-1f9786c66749/SERVER_EVAL_x64FRE_en-us.iso' \
  ) ) \
  && ( [ -f ./build/image-stage1-complete ] || ( \
    echo "Creating VM image" \
    && rm -rf ./build/clean.qcow2 ./build/image-built \
    && qemu-img create -f qcow2 ./build/clean.qcow2 51200M \
    && echo "Installing and configuring windows (this will take a while)" \
    && qemu-system-x86_64 \
      -name dojo \
      -boot once=d \
      -machine type=pc,accel=kvm \
      -m 4096M \
      -smp "$(nproc)" \
      -display vnc=:12 \
      -nographic \
      -device virtio-net,netdev=user.0 \
      -netdev user,id=user.0,hostfwd=tcp::5985-:5985,hostfwd=tcp::2222-:22 \
      -serial null \
      `#-monitor unix:./build/monitor.sock,server,nowait` \
      -drive file=./floppy.img,format=raw,index=0,if=floppy \
      -drive "file=./build/server-2022.iso,media=cdrom" \
      -drive "file=./build/virtio-win-processed.iso,media=cdrom" \
      -drive file=./build/clean.qcow2,if=virtio,cache=writeback,discard=ignore,format=qcow2 \
    && rm -rf ./build/monitor.sock \
    && touch ./build/image-stage1-complete \
  ) ) \
  && ( [ -f ./build/image-built ] || ( \
    echo "Performing initial bootup" \
    && ( \
      qemu-system-x86_64 \
        -name dojo \
        -boot once=d \
        -machine type=pc,accel=kvm \
        -m 4096M \
        -smp "$(nproc)" \
        -display vnc=:12 \
        -nographic \
        -device virtio-net,netdev=user.0 \
        -netdev user,id=user.0,hostfwd=tcp::5985-:5985,hostfwd=tcp::2222-:22 \
        -serial null \
        `#-monitor unix:./build/monitor.sock,server,nowait` \
        -drive file=./floppy.img,format=raw,index=0,if=floppy \
        -drive "file=./build/server-2022.iso,media=cdrom" \
        -drive "file=./build/virtio-win-processed.iso,media=cdrom" \
        -drive file=./build/clean.qcow2,if=virtio,cache=writeback,discard=ignore,format=qcow2 \
      & python3 ./shutdown.py \
    ) && rm -f ./build/monitor.sock \
    && touch ./build/image-built \
    && echo "Windows image built" \
  ) )

FROM ubuntu:20.04 AS none

CMD true
