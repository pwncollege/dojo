# Docker Registry

This document describes the DOJO private Docker Registry, the token auth server, certificate options (ACME vs static), the CTFd verification endpoint, and client usage.

## Overview

- Host: `registry.<domain>` served by `nginx-proxy`
- Auth server: `/auth/token` on the same host (path-based) backed by `registry-auth`
- Tokens: RS256 JWTs with a KID header that the registry uses to select the correct verification key
- CTFd verify: `registry-auth` validates user creds and authorization by calling CTFd at `/pwncollege_api/v1/registry/verify`


## Environment and Secrets

- `REGISTRY_API_SECRET`: shared secret used by `registry-auth` to call CTFd’s verify endpoint
  - Must be identical in both `ctfd` and `registry-auth`
- `CTFD_URL`: URL of the CTFd service as seen from `registry-auth` (e.g., `http://ctfd:8000`)
- Token parameters (consistent between services, single-host example):
  - Registry: `REGISTRY_AUTH_TOKEN_REALM=https://registry.pwn.college/auth/token`
  - Registry: `REGISTRY_AUTH_TOKEN_SERVICE=registry.pwn.college`
  - Registry: `REGISTRY_AUTH_TOKEN_ISSUER=registry.pwn.college`
  - Auth: `TOKEN_SERVICE=registry.pwn.college`, `TOKEN_ISSUER=registry.pwn.college`

## Nginx Proxy Routes

`dojo/nginx-proxy/etc/nginx/vhost.d/registry.localhost.pwn.college` illustrates path-based routing (replace with your domain in production):

- `/v2/` → `registry:5000`
- `/auth/token` → `registry-auth:8080`

This single host setup lets Docker clients talk to both the registry and the token server at `https://registry.pwn.college`.

## CTFd Verify Endpoint

- Path: `POST /pwncollege_api/v1/registry/verify`
- Headers: `Authorization: Bearer <REGISTRY_API_SECRET>`, `Content-Type: application/json`
- Body:
  - `username` (CTFd username or email)
  - `password` (CTFd password)
  - `repository` (from the Docker auth scope; e.g., `forensics-4b8112d0/myimage`)
  - `actions` (requested actions array; e.g., `["push","pull"]`)
- Behavior:
  - AuthN: verifies the pwn.college user credentials against CTFd
  - Repo format: requires first path segment `<dojo_id>-<8hex>`
  - Dojo mapping: `<dojo_id>-<hex>` maps to Reference ID `<dojo_id>~<hex>`
  - Push authZ: only Dojo admins for that dojo (or global CTFd admins) may push
  - Pull policy: authenticated users may pull (configurable if needed)
- Response:
  - 200 `{ "success": true, "allowed": ["pull","push"] }` (subset of requested actions)
  - 401 `{ "success": false, "error": "Invalid credentials" }`
  - 403 `{ "success": false, "error": "Invalid repository format" | "Dojo not found" | "Not authorized" }`

## Image Naming Rules

- Use the dojo’s Reference ID from the admin page (e.g., `forensics~4b8112d0`)
- Convert to repo prefix by replacing `~` with `-` (tilde is not allowed by Docker):
  - `forensics-4b8112d0/<your-image>:<tag>`
- If the format is violated, the verify endpoint returns 403 with a hint

## Client Usage

Login to the registry and push:

```sh
docker login registry.pwn.college
docker tag yourimage registry.pwn.college/forensics-4b8112d0/yourimage:latest
docker push registry.pwn.college/forensics-4b8112d0/yourimage:latest
```

Pull:

```sh
docker pull registry.pwn.college/forensics-4b8112d0/yourimage:latest
```

## Image Puller 

I have made minimal changes to the current image puller implementation. Rather than pulling from docker hub, it now pulls from our registry.

## Production Checklist

- Set `DOJO_ENV=production`, `DOJO_HOST=<dojo.domain>`
- ACME: enable `acme-companion`, use `certs` volume, set `LETSENCRYPT_HOST` per service
- Ensure `REGISTRY_API_SECRET` is identical in `ctfd` and `registry-auth`
- Mount JWT public cert to the registry at `/auth/jwt.crt`. The correct format for creating is listed below.
- Confirm vhost routes for `/v2/` and `/auth/token`
- If you change `REGISTRY_AUTH_TOKEN_ISSUER`, remember to change the auth service token issuer variable.

## Private Docker Registry with Token Auth (Correct KID + Cert Flow)

### Why these exact certificates and KID matter

### Two separate concerns

1. **TLS trust for the realm (`/auth/token`)**  
    The registry (and clients via your reverse proxy) must trust the HTTPS endpoint that issues tokens. We mount a CA (or the server cert itself) into the registry via `REGISTRY_AUTH_TOKEN_ROOTCERTBUNDLE=/auth/jwt.crt`. If this trust path is wrong, the registry won’t fetch tokens.
    
2. **JWT verification key + KID**  
    The registry verifies JWTs using the token’s `kid` header to select the right public key material. The KID is derived from **only the public key DER** (SubjectPublicKeyInfo), not the full X.509 certificate. Hashing the whole certificate gives the wrong KID and you’ll loop on 401s forever.
    

**KID algorithm (exactly what we implement):**

- Take the **DER of the public key** (not the cert!)
    
- SHA-256 hash → **truncate to 30 bytes (240 bits)**
    
- Base32 encode (uppercase A–Z, 2–7), **strip `=` padding**
    
- Insert `:` every 4 characters → 12 groups (48 chars total)
    

### JWT Key Management

- Generate a dedicated keypair (do not reuse TLS/ACME keys):
  - `openssl genrsa -out auth-keys/jwt/private.key 2048`
  - `openssl req -new -x509 -key auth-keys/jwt/private.key -out auth-keys/jwt/public.crt -days 365 -subj "/CN=registry-token"`
- Mounts:
  - `registry-auth`: `./auth-keys/jwt:/keys:ro`
  - `registry`: `./auth-keys/jwt:/auth:ro` (so `/auth/jwt.crt` is present)


## Troubleshooting

- `docker logs nginx-proxy` – reverse proxy and ACME logs
- `docker logs registry` – registry errors (JWT, token fetch, catalog)
- `docker logs registry-auth` – token server, CTFd verify responses
- `docker logs ctfd` – CTFd logs (verify endpoint).

## Migrations

To migrate legacy images previously pushed to Docker Hub into the new registry:

- Export a list of legacy images and their intended Reference IDs (e.g., from the database `DojoChallenges.data["image"]`).
- For each image, construct the new repository name using the dojo Reference ID: `forensics~4b8112d0` → `forensics-4b8112d0/<image>:<tag>`.
- Authenticate to `registry.pwn.college` as a global admin (global admins may push to any repo).
- Pull, retag, and push each image to the new registry.

## Things to verify:

- Duplicate Images Across Different Users
    - As higlighted by robwaz there is an open question regarding the handling of duplicate images pushed by different users.
    - For example, consider the following scenario:
        - User `test` pushes an image named `testdojo-<dojoid>/legacy`.
        - User `adical` pushes an image named `adicaldojo:<dojoid>/legacy`. 
    
    - While both images are identical (e.g., equivalent to pwncollege/legacy), the registry would still store them as separate physical images because they were built on different machines at different timestamps.
    - Storage optimization only occurs when images are exactly identical.

- Registry Login Flow
    - The original login mechanism for the registry used `update_code` as the password. This approach has not been implemented in the current PR due to two primary concerns:
        1. The administrator flow was functional but inefficient.
        2. There was no clear mechanism to prevent a former dojo administrator (who has since been removed) from continuing to push images to the associated dojo.
    - To address these issues, a new login flow has been implemented, as detailed above.

## Future work:

### Work on the Image puller:
 - Once the registry is working on production, Work on a followup PR with a more efficient mechanism for pulling the images.

