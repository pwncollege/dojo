#!/bin/sh

mkdir -p /home/hacker/.ipython/profile_default/startup
cat >/home/hacker/.ipython/profile_default/startup/22-autocomplete.py <<EOF
import IPython
py = IPython.get_ipython()
py.Completer.use_jedi = False
py.Completer.greedy = True
EOF
