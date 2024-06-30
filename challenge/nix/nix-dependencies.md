# Packages needed for functioning systems without services on nix

---

# Packages

## builder-desktop

- tigervnc
  
- novnc
  
- xfce subpackages
  
- xorg subpackages
  
- <mark>TODO: Python stuff</mark>
  
- xclip
  
- dbus (dbus-x11 but same impl)
  
- at-spi2-atk
  

## builder-code-server

- code-server (unstable only)
  
- qemu (need to test if full package is better)
  

---

# Subpackages for Xfce (via [ubuntu](https://packages.ubuntu.com/noble/xfce4))

## Dependencies

- xfce.libxfce4ui
  
- xfce.thunar
  
- xfce.xfce4-appfinder
  
- xfce.xfce4-panel
  
- xfce.xfce4-pulseaudio-plugin
  
- xfce.xfce4-session
  
- xfce.xfce4-settings
  
- xfce.xfconf
  
- xfce.xfdesktop
  
- xfce.xfwm4
  
- xorg.xrdb
  
- xorg.xhost (maybe dev dependency)
  

### Depended by dojo

- xfce.xfce4-terminal
  
- xfce.mousepad
  

## Recommended Packages

- tango-icon-theme
  
- xfce.thunar-volman
  
- xfce.xfce4-notifyd
  
- xorg (see subpackages for xorg)
  

## Suggestions

- xfce.xfce4-power-manager
  
- [xfce4-goodies]([Ubuntu – Details of package xfce4-goodies in noble](https://packages.ubuntu.com/noble/xfce4-goodies)) (not avaliable on nixos)
  

---

# Subpackages for Xorg (via [ubunutu](https://packages.ubuntu.com/noble/xorg))

## Dependencies

- xterm
  
- libGL (says libgl1 but I'll assume this will work also)
  
- libGLU (says libglu1 but should work also)
  
- x11-apps (not listed on nixpkgs)
  
- x11-session-utils (not listed on nixpkgs)
  
- x11-utils (not listed on nixpkgs)
  
- xorg.xkbutils
  
- x11-xserver-utils (not listed on nixpkgs)
  
- xorg.xauth
  
- xfonts-base (not listed on nixpkgs you have to install fonts I think)
  
- xfonts-utils (not listed on nixpkgs you have to install fonts I think)
  
- xorg.xinit
  
- xorg.xinput
  
- xkbset (not exact match for xkb-data but should help?)
  
- xorg.xorgdocs
  
- xorg.xorgserver
  
- xorg.xfs (not listed but needed for stuff)
  
- <mark>xorg.xf86videoqxl (depends on what display server you are running)</mark>
  
- mesa.drivers (not listed in search but will resolve)
  

### Depended by dojo

- xterm

## Suggested

- xorg.fontutil (xfs util but same probably)

nix-shell -p xfce.libxfce4ui xfce.thunar xfce.xfce4-appfinder xfce.xfce4-panel xfce.xfce4-pulseaudio-plugin xfce.xfce4-session xfce.xfce4-settings xfce.xfconf xfce.xfdesktop xfce.xfwm4 xfce.xfce4-terminal xfce.mousepad tango-icon-theme xfce.thunar-volman xfce.xfce4-notifyd xfce.xfce4-power-manager l  
ibGL libGLU xorg.xkbutils xorg.xauth xorg.xinit xorg.xinput xorg.xorgserver xorg.xfs xorg.fontutil

got to mesa driver issues
