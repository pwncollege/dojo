#!/bin/sh

# Add /challenge to the "bookmarks" in GTK file dialog
mkdir -p /home/hacker/.config/gtk-3.0
[ -f /home/hacker/.config/gtk-3.0/bookmarks ] || echo "file:///challenge" > /home/hacker/.config/gtk-3.0/bookmarks

# Do the same to the QT file dialog
[ -f /home/hacker/.config/QtProject.conf ] || cat <<END > /home/hacker/.config/QtProject.conf
[FileDialog]
history=file:///home/hacker
lastVisited=file:///
qtVersion=5.15.2
shortcuts=file:, file:///home/hacker, file:///challenge
sidebarWidth=90
treeViewHeader=@ByteArray(\0\0\0\xff\0\0\0\0\0\0\0\x1\0\0\0\0\0\0\0\0\x1\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x1\xec\0\0\0\x4\x1\x1\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x64\xff\xff\xff\xff\0\0\0\x81\0\0\0\0\0\0\0\x4\0\0\0\xff\0\0\0\x1\0\0\0\0\0\0\0?\0\0\0\x1\0\0\0\0\0\0\0@\0\0\0\x1\0\0\0\0\0\0\0n\0\0\0\x1\0\0\0\0\0\0\x3\xe8\0\xff\xff\xff\xff)
viewMode=List
END

# Update GUI config
[ ! -e /usr/share/desktop-base/profiles/xdg-config/xfce4 ] || cp -au /usr/share/desktop-base/profiles/xdg-config/xfce4 /home/hacker/.config/
