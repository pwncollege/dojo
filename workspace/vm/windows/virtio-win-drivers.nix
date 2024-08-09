{ lib, libisoburn, fetchurl, stdenv }:

stdenv.mkDerivation rec {
  pname = "virtio-win-drivers";
  version = "0.1.248-1";

  src = fetchurl {
    # find latest version:
    # curl -sI 'https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/latest-virtio/virtio-win.iso' | grep -Fi 'Location: '
    url = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-${version}/virtio-win.iso";
    hash = "sha256-1bVznPKX8FONJj4wZ41aCbukcKfGvL2N/3TkQVPxZUk=";
  };

  nativeBuildInputs = [
    libisoburn
  ];

  unpackPhase = ''
    runHook preUnpack

    cd "$(mktemp -d)"
    # must create a subdirectory with this exact name
    mkdir virtio-win
    xorriso -report_about SORRY -osirrox on -indev $src -extract / ./virtio-win
    # possible TODO: keep only the specific drivers we need to save space

    runHook postUnpack
  '';

  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/
    # repackage the ISO in the format windows expects
    xorriso \
      -as genisoimage -rock -joliet -volid VIRTIO \
      -output $out/share/virtio-drivers.iso \
      ./

    runHook postInstall
  '';

  # save some time
  dontPatchELF = true;
  dontPatchShebangs = true;

  meta = {
    description = "Windows paravirtualized drivers for QEMU/KVM, based on the virtIO standard";
    homePage = "https://github.com/virtio-win/kvm-guest-drivers-windows";
    downloadPage = "https://github.com/virtio-win/virtio-win-pkg-scripts/blob/master/README.md";
    license = lib.licenses.bsd3;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
