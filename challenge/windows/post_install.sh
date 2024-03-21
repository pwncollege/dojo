#!/usr/bin/bash
#!/usr/bin/bash

CON="NOPE"
while [[ $CON != *"SSH"* ]]; do
  CON=$(netcat -w10 127.0.0.1 2222)
  echo $CON
done

scp -o "StrictHostKeyChecking=no" -P2222 /opt/windows/post_install.ps1 hacker@127.0.0.1:
scp -o "StrictHostKeyChecking=no" -P2222 /opt/windows/startup.ps1 "hacker@127.0.0.1:\"C:/Program Files/Common Files/\""
scp -o "StrictHostKeyChecking=no" -P2222 /opt/windows/challenge-proxy.c "hacker@127.0.0.1:\"C:/Program Files/Common Files/\""
ssh -o "StrictHostKeyChecking=no" -p2222 hacker@127.0.0.1 -- ./post_install.ps1
