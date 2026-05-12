import hashlib


def ssh_link_token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()
