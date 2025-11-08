# SSH Key

The `keys` namespace is responsible for managing users' public SSH keys.

***/***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/ssh_key.py#L21
Accepted Methods: `POST`, `DELETE`.
Required Parameters: `ssh_key`.
Optional Parameters: None.
Description: This endpoint is responsible for adding a new SSH key.

****Method: POST****

****1. Get SSH key****

```
data = request.get_json()
key_value = data.get("ssh_key", "")
```

This part assigns the `key_value` variable to the user supplied `ssh_key`.

****2. Parse `key_value`****

```
if key_value:
    try:
        key = SSHKey(key_value, strict=True)
        key.parse()
        key_value = f"{key.key_type.decode()} {base64.b64encode(key._decoded_key).decode()}"
    except (InvalidKeyError, NotImplementedError) as e:
        return (
            {
                "success": False,
                "error": f"Invalid SSH Key, error: <code>{markupsafe.escape(e)}</code> <br>Refer below for how to generate a valid ssh key"
            },
            400,
        )
```

This part tries to parse the provided SSH key, and throws an error if the SSH key is invalid.

****3. Get current user****

```
user = get_current_user()
```

This part uses the `get_current_user` function to assign the `user` variable to the current user.

****4. Add SSH key****

```
try:
    key = SSHKeys(user_id=user.id, value=key_value)
    db.session.add(key)
    db.session.commit()
except IntegrityError:
    db.session.rollback()
    return (
        {"success": False, "error": "SSH Key already in use"},
        400,
    )
```

This part tries to add the parsed SSH key to the user's SSH keys collection. It throws an error if they key
is already in use.

****5. Return****

```
return {"success": True}
```

This part returns `True` if all other parts before it don't return.

****Method: DELETE****

****1. Get SSH key****

```
data = request.get_json()
key_value = data.get("ssh_key", "")
```

This part assigns the `key_value` variable to the user supplied `ssh_key`.

****2. Get current user****

```
user = get_current_user()
```

This part uses the `get_current_user` function to assign the `user` variable to the current user.

****3. Get SSH key****

```
key = SSHKeys.query.filter_by(user=user, value=key_value).first()
if not key:
    return (
        {"success": False, "error": "SSH Key does not exist"},
        400,
    )
```

This part queries the database for the provided SSH key. If it doesn't find it, it returns an error.

****4. Delete SSH key****

```
db.session.delete(key)
db.session.commit()
```

This part deletes the provided SSH key.

****5. Return****

```
return {"success": True}
```

This part returns `True` if all other parts before it don't return.
