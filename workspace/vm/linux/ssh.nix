{ pkgs }:

let
sshdPatch = pkgs.writeText "sshd_patch.diff" ''
    *** a/etc/ssh/sshd_config
    --- b/etc/ssh/sshd_config
    ***************
    *** 32 ****
    ! #PermitRootLogin prohibit-password
    --- 32 ----
    ! PermitRootLogin yes
    ***************
    *** 57,58 ****
    ! #PasswordAuthentication yes
    ! #PermitEmptyPasswords no
    --- 57,58 ----
    ! PasswordAuthentication yes
    ! PermitEmptyPasswords yes
  '';
in
pkgs.openssh.overrideAttrs (oldAttrs: {
    # Disable checks which error
    doCheck = false;

    postInstall = (oldAttrs.postInstall or "") + ''
      patch -p1 -d $out < ${sshdPatch}
    '';
})
