{ pkgs }:

pkgs.writeScriptBin "dojo" ''
  #!${pkgs.python3}/bin/python3

  import json
  import sys
  import os
  import argparse
  import urllib.request
  import urllib.error
  
  CTFD_URL = "http://ctfd:8000"
  
  def submit_flag(flag):
      if int(open("/run/dojo/sys/workspace/privileged").read()):
          print("Error: workspace is in practice mode. Flag submission disabled.")
          return 1

      auth_token = os.environ.get("DOJO_AUTH_TOKEN")
      if not auth_token:
          print("Error: Authentication token not found (DOJO_AUTH_TOKEN not set)")
          return 1
          
      try:
          request_data = {
              "auth_token": auth_token,
              "submission": flag
          }
          
          req = urllib.request.Request(
              f"{CTFD_URL}/pwncollege_api/v1/integrations/solve",
              data=json.dumps(request_data).encode(),
              headers={"Content-Type": "application/json"}
          )
          
          response = urllib.request.urlopen(req, timeout=10)
          result = json.loads(response.read().decode())
          
          if response.status == 200:
              if result.get("status") == "already_solved":
                  print("✓ You already solved this challenge!")
              else:
                  print("✓ Congratulations! Flag accepted!")
              return 0
          else:
              print(f"✗ {result.get('message', result.get('status', 'Flag submission failed'))}")
              return 1
              
      except urllib.error.HTTPError as e:
          result = json.loads(e.read().decode())
          print(f"✗ {result.get('message', result.get('status', 'Flag submission failed'))}")
          return 1
      except urllib.error.URLError as e:
          print(f"Error: Unable to connect to CTFd service: {e}")
          return 1
      except Exception as e:
          print(f"Error: {e}")
          return 1
  
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
