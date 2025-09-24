{ pkgs }:

pkgs.writeShellScriptBin "dojo-zsh-setup" ''
  #!${pkgs.bash}/bin/bash
  
  # Always create .zshrc if it doesn't exist
  if [ ! -f /home/hacker/.zshrc ]; then
    cat > /home/hacker/.zshrc << 'EOF'
# Path configuration
export PATH="/run/challenge/bin:/run/dojo/bin:$PATH"

# Basic zsh configuration
export LANG="C.UTF-8"
export TERM="xterm-256color"

# History
HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
setopt appendhistory

# Basic completion
autoload -Uz compinit && compinit

# Prompt with colors (fallback if no oh-my-zsh)
autoload -Uz colors && colors
PS1="%{$fg_bold[green]%}%n@%m%{$reset_color%}:%{$fg_bold[blue]%}%~%{$reset_color%}$ "

# Aliases
alias ll='ls -la'
alias la='ls -A'
alias l='ls -CF'
alias ls='ls --color=auto'
alias grep='grep --color=auto'

# Try to setup oh-my-zsh if we have internet
if command -v git >/dev/null 2>&1 && [ ! -d /home/hacker/.oh-my-zsh ]; then
  export ZSH="/home/hacker/.oh-my-zsh"
  git clone --depth=1 https://github.com/ohmyzsh/ohmyzsh.git $ZSH 2>/dev/null && {
    # If clone succeeded, update zshrc for oh-my-zsh
    cat > /home/hacker/.zshrc << 'OHMYZSH'
export ZSH="/home/hacker/.oh-my-zsh"
ZSH_THEME="agnoster"
plugins=(git docker python golang rust)
source $ZSH/oh-my-zsh.sh

# Custom aliases
alias ll='ls -la'
alias la='ls -A'
alias l='ls -CF'

# Set PATH to include challenge and dojo bins
export PATH="/run/challenge/bin:/run/dojo/bin:$PATH"
OHMYZSH
  }
fi

# Source oh-my-zsh if it exists
if [ -d /home/hacker/.oh-my-zsh ]; then
  export ZSH="/home/hacker/.oh-my-zsh"
  ZSH_THEME="agnoster"
  plugins=(git docker python golang rust)
  [ -f $ZSH/oh-my-zsh.sh ] && source $ZSH/oh-my-zsh.sh
fi
EOF
    
    # Fix permissions
    chown hacker:hacker /home/hacker/.zshrc 2>/dev/null || true
  fi
  
  # Fix oh-my-zsh permissions if it exists
  [ -d /home/hacker/.oh-my-zsh ] && chown -R hacker:hacker /home/hacker/.oh-my-zsh 2>/dev/null || true
''