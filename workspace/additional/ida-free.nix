{ pkgs }:

pkgs.stdenv.mkDerivation rec {
  pname = "ida-free";
  version = "8.4.240320";

  src = pkgs.fetchurl {
    url = "https://web.archive.org/web/20240330140328/https://out7.hex-rays.com/files/idafree84_linux.run";
    hash = "sha256-StjJDl3DIset+6bt1bAS9Pf2jMOkE0WFr0dKOJ0C5vE=";
  };

  icon = pkgs.fetchurl {
    url = "https://web.archive.org/web/20221105181231if_/https://hex-rays.com/products/ida/news/8_1/images/icon_free.png";
    hash = "sha256-widkv2VGh+eOauUK/6Sz/e2auCNFAsc8n9z0fdrSnW0=";
  };

  desktopItem = pkgs.makeDesktopItem {
    name = "ida-free";
    exec = "ida64";
    icon = icon;
    comment = meta.description;
    desktopName = "IDA Free";
    genericName = "Interactive Disassembler";
    categories = [ "Development" ];
    startupWMClass = "IDA";
  };

  desktopItems = [ desktopItem ];

  nativeBuildInputs = with pkgs; [
    makeWrapper
    copyDesktopItems
    autoPatchelfHook
    libsForQt5.wrapQtAppsHook
  ];

  dontUnpack = true;

  runtimeDependencies = with pkgs; [
    cairo
    dbus
    fontconfig
    freetype
    glib
    gtk3
    libdrm
    libGL
    libkrb5
    libsecret
    libsForQt5.qtbase
    libunwind
    libxkbcommon
    openssl
    stdenv.cc.cc
    libice
    libsm
    libx11
    libxau
    libxcb
    libxext
    libxi
    libxrender
    libxcb-image
    libxcb-keysyms
    libxcb-render-util
    libxcb-wm
    zlib
  ];
  buildInputs = runtimeDependencies;

  dontWrapQtApps = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/bin $out/lib $out/opt
    IDADIR=$out/opt

    $(cat $NIX_CC/nix-support/dynamic-linker) $src \
      --mode unattended --prefix $IDADIR --installpassword ""

    cp $IDADIR/libida64.so $out/lib
    addAutoPatchelfSearchPath $IDADIR

    for bb in ida64 assistant; do
      wrapProgram $IDADIR/$bb \
        --prefix QT_PLUGIN_PATH : $IDADIR/plugins/platforms
      ln -s $IDADIR/$bb $out/bin/$bb
    done

    patchelf --add-needed libcrypto.so $IDADIR/libida64.so

    runHook postInstall
  '';

  meta = with pkgs.lib; {
    description = "Freeware version of the world's smartest and most feature-full disassembler";
    homepage = "https://hex-rays.com/ida-free/";
    changelog = "https://hex-rays.com/products/ida/news/";
    license = licenses.unfree;
    mainProgram = "ida64";
    platforms = [ "x86_64-linux" ];
    sourceProvenance = with sourceTypes; [ binaryNativeCode ];
  };
}
