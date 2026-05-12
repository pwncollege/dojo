import base64

from sshpubkeys import SSHKey, InvalidKeyError


def normalize_ssh_key(key_value):
    key = SSHKey(key_value, strict=True)
    key.parse()
    return f"{key.key_type.decode()} {base64.b64encode(key._decoded_key).decode()}"


def normalize_offered_ssh_key(key_type, key_base64):
    return normalize_ssh_key(f"{key_type} {key_base64}")


__all__ = ["InvalidKeyError", "normalize_ssh_key", "normalize_offered_ssh_key"]
