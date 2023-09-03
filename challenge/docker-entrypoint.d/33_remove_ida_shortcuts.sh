#!/bin/sh

# delete shortcuts to IDA if IDA is not installed
if [ ! -d /opt/ida ]
then
    rm -rf /home/hacker/.config/xfce4/panel/launcher-13
    [ ! -f /home/hacker/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml ] || sed -i -e '/<property name="plugin-13" type="string" value="launcher">/,/<\/property>/d' /home/hacker/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
fi
