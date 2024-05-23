#!/bin/sh

for LAUNCHER in /home/hacker/.config/xfce4/panel/launcher-*
do
        NUMBER=${LAUNCHER##*-}
        EXE=$(cat "$LAUNCHER"/*.desktop | grep Exec | sed -e "s/.*=//")
        if [ ! -f "$EXE" ] && [[ ! "$EXE" =~ " " ]]
        then
                rm -rf "$LAUNCHER"
                sed -i -e '/<property name="plugin-$NUMBER" type="string" value="launcher">/,/<\/property>/d' /home/hacker/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
        fi
done
