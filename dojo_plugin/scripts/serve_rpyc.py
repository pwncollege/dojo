import rpyc
import sys
import os

origstdin = sys.stdin
origstdout = sys.stdout
sys.stdin = open(os.devnull, "r")
sys.stdout = open("/tmp/rpyc-stdout", "w")
sys.stderr = open("/tmp/rpyc-stderr", "w")
conn = rpyc.utils.factory.connect_pipes(origstdin, origstdout, service=rpyc.core.service.ClassicService, config={'sync_request_timeout':None})
