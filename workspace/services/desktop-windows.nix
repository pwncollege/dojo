{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  # Revert https://github.com/novnc/noVNC/pull/1672
  reconnectPatch = pkgs.writeText "reconnect_patch.diff" ''
    --- a/share/webapps/novnc/app/ui.js
    +++ b/share/webapps/novnc/app/ui.js
    @@ -1,3 +1,3 @@
    -        if (UI.getSetting('reconnect', false) === true && !UI.inhibitReconnect) {
    +        else if (UI.getSetting('reconnect', false) === true && !UI.inhibitReconnect) {
  '';
  novnc = pkgs.novnc.overrideAttrs (oldAttrs: {
    postInstall = (oldAttrs.postInstall or "") + ''
      patch -p1 -d $out < ${reconnectPatch}
    '';
  });
in
pkgs.writeScriptBin "dojo-desktop-windows" ''
  #!${pkgs.bash}/bin/bash

  until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

  mkdir -p /run/dojo/desktop-windows-service

  ${service}/bin/service start desktop-windows-service/novnc \
    ${novnc}/bin/novnc \
      --vnc localhost:5912 \
      --listen 6082

  until [ -e /tmp/.X11-unix/X0 ]; do sleep 0.1; done
  until ${pkgs.curl}/bin/curl -s localhost:6081 >/dev/null; do sleep 0.1; done
''
