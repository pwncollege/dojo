#!/usr/bin/env python3

import socket
import os
import json
import logging
import threading
import struct
import traceback
from pathlib import Path

import docker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SOCKET_PATH = "/var/run/dojo-command/socket"
CTFD_URL = "http://ctfd:8000"


class DojoSocketService:
    def __init__(self):
        self.docker_client = docker.from_env()
        
    def start(self):
        os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
        
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
            
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666)
        server.listen(5)
        
        logger.info(f"Dojo socket service listening on {SOCKET_PATH}")
        
        while True:
            try:
                conn, _ = server.accept()
                thread = threading.Thread(target=self.handle_client, args=(conn,))
                thread.daemon = True
                thread.start()
            except Exception as e:
                logger.error(f"Error accepting connection: {e}")
                
    def handle_client(self, conn):
        try:
            data = self.recv_message(conn)
            if not data:
                return
                
            request = json.loads(data.decode())
            command = request.get("command")
            
            if command == "submit_flag":
                response = self.handle_submit_flag(request)
            else:
                response = {"success": False, "error": "Unknown command"}
                
            self.send_message(conn, json.dumps(response).encode())
            
        except Exception as e:
            logger.error(f"Error handling client: {e}")
            logger.error(traceback.format_exc())
            error_response = {"success": False, "error": "Internal server error"}
            try:
                self.send_message(conn, json.dumps(error_response).encode())
            except:
                pass
        finally:
            conn.close()
            
    def recv_message(self, conn):
        length_data = conn.recv(4)
        if len(length_data) != 4:
            return None
        length = struct.unpack("!I", length_data)[0]
        
        data = b""
        while len(data) < length:
            chunk = conn.recv(min(length - len(data), 4096))
            if not chunk:
                return None
            data += chunk
        return data
        
    def send_message(self, conn, data):
        conn.sendall(struct.pack("!I", len(data)) + data)
        
    def handle_submit_flag(self, request):
        auth_token = request.get("auth_token")
        flag = request.get("flag")
        
        if not all([auth_token, flag]):
            return {"success": False, "error": "Missing required parameters"}
        
        import requests
        
        try:
            response = requests.post(
                f"{CTFD_URL}/pwncollege_api/v1/integrations/solve",
                json={"auth_code": auth_token, "submission": flag},
                timeout=10
            )
            
            result = response.json()
            
            if response.status_code == 200:
                if result.get("status") == "already_solved":
                    return {"success": True, "message": "You already solved this challenge!"}
                else:
                    return {"success": True, "message": "Congratulations! Flag accepted!"}
            else:
                return {"success": False, "message": result.get("message", result.get("status", "Flag submission failed"))}
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling solve API: {e}")
            return {"success": False, "error": "Failed to submit flag to server"}
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {"success": False, "error": "Internal server error"}


if __name__ == "__main__":
    service = DojoSocketService()
    service.start()
