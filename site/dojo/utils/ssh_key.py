import base64
import re

from sshpubkeys import SSHKey, InvalidKeyError


KEY_TYPE_RE = re.compile(rb"[\x21-\x2b\x2d-\x7e]{1,64}\Z")


def normalize_ssh_key(key_value):
    if not isinstance(key_value, str):
        raise InvalidKeyError("SSH key must be a string")
    key = SSHKey(key_value, strict=True)
    key.parse()
    if not KEY_TYPE_RE.match(key.key_type):
        raise InvalidKeyError(f"unsupported key type: {key.key_type[:64]!r}")
    return f"{key.key_type.decode()} {base64.b64encode(key._decoded_key).decode()}"


def normalize_offered_ssh_key(key_type, key_base64):
    if not isinstance(key_type, str) or not isinstance(key_base64, str):
        raise InvalidKeyError("SSH key type and data must be strings")
    if any(character.isspace() for character in key_type + key_base64):
        raise InvalidKeyError("SSH key type and data must not contain whitespace")
    return normalize_ssh_key(f"{key_type} {key_base64}")
