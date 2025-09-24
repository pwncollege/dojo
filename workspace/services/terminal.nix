{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };
  themes = import ../themes { inherit pkgs; };

  serviceScript = pkgs.writeScript "dojo-terminal" ''
    #!${pkgs.bash}/bin/bash

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    export TERM=xterm-256color

    # Setup fish configuration
    mkdir -p /home/hacker/.config/fish

    # Create our default config
    cat > /home/hacker/.config/fish/config.fish.orig << 'EOF'

if status is-interactive
    # Commands to run in interactive sessions can go here
    set fish_greeting
    #neofetch
end


# Basic aliases
alias ll="ls -la"
alias l="eza -lah --icons --group-directories-first"
alias v="nvim"

# Fast file opener with fzf
function o --description 'Open file with fzf'
    # Use fd for faster file finding with common exclusions
    set -l selected (fd -t f -H -E .git -E node_modules -E .cache | \
                     fzf --preview 'bat --color=always --style=numbers --line-range=:100 {} 2>/dev/null || head -100 {}' \
                         --preview-window='right:50%:wrap' \
                         --bind='ctrl-/:toggle-preview' \
                         --height=80% \
                         --layout=reverse)

    # Only open if a file was selected
    if test -n "$selected"
        v $selected
    end
end

# Bind Ctrl+O to the o function
bind \co 'o; commandline -f repaint'

EOF

    # Use our config if user doesn't have one
    if [ ! -f /home/hacker/.config/fish/config.fish ]; then
        cp /home/hacker/.config/fish/config.fish.orig /home/hacker/.config/fish/config.fish
    fi
    chown -R hacker:hacker /home/hacker/.config

    # Load theme using organized theme files
    THEME_NAME="''${TERMINAL_THEME_NAME:-matrix}"
    echo "[TERMINAL] Loading theme: $THEME_NAME" >&2

    case "$THEME_NAME" in
      "matrix")
        THEME=$(cat ${themes.getTerminalTheme "matrix"})
        ;;
      "amethyst")
        THEME=$(cat ${themes.getTerminalTheme "amethyst"})
        ;;
      "solarized")
        THEME=$(cat ${themes.getTerminalTheme "solarized"})
        ;;
      "everforest")
        THEME=$(cat ${themes.getTerminalTheme "everforest"})
        ;;
      "gruvbox")
        THEME=$(cat ${themes.getTerminalTheme "gruvbox"})
        ;;
      "perplexity")
        THEME=$(cat ${themes.getTerminalTheme "perplexity"})
        ;;
      *)
        THEME=$(cat ${themes.getTerminalTheme "matrix"})
        echo "[TERMINAL] Unknown theme '$THEME_NAME', using matrix" >&2
        ;;
    esac
    echo "[TERMINAL] Theme loaded successfully" >&2

    ${service}/bin/dojo-service start terminal-service/ttyd \
      ${pkgs.ttyd}/bin/ttyd \
        --port 7681 \
        --interface 0.0.0.0 \
        --writable \
        -t disableLeaveAlert=true \
        -t 'fontSize=14' \
        -t 'fontFamily=JetBrainsMono Nerd Font, DejaVu Sans Mono, Consolas, Monaco, Menlo, Courier New, monospace' \
        -t "theme=$THEME" \
        -t 'cursorStyle=block' \
        -t 'cursorBlink=true' \
        -t 'scrollback=10000' \
        -t 'lineHeight=1.2' \
        -t 'scrollOnKey=true' \
        -t 'scrollOnOutput=true' \
        -t 'scrollSensitivity=1' \
        -t 'rendererType=webgl' \
        ${pkgs.fish}/bin/fish --login

    until ${pkgs.curl}/bin/curl -fs localhost:7681 >/dev/null; do sleep 0.1; done
  '';

in pkgs.stdenv.mkDerivation {
  name = "terminal-service";
  buildInputs = with pkgs; [
    ttyd
    bashInteractive
    zsh
    fish
    neovim
    curl
    # Dependencies for Mason LSP servers
    wget
    unzip
    gnutar
    gzip
    nodejs
    nodePackages.npm
    python3
    python3Packages.pip
    gcc
    # Search and navigation tools
    ripgrep
    fzf
    fd
    bat
    eza
    # Nerd Font for icons
    nerd-fonts.jetbrains-mono
    # System info
    neofetch
  ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-terminal
    chmod +x $out/bin/dojo-terminal
    ln -s ${pkgs.ttyd}/bin/ttyd $out/bin/ttyd
    ln -s ${pkgs.ttyd}/bin/ttyd $out/bin/terminal
    ln -s ${pkgs.zsh}/bin/zsh $out/bin/zsh
    ln -s ${pkgs.fish}/bin/fish $out/bin/fish
    ln -s ${pkgs.neovim}/bin/nvim $out/bin/nvim
    ln -s ${pkgs.neovim}/bin/nvim $out/bin/vim
    ln -s ${pkgs.ripgrep}/bin/rg $out/bin/rg
    ln -s ${pkgs.fzf}/bin/fzf $out/bin/fzf
    ln -s ${pkgs.fd}/bin/fd $out/bin/fd
    ln -s ${pkgs.bat}/bin/bat $out/bin/bat
    ln -s ${pkgs.eza}/bin/eza $out/bin/eza
    ln -s ${pkgs.neofetch}/bin/neofetch $out/bin/neofetch

    runHook postInstall
  '';
}
