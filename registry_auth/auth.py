#!/usr/bin/env python3

import os
import base64
import hashlib
import datetime
import secrets
import logging
import requests

from flask import Flask, request, jsonify, abort
from OpenSSL import crypto
import jwt
 
app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)




PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", "/keys/private.key")
PUBLIC_KEY_PATH  = os.getenv("PUBLIC_KEY_PATH",  "/keys/public.key")
ISSUER           = os.getenv("TOKEN_ISSUER")
SERVICE          = os.getenv("TOKEN_SERVICE")
# DATABASE_URL     = os.getenv("DATABASE_URL")
TTL              = int(os.getenv("TOKEN_TTL_SECONDS", "3600"))


with open(PRIVATE_KEY_PATH, "rb") as f:
    PRIVATE_KEY = f.read()

try:
    with open(PUBLIC_KEY_PATH, "rb") as f:
        PUBLIC_KEY = f.read()
except Exception as e:
    app.logger.warning(f"could not load PUBLIC_KEY ({e}), PUBLIC_KEY disabled")
    PUBLIC_KEY = None


def verify_dojo_access_api(username, password, repository=None, actions=None):
    ctfd_url = os.getenv("CTFD_URL")
    api_secret = os.getenv("REGISTRY_API_SECRET")
    if not ctfd_url or not api_secret:
        app.logger.error("CTFD_URL or REGISTRY_API_SECRET not set")
        return None

    url = f"{ctfd_url.rstrip('/')}/pwncollege_api/v1/registry/verify"
    headers = {"Authorization": f"Bearer {api_secret}", "Content-Type": "application/json"}
    payload = {"username": username, "password": password}
    if repository is not None:
        payload["repository"] = repository
    if actions is not None:
        payload["actions"] = actions
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=5)
        try:
            data = r.json()
        except Exception:
            data = {"error": r.text}
        if r.status_code != 200:
            app.logger.warning(f"ctfd verify failed status={r.status_code} body={data}")
        return r.status_code, data
    except Exception as e:
        app.logger.error(f"error contacting ctfd verify endpoint: {e}")
        return 502, {"error": "Upstream verify endpoint unreachable"}


def create_kid(pem_bytes: bytes) -> str:
    try:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, pem_bytes)
        pkey = cert.get_pubkey()
    except crypto.Error:
        pkey = crypto.load_publickey(crypto.FILETYPE_PEM, pem_bytes)

    der = crypto.dump_publickey(crypto.FILETYPE_ASN1, pkey)
    h = hashlib.sha256(der).digest()[:30]
    b32 = base64.b32encode(h).decode('ascii').rstrip('=')
    return ":".join(b32[i:i+4] for i in range(0, len(b32), 4))


@app.route("/auth/token", methods=["GET"])
def token():
    auth = request.authorization
    if not auth:
        app.logger.error("No authorization provided")
        return abort(401)

    service = request.args.get("service") or SERVICE
    scope   = request.args.get("scope", "")
    access  = []

    repo_name = None
    requested_actions = []
    if scope:
        try:
            typ, name, acts = scope.split(":", 2)
            if typ != "repository":
                return abort(400, "unsupported scope type")
            repo_name = name
            requested_actions = [a for a in acts.split(",") if a]
        except ValueError:
            return abort(400, "invalid scope format")

    access.append({"type": "registry", "name": "catalog", "actions": ["*"]})
    status, verify_res = verify_dojo_access_api(auth.username, auth.password, repo_name, requested_actions)
    if status != 200:
        msg = ""
        if isinstance(verify_res, dict):
            msg = verify_res.get("error") or verify_res.get("message") or ""
        return jsonify(success=False, error=msg), status

    if repo_name is not None:
        allowed = verify_res.get("allowed", requested_actions) if verify_res.get("allowed") is not None else requested_actions
        if not allowed:
            return abort(403)
        access.append({"type": "repository", "name": repo_name, "actions": allowed})
    else:
        pass

    now = datetime.datetime.utcnow()
    iat = int(now.timestamp())
    nbf = int((now - datetime.timedelta(seconds=10)).timestamp())
    exp = int((now + datetime.timedelta(seconds=TTL)).timestamp())
    jti = secrets.token_hex(16)

    payload = {
        "iss": ISSUER,
        "sub": auth.username,
        "aud": service,
        "iat": iat,
        "nbf": nbf,
        "exp": exp,
        "jti": jti,
        "access": access
    }

    headers = None
    if PUBLIC_KEY:
        try:
            kid = create_kid(PUBLIC_KEY)
            headers = {"kid": kid}
        except Exception as e:
            app.logger.warning(f"failed to create kid header ({e}), skipping")

    if headers:
        token_str = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers=headers)
    else:
        token_str = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")

    return jsonify(token=token_str, expires_in=TTL, issued_at=now.isoformat() + "Z")
