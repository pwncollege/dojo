{ pkgs }:

# This creates the /run/dojo/bin/dojo command available in user containers
# The command communicates with the socket service running in the CTFd container
pkgs.writeScriptBin "dojo" ''
  #!${pkgs.python3}/bin/python3

  import socket
  import json
  import sys
  import os
  import struct
  import argparse
  
  SOCKET_PATH = "/run/dojo/socket"
  
  def send_message(sock, data):
      sock.sendall(struct.pack("!I", len(data)) + data)
      
  def recv_message(sock):
      length_data = sock.recv(4)
      if len(length_data) != 4:
          return None
      length = struct.unpack("!I", length_data)[0]
      
      data = b""
      while len(data) < length:
          chunk = sock.recv(min(length - len(data), 4096))
          if not chunk:
              return None
          data += chunk
      return data
  
  def submit_flag(flag):
      if not os.path.exists(SOCKET_PATH):
          print("Error: Dojo socket not available. Are you running this inside a challenge container?")
          return 1
          
      if int(open("/run/dojo/sys/workspace/privileged").read()):
          print("Error: workspace is in practice mode. Flag submission disabled.")
          return 1

      auth_token = os.environ.get("DOJO_AUTH_TOKEN")
      if not auth_token:
          print("Error: Authentication token not found (DOJO_AUTH_TOKEN not set)")
          return 1
          
      try:
          sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
          sock.connect(SOCKET_PATH)
          
          request = {
              "command": "submit_flag",
              "auth_token": auth_token,
              "flag": flag
          }
          
          send_message(sock, json.dumps(request).encode())
          response_data = recv_message(sock)
          
          if not response_data:
              print("Error: No response from server")
              return 1
              
          response = json.loads(response_data.decode())
          
          if response.get("success"):
              print(f"✓ {response.get('message', 'Flag submitted successfully!')}")
              return 0
          else:
              print(f"✗ {response.get('message', 'Unknown error')}")
              return 1
              
      except socket.error as e:
          print(f"Error: Unable to connect to dojo service: {e}")
          return 1
      except Exception as e:
          print(f"Error: {e}")
          return 1
      finally:
          sock.close()
  
  def main():
      parser = argparse.ArgumentParser(
          description="Dojo command-line tool for pwn.college",
          prog="dojo"
      )
      
      subparsers = parser.add_subparsers(dest="command", help="Available commands")
      
      submit_parser = subparsers.add_parser("submit", help="Submit a flag")
      submit_parser.add_argument("flag", help="The flag to submit")
      
      args = parser.parse_args()
      
      if args.command == "submit":
          return submit_flag(args.flag)
      else:
          parser.print_help()
          return 1
  
  if __name__ == "__main__":
      sys.exit(main())
''
