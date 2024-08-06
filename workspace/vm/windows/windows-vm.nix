{ callPackage, lib, qemu_test, netcat-openbsd, openssh, stdenv, writeShellScript }:

let
  setup-drive = callPackage ./setup-drive.nix { };
  server-iso = callPackage ./server-iso.nix { };
  virtio-win-drivers = callPackage ./virtio-win-drivers.nix { };

  windows-vm-stage1 = stdenv.mkDerivation {
    name = "windows-vm-stage1";
    src = null;

    # qemu_test only supports host CPU and has a more minimal feature set that allows us
    #  to avoid pulling in the desktop software kitchen sink.
    nativeBuildInputs = [ qemu_test ];

    dontUnpack = true;
    dontConfigure = true;

    buildPhase = ''
      runHook preBuild

      mkdir -p $out
      qemu-img create -f qcow2 $out/windows-base.qcow2 51200M

      # install
      printf "Installing windows and tools...\n"
      qemu-system-x86_64 \
        -name dojo \
        -boot once=d \
        -machine type=pc,accel=kvm \
        -m 4096M \
        -smp "$NIX_BUILD_CORES" \
        -display vnc=:12 \
        -nographic \
        -device virtio-net,netdev=user.0 \
        -netdev user,id=user.0,hostfwd=tcp::5985-:5985,hostfwd=tcp::2222-:22 \
        -serial null \
        -monitor none \
        -chardev socket,id=mon1,host=localhost,port=4444,server=on,wait=off \
        -mon chardev=mon1 \
        -drive "file=${setup-drive},read-only=on,format=raw,if=floppy,index=0" \
        -drive "file=${server-iso},read-only=on,media=cdrom,index=1" \
        -drive "file=${virtio-win-drivers}/share/virtio-drivers.iso,read-only=on,media=cdrom,index=2" \
        -drive "file=$out/windows-base.qcow2,if=virtio,cache=writeback,discard=ignore,format=qcow2,index=3"
    '';

    dontInstall = true;

    # save some time
    dontPatchELF = true;
    dontPatchShebangs = true;

    meta = {
      # unfree software is downloaded during the setup process.
      license = lib.licenses.unfree;
      sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    };
  };
in
stdenv.mkDerivation {
  name = "windows-vm";

  src = lib.cleanSource ./postinst-files;

  # qemu_test only supports host CPU and has a more minimal feature set that allows us
  #  to avoid pulling in the desktop software kitchen sink.
  nativeBuildInputs = [ qemu_test openssh netcat-openbsd ];

  dontUnpack = true;
  dontConfigure = true;

  buildPhase = ''
    runHook preBuild
    mkdir -p $out
    qemu-img create \
      -f qcow2 \
      -o backing_file=${windows-vm-stage1}/windows-base.qcow2 \
      -o backing_fmt=qcow2 \
      $out/windows-base.qcow2 51200M

    # perform initial bootup (in background)
    printf "Performing initial bootup...\n"
    qemu-system-x86_64 \
      -name dojo \
      -boot once=d \
      -machine type=pc,accel=kvm \
      -m 4096M \
      -smp "$NIX_BUILD_CORES" \
      -display vnc=:12 \
      -nographic \
      -device virtio-net,netdev=user.0 \
      -netdev user,id=user.0,hostfwd=tcp::5985-:5985,hostfwd=tcp::2222-:22 \
      -serial null \
      -monitor none \
      -chardev socket,id=mon1,host=localhost,port=4444,server=on,wait=off \
      -mon chardev=mon1,mode=control \
      -drive "file=${setup-drive},read-only=on,format=raw,index=0,if=floppy" \
      -drive "file=${server-iso},read-only=on,media=cdrom,index=1" \
      -drive "file=${virtio-win-drivers}/share/virtio-drivers.iso,read-only=on,media=cdrom,index=2" \
      -drive "file=$out/windows-base.qcow2,if=virtio,cache=writeback,discard=ignore,format=qcow2,index=3" &
    qemu_pid="$!"
    
    # wait for SSH to open
    printf "Waiting for SSH to open..."
    CON="NOPE"
    while [[ $CON != *"SSH"* ]]; do
      CON="$(timeout 10 ${netcat-openbsd}/bin/nc -w10 127.0.0.1 2222 || true)"
    done
    echo "SSH is up! Finalizing..."

    cd $src
    scp -o "StrictHostKeyChecking=no" -P2222 ./post_install.ps1 hacker@127.0.0.1:
    scp -o "StrictHostKeyChecking=no" -P2222 ./startup.ps1 "hacker@127.0.0.1:C:/Program Files/Common Files/"
    scp -o "StrictHostKeyChecking=no" -P2222 ./challenge-proxy.c "hacker@127.0.0.1:C:/Program Files/Common Files/"
    ssh -o "StrictHostKeyChecking=no" -p2222 hacker@127.0.0.1 -- ./post_install.ps1

    # wait for post_install.ps1 to shut the machine down
    sleep 30
    echo "shutting down qemu"
    echo -e '{"execute": "qmp_capabilities"}\n{"execute": "system_powerdown"}' | nc -w 15 localhost 4444
    kill -9 "$qemu_pid" || true

    runHook postBuild
  '';

  dontInstall = true;

  # save some time
  dontPatchELF = true;
  dontPatchShebangs = true;

  meta = {
    # unfree software is downloaded during the setup process.
    license = lib.licenses.unfree;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
