{
  bc,
  bison,
  bun,
  cacert,
  elfutils,
  fetchFromGitHub,
  fetchurl,
  flex,
  gawk,
  gnutar,
  inputs,
  lib,
  nginxMainline,
  nodejs_22,
  openssl,
  pahole,
  patch,
  perl,
  pkgs,
  pkg-config,
  python313,
  pyproject-build-systems,
  pyproject-nix,
  stdenv,
  stdenvNoCC,
  uv2nix,
  xz,
  zlib,
  dojoSource,
}:

let
  pythonWorkspace = uv2nix.lib.workspace.loadWorkspace {
    workspaceRoot = ./ctfd;
  };

  pythonOverlay = pythonWorkspace.mkPyprojectOverlay {
    sourcePreference = "wheel";
  };

  pythonSet =
    (pkgs.callPackage pyproject-nix.build.packages {
      python = python313;
    }).overrideScope
      (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          pythonOverlay
          (final: prev: {
            cmarkgfm = prev.cmarkgfm.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
                final.cffi
                final.pycparser
                final.setuptools
              ];
            });
            flask-script = prev.flask-script.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.setuptools ];
            });
            maxminddb = prev.maxminddb.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.setuptools ];
            });
            sqlalchemy = prev.sqlalchemy.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.setuptools ];
            });
          })
        ]
      );

  pythonRuntime = pythonSet.mkVirtualEnv "dojo-python-runtime" pythonWorkspace.deps.all;

  dojofsPython = python313.withPackages (pythonPackages: [
    pythonPackages.docker
    pythonPackages.pyfuse3
    pythonPackages.requests
    pythonPackages.trio
  ]);

  ctfdSource = stdenvNoCC.mkDerivation {
    pname = "dojo-ctfd";
    version = "3.6.0";
    src = inputs.ctfd;
    nativeBuildInputs = [ patch ];
    patches = [
      "${dojoSource}/ctfd/patches/01-solves-performance.patch"
      "${dojoSource}/ctfd/patches/02-Improve-caching-by-returning-proper-Cache-Control-he.patch"
      "${dojoSource}/ctfd/patches/03-run-id-cache-buster.patch"
    ];
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      cp -a . "$out"
      chmod -R u+w "$out"
      cp ${dojoSource}/ctfd/.coveragerc "$out/.coveragerc"
      rm -rf "$out/CTFd/plugins/dojo_plugin" "$out/CTFd/themes/dojo_theme"
      cp -a ${dojoSource}/dojo_plugin "$out/CTFd/plugins/dojo_plugin"
      cp -a ${dojoSource}/dojo_theme "$out/CTFd/themes/dojo_theme"
      substituteInPlace "$out/docker-entrypoint.sh" \
        --replace-fail "--bind '0.0.0.0:8000'" "--bind '127.0.0.1:8000'"
      runHook postInstall
    '';
  };

  frontendSource = lib.cleanSourceWith {
    src = "${dojoSource}/frontend";
    filter =
      path: type:
      let
        name = baseNameOf path;
      in
      !(lib.elem name [
        ".next"
        "node_modules"
      ]);
  };

  frontendDependencies = stdenvNoCC.mkDerivation {
    pname = "dojo-frontend-dependencies";
    version = "1";
    src = frontendSource;
    nativeBuildInputs = [
      bun
      cacert
      gnutar
      pkgs.zstd
    ];
    dontConfigure = true;
    buildPhase = ''
      runHook preBuild
      export HOME="$TMPDIR"
      bun install --frozen-lockfile --no-progress
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      tar \
        --sort=name \
        --mtime=@1 \
        --owner=0 \
        --group=0 \
        --numeric-owner \
        --zstd \
        -cf "$out/node_modules.tar.zst" \
        node_modules
      runHook postInstall
    '';
    outputHashAlgo = "sha256";
    outputHashMode = "recursive";
    outputHash = "sha256-nvcPrOMK0Fi9rVZbDeqxhvvNFHWnJet2HzQHHC3/ucU=";
  };

  frontend = stdenvNoCC.mkDerivation {
    pname = "dojo-frontend";
    version = "1";
    src = frontendSource;
    nativeBuildInputs = [
      bun
      gnutar
      nodejs_22
      pkgs.zstd
    ];
    dontConfigure = true;
    buildPhase = ''
      runHook preBuild
      tar --zstd -xf ${frontendDependencies}/node_modules.tar.zst
      patchShebangs node_modules/.bin/next node_modules/next/dist/bin/next
      bun run build
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp -a .next/standalone/. "$out/"
      mkdir -p "$out/.next"
      cp -a .next/static "$out/.next/static"
      ln -s /var/cache/dojo-frontend "$out/.next/cache"
      cp -a public "$out/public"
      runHook postInstall
    '';
  };

  hmacSecureLinkModule = {
    name = "hmac-secure-link";
    meta.license = [ lib.licenses.bsd2 ];
    src = fetchFromGitHub {
      owner = "nginx-modules";
      repo = "ngx_http_hmac_secure_link_module";
      rev = "b80defebeafbb77b34431aee8f313908cd7cbeb5";
      hash = "sha256-X33SqgwKj7vcLzSWl1mzKKfZxUVQXr+nyxaRQ+doTzY=";
    };
  };

  nginx = nginxMainline.override {
    modules = [ hmacSecureLinkModule ];
  };

  kataImages = pkgs.fetchzip {
    name = "kata-images-3.32.0";
    url = "https://github.com/kata-containers/kata-containers/releases/download/3.32.0/kata-static-3.32.0-amd64.tar.zst";
    hash = "sha256-ea4/6xjuoiqFebGF+NegGa4B+3Imf/4uULfQbJxqKtc=";
    nativeBuildInputs = [ pkgs.zstd ];
    postFetch = ''
      mv "$out/kata/share/kata-containers" kata-containers
      rm -r "$out"
      mkdir -p "$out/share"
      mv kata-containers "$out/share/kata-containers"
    '';
  };

  kataRuntime = pkgs.kata-runtime.overrideAttrs (old: {
    version = "3.32.0";
    src = fetchFromGitHub {
      owner = "kata-containers";
      repo = "kata-containers";
      rev = "3.32.0";
      hash = "sha256-dnbzjYDKeAp0wFQcO5VK71vkf7ubVK5Lh9R9jjuro28=";
    };
    vendorHash = "sha256-HAWobIcqwHL7jgawpOk1ZNx6vG8NApF5Nn60eZ9Fc1c=";
    dontConfigure = false;
    installPhase = ''
      runHook preInstall
      HOME="$TMPDIR" GOPATH="$TMPDIR/gopath" make ${toString old.makeFlags} install
      ln -s "$out/bin/containerd-shim-kata-v2" "$out/bin/containerd-shim-kata-qemu-v2"
      ln -s "$out/bin/containerd-shim-kata-v2" "$out/bin/containerd-shim-kata-clh-v2"
      sed -i \
        -e "s!$out/share/kata-containers!${kataImages}/share/kata-containers!" \
        -e 's!^virtio_fs_daemon.*!virtio_fs_daemon="${pkgs.virtiofsd}/bin/virtiofsd"!' \
        -e 's!^valid_virtio_fs_daemon_paths.*!valid_virtio_fs_daemon_paths=["${pkgs.virtiofsd}/bin/virtiofsd"]!' \
        "$out/share/defaults/kata-containers/"*.toml
      runHook postInstall
    '';
    passthru = (old.passthru or { }) // {
      kata-images = kataImages;
    };
  });

  kataKernelSource = fetchurl {
    url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.36.tar.xz";
    hash = "sha256-ShaK7S3lqBqt2QuisVOGCpjZm/w0ZRk24X8Y5U8Buow=";
  };

  kataKernel = stdenv.mkDerivation {
    pname = "dojo-kata-kernel";
    version = "6.12.36";
    src = kataRuntime.src;
    nativeBuildInputs = [
      bc
      bison
      pahole
      elfutils
      flex
      gawk
      gnutar
      openssl
      patch
      perl
      pkg-config
      python313
      xz
    ];
    buildInputs = [ zlib ];
    dontConfigure = true;
    buildPhase = ''
      runHook preBuild
      export HOME="$TMPDIR"
      export KBUILD_BUILD_TIMESTAMP="$(date -u -d "@$SOURCE_DATE_EPOCH")"
      export KBUILD_BUILD_USER=dojo
      export KBUILD_BUILD_HOST=nix
      kernel_path="$PWD/kata-linux-6.12.36"
      cp ${kataKernelSource} linux-6.12.36.tar.xz
      sha256sum linux-6.12.36.tar.xz > linux-6.12.36.tar.xz.sha256
      cp ${./kata-kernel.conf} tools/packaging/kernel/configs/fragments/x86_64/dojo.conf
      patchShebangs tools/packaging
      tools/packaging/kernel/build-kernel.sh -v 6.12.36 -k "$kernel_path" setup
      patchShebangs "$kernel_path/scripts/bpf_doc.py"
      tools/packaging/kernel/build-kernel.sh -v 6.12.36 -k "$kernel_path" build
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp kata-linux-6.12.36/vmlinux "$out/vmlinux.container"
      runHook postInstall
    '';
  };

  kata = stdenvNoCC.mkDerivation {
    pname = "dojo-kata-runtime";
    inherit (kataRuntime) version;
    dontUnpack = true;
    installPhase = ''
      mkdir -p "$out/kata/share/defaults/kata-containers"
      ln -s ${kataRuntime}/bin "$out/kata/bin"
      cp ${kataRuntime}/share/defaults/kata-containers/configuration-qemu.toml \
        "$out/kata/share/defaults/kata-containers/configuration.toml"
      substituteInPlace "$out/kata/share/defaults/kata-containers/configuration.toml" \
        --replace-fail 'kernel = "${kataRuntime.kata-images}/share/kata-containers/vmlinux.container"' \
        'kernel = "${kataKernel}/vmlinux.container"'
    '';
  };

  dockerSeccomp = fetchurl {
    url = "https://raw.githubusercontent.com/moby/profiles/3c28324314729dbade8287e868eef6338c42807a/seccomp/default.json";
    hash = "sha256-U2UptmXdCXLDe/tWn11KyKU1kuewB1K8Of8GPKmGTHQ=";
  };

  vscodeCli = stdenvNoCC.mkDerivation {
    pname = "dojo-vscode-cli";
    version = "110a328ea54b42367b803ec53ee0bf52ef26b419";
    src = fetchurl {
      url = "https://vscode.download.prss.microsoft.com/dbazure/download/stable/110a328ea54b42367b803ec53ee0bf52ef26b419/vscode_cli_alpine_x64_cli.tar.gz";
      hash = "sha256-tMuE2RDNdYJ8nvn08C6nvCtrwHsYARFJiXX0NtEKiQE=";
    };
    sourceRoot = ".";
    installPhase = ''
      install -Dm755 code "$out/bin/code"
    '';
  };

  workspaceCli = import "${dojoSource}/workspace/core/dojo-cli.nix" { inherit pkgs; };
in
{
  inherit
    ctfdSource
    dockerSeccomp
    dojofsPython
    frontend
    frontendDependencies
    kata
    nginx
    pythonRuntime
    vscodeCli
    workspaceCli
    ;
}
