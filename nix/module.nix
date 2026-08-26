{
  config,
  dojoPackages,
  dojoSource,
  lib,
  pkgs,
  ...
}:

let
  dojoConfigNames = [
    "AWS_ACCESS_KEY_ID"
    "AWS_DEFAULT_REGION"
    "AWS_SECRET_ACCESS_KEY"
    "BACKUP_AES_KEY_FILE"
    "CORS_ORIGINS"
    "DB_HOST"
    "DB_NAME"
    "DB_PASS"
    "DB_USER"
    "DISCORD_BOT_TOKEN"
    "DISCORD_CLIENT_ID"
    "DISCORD_CLIENT_SECRET"
    "DISCORD_GUILD_ID"
    "DOCKER_TOKEN"
    "DOCKER_USERNAME"
    "DOJO_ENV"
    "DOJO_HOST"
    "DOJO_OFFLINE"
    "DOJO_SSH_SERVICE_KEY"
    "DOJO_WORKSPACE"
    "ENABLE_SPLUNK"
    "INTERNET_FOR_ALL"
    "MAC_HOSTNAME"
    "MAC_USERNAME"
    "MAIL_ADDRESS"
    "MAIL_PASSWORD"
    "MAIL_PORT"
    "MAIL_SERVER"
    "MAIL_USERNAME"
    "NIX_GARBAGE_COLLECT"
    "S3_BACKUP_BUCKET"
    "SECRET_KEY"
    "STORAGE_HOST"
    "WORKSPACE_HOST"
    "WORKSPACE_KEY"
    "WORKSPACE_NODE"
    "WORKSPACE_SECRET"
  ];

  inherit (dojoPackages)
    ctfdSource
    dockerSeccomp
    dojofsPython
    frontend
    kata
    nginx
    pythonRuntime
    vscodeCli
    workspaceCli
    ;

  dojoTools = pkgs.runCommand "dojo-tools" { } ''
    mkdir -p "$out/bin"
    for tool in ${dojoSource}/dojo/*; do
      if [ -f "$tool" ]; then
        install -m755 "$tool" "$out/bin/$(basename "$tool")"
      fi
    done
    patchShebangs "$out/bin"
  '';

  dojoTool = name: pkgs.writeShellScriptBin name (builtins.readFile "${dojoSource}/dojo/${name}");
  dojoCommand = dojoTool "dojo";
  dojoCertificatesTool = dojoTool "dojo-certificates";
  dojoConfigTool = dojoTool "dojo-config";
  dojoDockerMigrateTool = dojoTool "dojo-docker-migrate";
  dojoNetworkTool = dojoTool "dojo-network";
  dojoNginxConfigTool = dojoTool "dojo-nginx-config";
  dojoNodeTool = dojoTool "dojo-node";
  dojoSplunkInstallTool = dojoTool "dojo-splunk-install";
  dojoStorageTool = dojoTool "dojo-storage";
  dojoStoragePermissionsTool = dojoTool "dojo-storage-permissions";
  dojoWorkspaceBuildTool = dojoTool "dojo-workspace-build";
  dojoUserFirewall = pkgs.writeText "dojo-user-firewall.allowed" (
    builtins.readFile "${dojoSource}/user_firewall.allowed"
  );

  writeDojoShellApplication =
    arguments:
    pkgs.writeShellApplication (
      arguments
      // {
        excludeShellChecks = (arguments.excludeShellChecks or [ ]) ++ [ "SC1091" ];
      }
    );

  ctfdRuntimeSource = "/run/dojo/ctfd";
  ctfdLiveSourcePaths = [
    "-/opt/pwn.college/dojo_plugin"
    "-/opt/pwn.college/dojo_theme"
  ];

  dojoCtfdSource = writeDojoShellApplication {
    name = "dojo-ctfd-source";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      runtime_link=${ctfdRuntimeSource}
      runtime_source="$(mktemp -d /run/dojo/ctfd-source.XXXXXX)"
      temporary_link="$runtime_source.link"
      trap 'rm -rf "$runtime_source" "$temporary_link"' EXIT
      chmod 755 "$runtime_source"
      cp --archive --symbolic-link ${ctfdSource}/. "$runtime_source"

      plugin_source=${ctfdSource}/CTFd/plugins/dojo_plugin
      if [ -f /opt/pwn.college/dojo_plugin/__init__.py ] \
        && [ -f /opt/pwn.college/dojo_plugin/config.py ] \
        && [ -d /opt/pwn.college/dojo_plugin/api ] \
        && [ -d /opt/pwn.college/dojo_plugin/pages ]; then
        plugin_source=/opt/pwn.college/dojo_plugin
      fi
      theme_source=${ctfdSource}/CTFd/themes/dojo_theme
      if [ -d /opt/pwn.college/dojo_theme/static ] \
        && [ -f /opt/pwn.college/dojo_theme/templates/base.html ]; then
        theme_source=/opt/pwn.college/dojo_theme
      fi

      chmod u+w "$runtime_source/CTFd/plugins" "$runtime_source/CTFd/themes"
      rm -rf "$runtime_source/CTFd/plugins/dojo_plugin" "$runtime_source/CTFd/themes/dojo_theme"
      ln -s "$plugin_source" "$runtime_source/CTFd/plugins/dojo_plugin"
      ln -s "$theme_source" "$runtime_source/CTFd/themes/dojo_theme"

      if [ -d "$runtime_link" ] && [ ! -L "$runtime_link" ]; then
        rm -rf "$runtime_link"
      fi
      ln -s "$runtime_source" "$temporary_link"
      mv -Tf "$temporary_link" "$runtime_link"
      trap - EXIT
    '';
  };

  dojoRole = writeDojoShellApplication {
    name = "dojo-role";
    runtimeInputs = [ pkgs.jq ];
    text = ''
      . /data/config.env
      node_count="$(${pkgs.jq}/bin/jq 'length' /data/workspace_nodes.json 2>/dev/null || echo 0)"
      case "$1" in
        main) [ "$WORKSPACE_NODE" -eq 0 ] ;;
        local-database) [ "$WORKSPACE_NODE" -eq 0 ] && [ "$DB_HOST" = /run/postgresql ] ;;
        worker) [ "$WORKSPACE_NODE" -gt 0 ] ;;
        workspace) [ "$WORKSPACE_NODE" -gt 0 ] || [ "$node_count" -eq 0 ] ;;
        clustered-main) [ "$WORKSPACE_NODE" -eq 0 ] && [ "$node_count" -gt 0 ] ;;
        splunk) [ "$WORKSPACE_NODE" -eq 0 ] && [ "$ENABLE_SPLUNK" = true ] ;;
        splunk-client) [ "$ENABLE_SPLUNK" = true ] ;;
        cloud-backup) [ "$WORKSPACE_NODE" -eq 0 ] && [ -n "$BACKUP_AES_KEY_FILE" ] && [ -n "$S3_BACKUP_BUCKET" ] ;;
        *) exit 2 ;;
      esac
    '';
  };

  dojoFlask = writeDojoShellApplication {
    name = "dojo-flask";
    runtimeInputs = [
      pkgs.openssl
      pkgs.git
      pkgs.openssh
      pythonRuntime
    ];
    text = ''
      . /run/dojo/ctfd.env
      encoded_user="$(${pythonRuntime}/bin/python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_USER")"
      encoded_pass="$(${pythonRuntime}/bin/python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_PASS")"
      encoded_name="$(${pythonRuntime}/bin/python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_NAME")"
      export DISCORD_BOT_TOKEN DISCORD_CLIENT_ID DISCORD_CLIENT_SECRET DISCORD_GUILD_ID
      export DOCKER_TOKEN DOCKER_USERNAME DOJO_ENV DOJO_HOST DOJO_SSH_SERVICE_KEY
      export INTERNET_FOR_ALL MAC_HOSTNAME MAC_USERNAME
      export MAIL_ADDRESS MAIL_PASSWORD MAIL_PORT MAIL_SERVER MAIL_USERNAME
      export SECRET_KEY WORKSPACE_HOST WORKSPACE_SECRET
      export DATABASE_URL="postgresql+psycopg2://$encoded_user:$encoded_pass@127.0.0.1:6432/$encoded_name"
      export REDIS_URL="redis://127.0.0.1:6379"
      export HOST_DATA_PATH=/data
      export FLASK_APP=CTFd
      export PYTHONPATH="${ctfdRuntimeSource}"
      export UPLOAD_FOLDER=/data/CTFd/uploads
      export LOG_FOLDER=/data/CTFd/logs
      export WORKERS=8
      export ACCESS_LOG=-
      export ERROR_LOG=-
      export REVERSE_PROXY=true
      export SERVER_SENT_EVENTS=false
      export CORS_ORIGINS="''${CORS_ORIGINS:-http://future.$DOJO_HOST}"
      export COVERAGE_FILE=/data/coverage/.coverage
      export IPYTHONDIR=/data/ctfd-ipython
      cd ${ctfdRuntimeSource}
      if [ "''${1:-}" = --coverage ]; then
        shift
        exec ${pythonRuntime}/bin/coverage run --source=CTFd/plugins/dojo_plugin -m flask "$@"
      fi
      if [ "''${1:-}" = --exec ]; then
        shift
        exec "$@"
      fi
      exec flask "$@"
    '';
  };

  dojoCtfdStart = writeDojoShellApplication {
    name = "dojo-ctfd-start";
    runtimeInputs = [
      dojoFlask
      pkgs.bash
      pkgs.openssl
      pythonRuntime
    ];
    text = ''
      . /run/dojo/ctfd.env
      case "$DOJO_ENV" in
        development)
          export FLASK_DEBUG=True
          export WERKZEUG_DEBUG_PIN=off
          exec dojo-flask run --host 127.0.0.1 --port 8000
          ;;
        coverage)
          export FLASK_DEBUG=True
          export WERKZEUG_DEBUG_PIN=off
          exec dojo-flask --coverage run --no-reload --host 127.0.0.1 --port 8000
          ;;
        production)
          RUN_ID="$(${pkgs.openssl}/bin/openssl rand -hex 4)"
          export RUN_ID
          exec dojo-flask --exec ${pkgs.bash}/bin/bash ${ctfdRuntimeSource}/docker-entrypoint.sh
          ;;
        *)
          echo "Invalid DOJO_ENV: $DOJO_ENV" >&2
          exit 1
          ;;
      esac
    '';
  };

  dojoSshAuth = writeDojoShellApplication {
    name = "dojo-ssh-auth";
    runtimeInputs = [ pythonRuntime ];
    text = ''
      . /run/dojo/ssh-auth.env
      encoded_user="$(${pythonRuntime}/bin/python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_USER")"
      encoded_pass="$(${pythonRuntime}/bin/python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_PASS")"
      encoded_name="$(${pythonRuntime}/bin/python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_NAME")"
      export DATABASE_URL="postgresql+psycopg2://$encoded_user:$encoded_pass@127.0.0.1:6432/$encoded_name"
      export PYTHONPATH=${dojoSource}/sshd
      exec ${pythonRuntime}/bin/python ${dojoSource}/sshd/auth.py "$@"
    '';
  };

  dojoSshEnter = writeDojoShellApplication {
    name = "dojo-ssh-enter";
    runtimeInputs = [
      pkgs.docker
      pythonRuntime
    ];
    text = ''
      . /run/dojo/ssh.env
      export DOJO_HOST DOJO_SSH_SERVICE_KEY MAC_HOSTNAME MAC_USERNAME
      export REDIS_URL=redis://127.0.0.1:6379
      export DOJO_WORKSPACE_CLI=${workspaceCli}/bin/dojo
      export PYTHONPATH=${dojoSource}/sshd
      exec ${pythonRuntime}/bin/python ${dojoSource}/sshd/enter.py "$@"
    '';
  };

  dojoHomefs = writeDojoShellApplication {
    name = "dojo-homefs";
    runtimeInputs = [
      pkgs.btrfs-progs
      pythonRuntime
    ];
    text = ''
      . /run/dojo/config.env
      export WORKSPACE_NODE
      bind_address="192.168.42.$((WORKSPACE_NODE + 1))"
      export PYTHONPATH=${dojoSource}/homefs
      export STORAGE_ROOT=/run/homefs
      export STORAGE_HOST="''${STORAGE_HOST:-192.168.42.1}"
      export LOCAL_STORAGE_HOST="$bind_address"
      exec ${pythonRuntime}/bin/gunicorn \
        --chdir ${dojoSource}/homefs \
        'homefs:create_app()' \
        --bind=unix:/run/docker/plugins/homefs.sock \
        --bind=127.0.0.1:4201 \
        --bind="$bind_address:4201" \
        --workers=32 \
        --access-logfile=- \
        --access-logformat '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s' \
        --timeout=300
    '';
  };

  dojoDojofs = writeDojoShellApplication {
    name = "dojo-dojofs";
    runtimeInputs = [
      dojofsPython
      pkgs.util-linux
    ];
    text = ''
      exec ${dojofsPython}/bin/python ${dojoSource}/dojofs/dojofs /run/dojo/dojofs
    '';
  };

  dojoWorkspaceAuthorizer = writeDojoShellApplication {
    name = "dojo-workspace-authorizer";
    runtimeInputs = [ dojofsPython ];
    text = ''
      exec ${dojofsPython}/bin/python ${dojoSource}/dojo/dojo-workspace-authorizer
    '';
  };

  dockerRemoveContainers = writeDojoShellApplication {
    name = "docker_remove_containers";
    runtimeInputs = [ pythonRuntime ];
    text = ''
      export PYTHONPATH=${dojoSource}/watchdog
      exec ${pythonRuntime}/bin/python ${dojoSource}/watchdog/docker_remove_containers.py "$@"
    '';
  };

  dockerPruneImages = writeDojoShellApplication {
    name = "docker_prune_images";
    runtimeInputs = [ pythonRuntime ];
    text = ''
      export PYTHONPATH=${dojoSource}/watchdog
      exec ${pythonRuntime}/bin/python ${dojoSource}/watchdog/docker_prune_images.py "$@"
    '';
  };

  dojoJournalSplunk = writeDojoShellApplication {
    name = "dojo-journal-splunk";
    runtimeInputs = [
      pkgs.systemd
      pythonRuntime
    ];
    text = ''
      . /run/dojo/config.env
      export WORKSPACE_NODE
      exec ${pythonRuntime}/bin/python ${dojoSource}/dojo/dojo-journal-splunk
    '';
  };

  dojoDatabaseInit = writeDojoShellApplication {
    name = "dojo-database-init";
    runtimeInputs = [
      pkgs.postgresql_17
      pkgs.util-linux
    ];
    text = ''
      . /data/config.env
      if [ "$DB_HOST" != /run/postgresql ]; then
        exit 0
      fi
      ${pkgs.util-linux}/bin/runuser -u postgres -- ${pkgs.postgresql_17}/bin/psql \
        --dbname postgres \
        --set ON_ERROR_STOP=1 \
        --set "dojo_user=$DB_USER" \
        --set "dojo_pass=$DB_PASS" \
        --set "dojo_name=$DB_NAME" <<SQL
      SELECT format('CREATE ROLE %I LOGIN', :'dojo_user') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'dojo_user') \gexec
      SELECT format('ALTER ROLE %I PASSWORD %L', :'dojo_user', :'dojo_pass') \gexec
      SELECT format('CREATE DATABASE %I OWNER %I', :'dojo_name', :'dojo_user') WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'dojo_name') \gexec
      SQL
      ${pkgs.util-linux}/bin/runuser -u postgres -- ${pkgs.postgresql_17}/bin/psql --dbname "$DB_NAME" --set ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto'
    '';
  };

  dockerDaemon = writeDojoShellApplication {
    name = "dojo-dockerd";
    runtimeInputs = [
      pkgs.docker
      pkgs.jq
    ];
    text = ''
      . /data/config.env
      hosts='["fd://"]'
      log_config='{}'
      if [ "$ENABLE_SPLUNK" = true ]; then
        splunk_host=127.0.0.1
        if [ "$WORKSPACE_NODE" -gt 0 ]; then
          splunk_host=192.168.42.1
        fi
        log_config="$(${pkgs.jq}/bin/jq -n --arg url "http://$splunk_host:8088" '{"log-driver":"splunk","log-opts":{"splunk-token":"11111111-1111-1111-1111-111111111111","splunk-url":$url,"splunk-insecureskipverify":"true","splunk-verify-connection":"false","splunk-gzip":"false","splunk-gzip-level":"0","splunk-format":"json","tag":"{{.Name}}/{{.ID}}","labels":"container_name,container_id,service","env":"DOJO_HOST,DOJO_ENV,WORKSPACE_NODE"}}')"
      fi
      ${pkgs.jq}/bin/jq -n \
        --argjson hosts "$hosts" \
        --argjson logging "$log_config" \
        --arg kata /opt/kata/bin/containerd-shim-kata-v2 \
        '{"data-root":"/data/docker","hosts":$hosts,"builder":{"Entitlements":{"security-insecure":true}},"runtimes":{"io.containerd.run.kata.v2":{"runtimeType":$kata,"options":{"ConfigPath":"/opt/kata/share/defaults/kata-containers/configuration.toml"}}}} + $logging' \
        > /run/dojo/docker-daemon.json
      exec ${pkgs.docker}/bin/dockerd --config-file=/run/dojo/docker-daemon.json
    '';
  };

  dojoDockerApi = writeDojoShellApplication {
    name = "dojo-docker-api";
    runtimeInputs = [ pkgs.socat ];
    text = ''
      . /run/dojo/config.env
      bind_address="192.168.42.$((WORKSPACE_NODE + 1))"
      exec socat "TCP-LISTEN:2375,bind=$bind_address,reuseaddr,fork" UNIX-CONNECT:/run/docker.sock
    '';
  };

  dojoRuntimeImages = writeDojoShellApplication {
    name = "dojo-runtime-images";
    runtimeInputs = [ pkgs.docker ];
    text = ''
      . /run/dojo/config.env
      if docker image inspect busybox:uclibc >/dev/null 2>&1; then
        exit 0
      fi
      if [ "$DOJO_OFFLINE" = true ]; then
        echo "busybox:uclibc is required in offline mode" >&2
        exit 1
      fi
      exec docker pull busybox:uclibc
    '';
  };

  prometheusTargets = writeDojoShellApplication {
    name = "dojo-prometheus-targets";
    runtimeInputs = [ pythonRuntime ];
    text = ''
      mkdir -p /run/dojo/prometheus-targets
      ${pythonRuntime}/bin/python - <<'PY'
      import json
      from pathlib import Path

      nodes = json.loads(Path("/data/workspace_nodes.json").read_text())
      addresses = ["192.168.42.1", *(f"192.168.42.{int(node) + 1}" for node in nodes)]
      target_dir = Path("/run/dojo/prometheus-targets")
      for name, port in (("cadvisor", 8080), ("node_exporter", 9100)):
          data = [{"labels": {"job": name}, "targets": [f"{address}:{port}" for address in addresses]}]
          temporary = target_dir / f".{name}.json"
          temporary.write_text(json.dumps(data, indent=2))
          temporary.replace(target_dir / f"{name}.json")
      PY
    '';
  };

  dojoReady = writeDojoShellApplication {
    name = "dojo-ready";
    runtimeInputs = [
      dojoRole
      pkgs.curl
      pkgs.gnugrep
      pkgs.redis
      pkgs.systemd
      pkgs.util-linux
    ];
    text = ''
      wait_for_unit() {
        unit="$1.service"
        while true; do
          if systemctl is-failed --quiet "$unit"; then
            echo "$unit failed" >&2
            exit 1
          fi
          if systemctl is-active --quiet "$unit"; then
            restart_count="$(systemctl show --property NRestarts --value "$unit")"
            sleep 1
            if systemctl is-active --quiet "$unit" &&
              [ "$(systemctl show --property NRestarts --value "$unit")" = "$restart_count" ]; then
              return
            fi
          fi
          sleep 1
        done
      }
      for unit in docker dojo-runtime-images dojo-workspace-builder dojo-homefs dojo-workspace-authorizer dojo-nginx; do
        wait_for_unit "$unit"
      done
      if dojo-role workspace; then
        wait_for_unit dojo-dojofs
        until [ -L /data/workspace/nix/var/nix/profiles/dojo-workspace ]; do sleep 1; done
        until [ -S /run/docker/plugins/homefs.sock ]; do sleep 1; done
        until mountpoint -q /run/dojo/dojofs; do sleep 1; done
      fi
      if dojo-role worker; then
        wait_for_unit dojo-docker-api
      fi
      if dojo-role main; then
        if dojo-role local-database; then
          wait_for_unit postgresql
        fi
        for unit in pgbouncer redis-dojo dojo-ctfd dojo-frontend dojo-stats-worker dojo-image-pull-worker sshd; do
          wait_for_unit "$unit"
        done
        until ${pkgs.redis}/bin/redis-cli -h 127.0.0.1 ping | grep -qx PONG; do sleep 1; done
        until ${pkgs.curl}/bin/curl --fail --silent http://127.0.0.1:8000/ >/dev/null; do sleep 1; done
        until ${pkgs.curl}/bin/curl --fail --silent http://127.0.0.1:3001/ >/dev/null; do sleep 1; done
        until [ -e /run/dojo-stats/ready ]; do sleep 1; done
      fi
      if dojo-role splunk; then
        wait_for_unit splunk
        until ${pkgs.curl}/bin/curl \
          --fail \
          --silent \
          --header 'Authorization: Splunk 11111111-1111-1111-1111-111111111111' \
          http://127.0.0.1:8088/services/collector/health >/dev/null; do sleep 1; done
      fi
    '';
  };

  vscodeTunnel = writeDojoShellApplication {
    name = "dojo-vscode-tunnel";
    runtimeInputs = [ vscodeCli ];
    text = ''
      export VSCODE_CLI_DATA_DIR=/data/vscode
      tunnel_name="$(< /data/vscode/tunnel-name)"
      exec code tunnel --name "$tunnel_name" --accept-server-license-terms
    '';
  };
in
{
  system.stateVersion = "26.05";
  system.installer.channel.enable = false;
  nixpkgs.flake.setFlakeRegistry = false;
  nixpkgs.flake.setNixPath = false;
  nix.channel.enable = false;
  nix.registry = lib.mkForce { };
  nix.nixPath = lib.mkForce [ ];

  system.tools = {
    nixos-build-vms.enable = false;
    nixos-enter.enable = false;
    nixos-generate-config.enable = false;
    nixos-install.enable = false;
    nixos-option.enable = false;
  };

  nix.settings = {
    experimental-features = [
      "nix-command"
      "flakes"
    ];
    accept-flake-config = true;
  };

  boot.kernel.sysctl = {
    "fs.inotify.max_user_instances" = 8192;
    "fs.inotify.max_user_watches" = 1048576;
    "kernel.pty.max" = 1048576;
    "kernel.core_pattern" = "core";
    "kernel.apparmor_restrict_unprivileged_userns" = 0;
  };

  fileSystems."/dev/shm" = {
    device = "shm";
    fsType = "tmpfs";
    options = [
      "nosuid"
      "nodev"
      "noexec"
      "size=50%"
    ];
  };

  fileSystems."/run/dojo" = {
    device = "tmpfs";
    fsType = "tmpfs";
    options = [
      "mode=0755"
      "shared"
    ];
  };

  users.users.hacker = {
    isNormalUser = true;
    uid = 1000;
    group = "hacker";
    home = "/home/hacker";
    createHome = true;
    extraGroups = [ "docker" ];
  };
  users.groups.hacker.gid = 1000;
  users.users.ctfd = {
    isSystemUser = true;
    uid = 1001;
    group = "ctfd";
    extraGroups = [ "docker" ];
  };
  users.groups.ctfd.gid = 1001;
  users.users.nginx = {
    isSystemUser = true;
    group = "nginx";
  };
  users.groups.nginx = { };
  users.users.dojo-frontend = {
    isSystemUser = true;
    group = "dojo-frontend";
  };
  users.groups.dojo-frontend = { };
  users.users.pgbouncer = {
    isSystemUser = true;
    group = "pgbouncer";
  };
  users.groups.pgbouncer = { };
  users.users.splunk = {
    isSystemUser = true;
    uid = 41812;
    group = "splunk";
    home = "/data/splunk";
  };
  users.groups.splunk.gid = 41812;

  programs.nix-ld = {
    enable = true;
    libraries = [
      pkgs.curl
      pkgs.libxml2
      pkgs.ncurses
      pkgs.openssl
      pkgs.stdenv.cc.cc.lib
      pkgs.zlib
    ];
  };

  programs.git = {
    enable = true;
    config.safe.directory = "/opt/pwn.college";
  };

  environment.systemPackages = [
    dojoDatabaseInit
    dojoFlask
    dojoHomefs
    dojoRole
    dojoSshAuth
    dojoSshEnter
    dojoTools
    dockerPruneImages
    dockerRemoveContainers
    pkgs.awscli2
    pkgs.bind.dnsutils
    pkgs.btrfs-progs
    pkgs.curl
    pkgs.docker
    pkgs.gawk
    pkgs.htop
    pkgs.iproute2
    pkgs.iptables
    pkgs.jq
    pkgs.kmod
    pkgs.nftables
    pkgs.openssl
    pkgs.openssh
    pkgs.postgresql_17
    pkgs.procps
    pkgs.redis
    pkgs.util-linux
    pkgs.wget
    pkgs.wireguard-tools
    pythonRuntime
    vscodeCli
  ];

  environment.variables.DOJO_CTFD_SOURCE = ctfdRuntimeSource;

  environment.etc."docker/seccomp.json".source = dockerSeccomp;
  environment.etc."dojo/user_firewall.allowed".source = dojoUserFirewall;
  environment.etc."kata-containers/configuration.toml".source =
    "${kata}/kata/share/defaults/kata-containers/configuration.toml";
  programs.ssh.extraConfig = ''
    GlobalKnownHostsFile /data/ssh_host_keys/ssh_known_hosts
  '';

  systemd.tmpfiles.rules = [
    "d /data 0755 root root -"
    "d /data/CTFd/logs 0755 ctfd ctfd -"
    "d /data/CTFd/uploads 0755 ctfd ctfd -"
    "d /data/backups 0700 root root -"
    "d /data/coverage 0755 ctfd ctfd -"
    "d /data/ctfd-ipython 0700 ctfd ctfd -"
    "d /data/docker 0710 root root -"
    "d /data/dojos 0755 ctfd ctfd -"
    "d /data/mac 0700 root root -"
    "d /data/redis 0750 redis-dojo redis-dojo -"
    "d /data/workspace 0755 root root -"
    "d /run/docker/plugins 0755 root root -"
    "d /run/dojo 0755 root root -"
    "d /var/log/nginx 0755 nginx nginx -"
    "d /run/dojo/acme/.well-known/acme-challenge 0755 nginx nginx -"
    "d /run/homefs 0755 root root -"
    "L+ /opt/kata - - - - ${kata}/kata"
  ];

  virtualisation.docker.enable = true;
  virtualisation.docker.enableOnBoot = true;

  systemd.services.docker = {
    requires = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    after = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    path = [
      pkgs.docker
      pkgs.iptables
      pkgs.nftables
      dojoStoragePermissionsTool
    ];
    serviceConfig = {
      ExecStart = lib.mkForce [
        ""
        "${dockerDaemon}/bin/dojo-dockerd"
      ];
      ExecStartPost = "${dojoDockerMigrateTool}/bin/dojo-docker-migrate";
      TimeoutStartSec = "10min";
    };
  };

  services.postgresql = {
    enable = true;
    package = pkgs.postgresql_17;
    dataDir = "/data/postgres";
    enableTCPIP = true;
    settings.listen_addresses = lib.mkForce "127.0.0.1";
    authentication = lib.mkForce ''
      local all all trust
      host all all 127.0.0.1/32 scram-sha-256
    '';
  };

  systemd.services.postgresql = {
    after = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    serviceConfig = {
      ExecCondition = "+${dojoRole}/bin/dojo-role local-database";
      TimeoutStartSec = "10min";
    };
  };

  systemd.services.postgresql-setup = {
    after = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    serviceConfig.ExecCondition = "+${dojoRole}/bin/dojo-role local-database";
  };

  systemd.services.pgbouncer = {
    description = "Dojo PostgreSQL connection pooler";
    after = [
      "dojo-config.service"
      "dojo-database-init.service"
    ];
    requires = [
      "dojo-config.service"
      "dojo-database-init.service"
    ];
    serviceConfig = {
      ExecCondition = "+${dojoRole}/bin/dojo-role main";
      ExecStart = "${pkgs.pgbouncer}/bin/pgbouncer /run/dojo/pgbouncer.ini";
      Group = "pgbouncer";
      LimitNOFILE = 65536;
      Restart = "always";
      RestartSec = 2;
      RuntimeDirectory = "pgbouncer";
      Type = "notify-reload";
      User = "pgbouncer";
    };
  };

  services.redis.servers.dojo = {
    enable = true;
    bind = "127.0.0.1";
    port = 6379;
    settings.dir = lib.mkForce "/data/redis";
  };

  systemd.services.redis-dojo = {
    after = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    serviceConfig = {
      ExecCondition = "+${dojoRole}/bin/dojo-role main";
      ReadWritePaths = [ "/data/redis" ];
    };
  };

  services.openssh = {
    enable = true;
    ports = [ 22 ];
    sftpServerExecutable = "/run/dojo/libexec/sftp-server";
    settings = {
      KbdInteractiveAuthentication = false;
      PasswordAuthentication = false;
      UsePAM = true;
      X11Forwarding = false;
      AllowTcpForwarding = false;
    };
    extraConfig = ''
      Match User hacker
        AuthorizedKeysCommand ${config.security.wrapperDir}/dojo-ssh-auth
        AuthorizedKeysCommandUser root
    '';
    hostKeys = [
      {
        path = "/data/ssh_host_keys/ssh_host_ed25519_key";
        type = "ed25519";
      }
      {
        path = "/data/ssh_host_keys/ssh_host_ecdsa_key";
        type = "ecdsa";
        bits = 256;
      }
      {
        path = "/data/ssh_host_keys/ssh_host_rsa_key";
        type = "rsa";
        bits = 4096;
      }
    ];
  };

  security.wrappers.dojo-ssh-auth = {
    source = "${dojoSshAuth}/bin/dojo-ssh-auth";
    owner = "root";
    group = "root";
    permissions = "a+rx";
  };

  systemd.services.sshd = {
    after = [
      "dojo-config.service"
      "dojo-database-init.service"
      "dojo-workspace-builder.service"
      "pgbouncer.service"
      "redis-dojo.service"
    ];
    requires = [ "dojo-config.service" ];
    preStart = ''
      install -d -m 700 -o hacker -g hacker /home/hacker/.ssh
      if [ -f /data/mac/key ]; then
        install -m 600 -o hacker -g hacker /data/mac/key /home/hacker/.ssh/key
      fi
    '';
    serviceConfig.ExecCondition = "${dojoRole}/bin/dojo-role main";
  };

  systemd.services.sshd-keygen = {
    after = [ "dojo-storage.service" ];
    requires = [ "dojo-storage.service" ];
  };

  services.cadvisor = {
    enable = true;
    listenAddress = "0.0.0.0";
    port = 8080;
    extraOptions = [
      "--docker_only=true"
      "--docker=unix:///run/docker.sock"
    ];
  };

  systemd.services.cadvisor = {
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
  };

  services.prometheus.exporters.node = {
    enable = true;
    listenAddress = "0.0.0.0";
    port = 9100;
  };

  systemd.services.prometheus-node-exporter = {
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
  };

  programs.fuse.userAllowOther = true;

  services.prometheus = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9090;
    stateDir = "dojo-prometheus";
    scrapeConfigs = [
      {
        job_name = "cadvisor";
        file_sd_configs = [ { files = [ "/run/dojo/prometheus-targets/cadvisor.json" ]; } ];
      }
      {
        job_name = "node_exporter";
        file_sd_configs = [ { files = [ "/run/dojo/prometheus-targets/node_exporter.json" ]; } ];
      }
    ];
  };

  systemd.services.prometheus = {
    after = [
      "docker.service"
      "dojo-prometheus-targets.service"
    ];
    requires = [
      "docker.service"
      "dojo-prometheus-targets.service"
    ];
    serviceConfig.ExecCondition = "+${dojoRole}/bin/dojo-role main";
  };

  services.grafana = {
    enable = true;
    settings = {
      server = {
        http_addr = "0.0.0.0";
        http_port = 3000;
      };
      security.disable_initial_admin_creation = true;
      security.secret_key = "$__file{/data/grafana-secret-key}";
      auth = {
        disable_login_form = true;
        disable_signout_menu = true;
      };
      "auth.anonymous" = {
        enabled = true;
        org_role = "Admin";
      };
    };
    provision.datasources.settings = {
      apiVersion = 1;
      datasources = [
        {
          name = "Prometheus";
          type = "prometheus";
          access = "proxy";
          url = "http://127.0.0.1:9090";
          isDefault = true;
        }
      ];
    };
  };

  systemd.services.grafana = {
    after = [
      "docker.service"
      "dojo-storage.service"
      "prometheus.service"
    ];
    requires = [
      "docker.service"
      "dojo-storage.service"
    ];
    serviceConfig.ExecCondition = "+${dojoRole}/bin/dojo-role main";
  };

  systemd.services.dojo-config = {
    description = "Materialize dojo runtime configuration";
    wantedBy = [ "dojo.target" ];
    after = [ "dojo-storage.service" ];
    requires = [ "dojo-storage.service" ];
    path = [
      pkgs.coreutils
      pkgs.diffutils
      pkgs.openssl
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      PassEnvironment = dojoConfigNames;
      ExecStart = "${dojoConfigTool}/bin/dojo-config";
    };
  };

  systemd.services.dojo-storage = {
    description = "Prepare persistent dojo storage";
    wantedBy = [ "dojo.target" ];
    before = [
      "dojo-config.service"
      "docker.service"
      "postgresql.service"
      "redis-dojo.service"
    ];
    path = [
      pkgs.btrfs-progs
      pkgs.coreutils
      pkgs.e2fsprogs
      pkgs.gawk
      pkgs.gnugrep
      pkgs.openssh
      pkgs.openssl
      pkgs.util-linux
      dojoStoragePermissionsTool
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      PassEnvironment = [
        "DOJO_DATA_STORAGE_SIZE"
        "DOJO_HOME_STORAGE_SIZE"
        "DOJO_OFFLINE"
      ];
      ExecStart = "${dojoStorageTool}/bin/dojo-storage";
    };
  };

  systemd.services.dojo-database-init = {
    description = "Initialize the dojo PostgreSQL role and database";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-config.service"
      "postgresql.service"
    ];
    requires = [
      "dojo-config.service"
      "postgresql.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecCondition = "${dojoRole}/bin/dojo-role main";
      ExecStart = "${dojoDatabaseInit}/bin/dojo-database-init";
    };
  };

  systemd.services.dojo-network = {
    description = "Configure dojo workspace networking";
    wantedBy = [ "dojo.target" ];
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
    restartTriggers = [ dojoUserFirewall ];
    path = [
      dojoNodeTool
      pkgs.bind.dnsutils
      pkgs.coreutils
      pkgs.docker
      pkgs.gawk
      pkgs.getent
      pkgs.iproute2
      pkgs.iptables
      pkgs.jq
      pkgs.wireguard-tools
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${dojoNetworkTool}/bin/dojo-network";
    };
  };

  systemd.services.dojo-docker-api = {
    description = "Expose the learner Docker API on the private worker network";
    wantedBy = [ "dojo.target" ];
    after = [ "dojo-network.service" ];
    requires = [ "dojo-network.service" ];
    serviceConfig = {
      ExecCondition = "${dojoRole}/bin/dojo-role worker";
      ExecStart = "${dojoDockerApi}/bin/dojo-docker-api";
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.services.dojo-runtime-images = {
    description = "Prepare Docker images required by the learner runtime";
    wantedBy = [ "dojo.target" ];
    after = [
      "docker.service"
      "dojo-config.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${dojoRuntimeImages}/bin/dojo-runtime-images";
    };
  };

  systemd.services.dojo-workspace-builder = {
    description = "Build the learner workspace Nix profile";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    path = [
      pkgs.coreutils
      pkgs.git
      pkgs.nix
      pkgs.util-linux
    ];
    environment.DOJO_WORKSPACE_FLAKE = "${dojoSource}/workspace";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${dojoWorkspaceBuildTool}/bin/dojo-workspace-build";
      TimeoutStartSec = "infinity";
    };
  };

  systemd.services.dojo-homefs = {
    description = "Dojo home filesystem Docker volume plugin";
    wantedBy = [ "dojo.target" ];
    after = [
      "docker.service"
      "dojo-config.service"
      "dojo-network.service"
      "dojo-storage.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
      "dojo-network.service"
      "dojo-storage.service"
    ];
    serviceConfig = {
      ExecStart = "${dojoHomefs}/bin/dojo-homefs";
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.services.dojo-dojofs = {
    description = "Dojo workspace metadata filesystem";
    wantedBy = [ "dojo.target" ];
    after = [
      "docker.service"
      "dojo-network.service"
    ];
    requires = [
      "docker.service"
      "dojo-network.service"
    ];
    serviceConfig = {
      ExecCondition = "${dojoRole}/bin/dojo-role workspace";
      ExecStart = "${dojoDojofs}/bin/dojo-dojofs";
      ExecStop = "${pkgs.fuse3}/bin/fusermount3 -u /run/dojo/dojofs";
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.services.dojo-workspace-authorizer = {
    description = "Authorize live learner workspace routes";
    wantedBy = [ "dojo.target" ];
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
    serviceConfig = {
      ExecStart = "${dojoWorkspaceAuthorizer}/bin/dojo-workspace-authorizer";
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.services.dojo-ctfd-source = {
    description = "Prepare the CTFd runtime source tree";
    wantedBy = [ "dojo.target" ];
    before = [ "dojo-ctfd.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${dojoCtfdSource}/bin/dojo-ctfd-source";
    };
  };

  systemd.services.dojo-ctfd = {
    description = "pwn.college CTFd application";
    wantedBy = [ "dojo.target" ];
    partOf = [ "dojo-ctfd-source.service" ];
    after = [
      "dojo-database-init.service"
      "dojo-ctfd-source.service"
      "dojo-dojofs.service"
      "dojo-homefs.service"
      "dojo-network.service"
      "dojo-runtime-images.service"
      "dojo-workspace-builder.service"
      "pgbouncer.service"
      "redis-dojo.service"
    ];
    requires = [
      "dojo-database-init.service"
      "dojo-ctfd-source.service"
      "dojo-homefs.service"
      "dojo-network.service"
      "dojo-runtime-images.service"
      "dojo-workspace-builder.service"
      "pgbouncer.service"
      "redis-dojo.service"
    ];
    environment = {
      PYTHONUNBUFFERED = "1";
      PYTHONDONTWRITEBYTECODE = "1";
    };
    serviceConfig = {
      User = "ctfd";
      Group = "ctfd";
      ExecCondition = "+${dojoRole}/bin/dojo-role main";
      ExecStart = "${dojoCtfdStart}/bin/dojo-ctfd-start";
      Restart = "always";
      RestartSec = 2;
      LimitNOFILE = "32768:1048576";
      ReadOnlyPaths = ctfdLiveSourcePaths;
    };
  };

  systemd.services.dojo-stats-worker = {
    description = "Dojo statistics worker";
    wantedBy = [ "dojo.target" ];
    partOf = [ "dojo-ctfd-source.service" ];
    environment.DOJO_STATS_READY = "/run/dojo-stats/ready";
    after = [
      "dojo-ctfd.service"
      "dojo-ctfd-source.service"
      "redis-dojo.service"
    ];
    requires = [
      "dojo-ctfd.service"
      "dojo-ctfd-source.service"
      "redis-dojo.service"
    ];
    serviceConfig = {
      User = "ctfd";
      Group = "ctfd";
      ExecCondition = "+${dojoRole}/bin/dojo-role main";
      RuntimeDirectory = "dojo-stats";
      RuntimeDirectoryMode = "0750";
      ExecStartPre = "${pkgs.coreutils}/bin/rm -f /run/dojo-stats/ready";
      ExecStart = "${dojoFlask}/bin/dojo-flask shell ${ctfdRuntimeSource}/CTFd/plugins/dojo_plugin/worker/__main__.py";
      Restart = "always";
      RestartSec = 2;
      ReadOnlyPaths = ctfdLiveSourcePaths;
    };
  };

  systemd.services.dojo-image-pull-worker = {
    description = "Dojo challenge image pull worker";
    wantedBy = [ "dojo.target" ];
    partOf = [ "dojo-ctfd-source.service" ];
    after = [
      "dojo-ctfd.service"
      "dojo-ctfd-source.service"
      "redis-dojo.service"
    ];
    requires = [
      "dojo-ctfd.service"
      "dojo-ctfd-source.service"
      "redis-dojo.service"
    ];
    serviceConfig = {
      User = "ctfd";
      Group = "ctfd";
      ExecCondition = "+${dojoRole}/bin/dojo-role main";
      ExecStart = "${dojoFlask}/bin/dojo-flask shell ${ctfdRuntimeSource}/CTFd/plugins/dojo_plugin/worker/image_pulls_main.py";
      Restart = "always";
      RestartSec = 2;
      ReadOnlyPaths = ctfdLiveSourcePaths;
    };
  };

  systemd.services.dojo-frontend = {
    description = "Dojo Next.js frontend";
    wantedBy = [ "dojo.target" ];
    after = [
      "docker.service"
      "dojo-config.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
    ];
    environment = {
      DOJO_API_ORIGIN = "http://127.0.0.1:8000";
      NODE_ENV = "production";
      PORT = "3001";
      HOSTNAME = "127.0.0.1";
    };
    serviceConfig = {
      User = "dojo-frontend";
      Group = "dojo-frontend";
      CacheDirectory = "dojo-frontend";
      CacheDirectoryMode = "0750";
      ExecCondition = "+${dojoRole}/bin/dojo-role main";
      ExecStart = "${pkgs.nodejs_22}/bin/node ${frontend}/server.js";
      WorkingDirectory = frontend;
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.services.dojo-certificates = {
    description = "Prepare dojo TLS certificates";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    path = [
      pkgs.coreutils
      pkgs.openssl
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${dojoCertificatesTool}/bin/dojo-certificates";
    };
  };

  systemd.services.dojo-nginx = {
    description = "Dojo HTTP and workspace proxy";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-certificates.service"
      "dojo-ctfd.service"
      "dojo-frontend.service"
      "dojo-network.service"
      "dojo-workspace-authorizer.service"
    ];
    requires = [
      "dojo-certificates.service"
      "dojo-network.service"
      "dojo-workspace-authorizer.service"
    ];
    path = [
      nginx
      pkgs.coreutils
      pkgs.gawk
      pkgs.gettext
      pkgs.gnused
    ];
    environment = {
      DOJO_NGINX_MAIN_SOURCE = "${dojoSource}/nginx";
      DOJO_NGINX_WORKSPACE_SOURCE = "${dojoSource}/nginx-workspace";
    };
    serviceConfig = {
      ExecStartPre = "${dojoNginxConfigTool}/bin/dojo-nginx-config";
      ExecStart = "${nginx}/bin/nginx -c /run/dojo/nginx/nginx.conf -g 'daemon off;'";
      ExecReload = "${nginx}/bin/nginx -c /run/dojo/nginx/nginx.conf -s reload";
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.services.acme-dojo = {
    description = "Renew dojo TLS certificates";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-nginx.service"
      "network-online.target"
    ];
    wants = [ "network-online.target" ];
    path = [
      pkgs.coreutils
      pkgs.getent
      pkgs.lego
      pkgs.openssl
      pkgs.systemd
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecCondition = "${dojoRole}/bin/dojo-role main";
      ExecStart = "${dojoCertificatesTool}/bin/dojo-certificates renew";
    };
  };

  systemd.timers.acme-dojo = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2min";
      OnUnitActiveSec = "12h";
      Persistent = true;
      Unit = "acme-dojo.service";
    };
  };

  systemd.services.dojo-prometheus-targets = {
    description = "Generate dojo Prometheus targets";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecCondition = "${dojoRole}/bin/dojo-role main";
      ExecStart = "${prometheusTargets}/bin/dojo-prometheus-targets";
    };
  };

  systemd.services.dojo-splunk-install = {
    description = "Install and configure native Splunk";
    wantedBy = [ "dojo.target" ];
    after = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
      "network-online.target"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
      "dojo-storage.service"
    ];
    wants = [ "network-online.target" ];
    path = [
      pkgs.coreutils
      pkgs.curl
      pkgs.gnutar
      pkgs.gzip
      pkgs.util-linux
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecCondition = "${dojoRole}/bin/dojo-role splunk";
      ExecStart = "${dojoSplunkInstallTool}/bin/dojo-splunk-install";
      TimeoutStartSec = 1800;
    };
  };

  systemd.services.splunk = {
    description = "Splunk Enterprise";
    wantedBy = [ "dojo.target" ];
    after = [ "dojo-splunk-install.service" ];
    requires = [ "dojo-splunk-install.service" ];
    environment = {
      HOME = "/data/splunk";
      SPLUNK_HOME = "/data/splunk/opt/splunk";
    };
    serviceConfig = {
      User = "splunk";
      Group = "splunk";
      ExecCondition = "+${dojoRole}/bin/dojo-role splunk";
      ExecStart = "/data/splunk/opt/splunk/bin/splunk _internal_launch_under_systemd";
      Restart = "always";
      KillMode = "mixed";
      KillSignal = "SIGINT";
      TimeoutStopSec = 360;
      LimitNOFILE = 65536;
      SuccessExitStatus = [
        51
        52
      ];
      RestartPreventExitStatus = 51;
      RestartForceExitStatus = 52;
      Delegate = true;
    };
  };

  systemd.services.dojo-journal-splunk = {
    description = "Forward the system journal to Splunk HEC";
    wantedBy = [ "dojo.target" ];
    after = [
      "dojo-config.service"
      "dojo-network.service"
      "splunk.service"
    ];
    requires = [
      "dojo-config.service"
      "dojo-network.service"
    ];
    serviceConfig = {
      ExecCondition = "${dojoRole}/bin/dojo-role splunk-client";
      ExecStart = "${dojoJournalSplunk}/bin/dojo-journal-splunk";
      Restart = "always";
      RestartSec = 2;
    };
  };

  systemd.paths.dojo-prometheus-targets = {
    wantedBy = [ "dojo.target" ];
    pathConfig.PathChanged = "/data/workspace_nodes.json";
  };

  systemd.services.dojo-watchdog-cleanup = {
    description = "Remove expired dojo workspaces";
    after = [
      "docker.service"
      "dojo-config.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecCondition = "${dojoRole}/bin/dojo-role main";
      ExecStart = "${dockerRemoveContainers}/bin/docker_remove_containers";
    };
  };

  systemd.timers.dojo-watchdog-cleanup = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "5min";
      OnUnitActiveSec = "5min";
      Unit = "dojo-watchdog-cleanup.service";
    };
  };

  systemd.services.dojo-watchdog-prune = {
    description = "Prune unused dojo challenge images";
    after = [
      "docker.service"
      "dojo-config.service"
    ];
    requires = [
      "docker.service"
      "dojo-config.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecCondition = "${dojoRole}/bin/dojo-role main";
      ExecStart = "${dockerPruneImages}/bin/docker_prune_images";
    };
  };

  systemd.timers.dojo-watchdog-prune = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 09:00:00 UTC";
      Persistent = true;
      Unit = "dojo-watchdog-prune.service";
    };
  };

  systemd.services.dojo-backup = {
    description = "Back up the dojo database";
    after = [ "dojo-database-init.service" ];
    requires = [ "dojo-database-init.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecCondition = "${dojoRole}/bin/dojo-role main";
      ExecStart = "${dojoCommand}/bin/dojo backup";
    };
    path = [ pkgs.postgresql_17 ];
  };

  systemd.timers.dojo-backup = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "hourly";
      Persistent = true;
      Unit = "dojo-backup.service";
    };
  };

  systemd.services.dojo-cloud-backup = {
    description = "Upload encrypted dojo backups";
    after = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    requires = [
      "dojo-config.service"
      "dojo-storage.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecCondition = "${dojoRole}/bin/dojo-role cloud-backup";
      ExecStart = "${dojoCommand}/bin/dojo cloud-backup";
    };
    path = [
      pkgs.awscli2
      pkgs.openssl
    ];
  };

  systemd.services.vscode-tunnel = {
    description = "VS Code Remote Tunnel";
    wantedBy = [ "multi-user.target" ];
    after = [
      "dojo-storage.service"
      "network-online.target"
    ];
    requires = [ "dojo-storage.service" ];
    wants = [ "network-online.target" ];
    unitConfig.ConditionPathExists = "/data/vscode/tunnel-name";
    serviceConfig = {
      ExecStart = "${vscodeTunnel}/bin/dojo-vscode-tunnel";
      Restart = "on-failure";
    };
  };

  systemd.timers.dojo-cloud-backup = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      Unit = "dojo-cloud-backup.service";
    };
  };

  systemd.services.dojo-ready = {
    description = "Wait for the dojo service graph";
    wantedBy = [ "dojo-ready.target" ];
    after = [
      "dojo-ctfd.service"
      "dojo-ctfd-source.service"
      "dojo-dojofs.service"
      "dojo-frontend.service"
      "dojo-homefs.service"
      "dojo-image-pull-worker.service"
      "dojo-nginx.service"
      "dojo-stats-worker.service"
      "dojo-workspace-builder.service"
      "dojo-workspace-authorizer.service"
      "sshd.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${dojoReady}/bin/dojo-ready";
      TimeoutStartSec = 1800;
    };
  };

  systemd.targets.dojo = {
    description = "pwn.college dojo";
    wantedBy = [ "multi-user.target" ];
    wants = [
      "acme-dojo.service"
      "cadvisor.service"
      "dojo-certificates.service"
      "dojo-config.service"
      "dojo-ctfd.service"
      "dojo-database-init.service"
      "dojo-docker-api.service"
      "dojo-dojofs.service"
      "dojo-frontend.service"
      "dojo-homefs.service"
      "dojo-image-pull-worker.service"
      "dojo-network.service"
      "dojo-nginx.service"
      "dojo-prometheus-targets.service"
      "dojo-ready.target"
      "dojo-runtime-images.service"
      "dojo-splunk-install.service"
      "dojo-journal-splunk.service"
      "dojo-stats-worker.service"
      "dojo-storage.service"
      "dojo-workspace-builder.service"
      "dojo-workspace-authorizer.service"
      "docker.service"
      "grafana.service"
      "prometheus-node-exporter.service"
      "pgbouncer.service"
      "postgresql.service"
      "prometheus.service"
      "redis-dojo.service"
      "sshd.service"
      "splunk.service"
    ];
  };

  systemd.targets.dojo-ready = {
    description = "pwn.college dojo readiness";
    requires = [ "dojo-ready.service" ];
    after = [ "dojo-ready.service" ];
  };

  documentation.enable = false;
  networking.hosts."192.168.42.1" = [ "pwn.college" ];
  networking.firewall.enable = false;
  networking.resolvconf.enable = false;
  networking.useDHCP = false;
  networking.useHostResolvConf = true;
  time.timeZone = "UTC";
}
