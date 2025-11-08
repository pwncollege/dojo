In this file we're going to explain what each endpoint in the dojo means.

Note that we're only going to take a look at the endpoints under `dojo_plugin/api/v1`.

Definitions

1. `API_PATH` - https::/pwn.college/pwncollege_api/v1. All endpoints start with this path.

**auth**

***/register***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/auth.py#L17
Accepted Methods: `POST`.
Required Parameters: `name`, `email`, `password`.
Optional Parameters: `website`, `affiliation`, `country`, `registration_code`.
Description: This endpoint is responsible for creating new users.

****1. Get registration data****

```
req = request.get_json()
errors = []

# Get registration data
name = req.get("name", "").strip()
email_address = req.get("email", "").strip().lower()
password = req.get("password", "").strip()
website = req.get("website")
affiliation = req.get("affiliation")
country = req.get("country")
```

We simply get the registration data from the request.

****2. Check user limit****

```
# Check user limit
num_users_limit = int(get_config("num_users", default=0))
num_users = Users.query.filter_by(banned=False, hidden=False).count()
if num_users_limit and num_users >= num_users_limit:
    return {"success": False, "errors": [f"Reached maximum users ({num_users_limit})"]}, 403
```

This gets the maximum amount of users allowed from the configuration and assigns it to `num_users_limit`.
It then gets the current amount of users with a database query and assigns it to `num_users`.
Then, it check whether we passed that limit and throws an error if so.

****3. Validation****

```
# Validation
if len(name) == 0:
    errors.append("Please provide a username")
if Users.query.filter_by(name=name).first():
    errors.append("That username is already taken")
if validators.validate_email(name):
    errors.append("Username cannot be an email address")

if not validators.validate_email(email_address):
    errors.append("Please enter a valid email address")
if Users.query.filter_by(email=email_address).first():
    errors.append("That email is already registered")
if not email.check_email_is_whitelisted(email_address):
    errors.append("Email address is not from an allowed domain")

if len(password) == 0:
    errors.append("Please provide a password")
if len(password) > 128:
    errors.append("Password is too long")

if website and not validators.validate_url(website):
    errors.append("Website must be a valid URL")

if country:
    try:
        validators.validate_country_code(country)
    except ValidationError:
        errors.append("Invalid country")

if affiliation and len(affiliation) > 128:
    errors.append("Affiliation is too long")
```

This part makes sure the parameters are valid. The requirements are:

1. name - must be longer than 0 characters, unique and not an email address.
2. email address - must be a valid email address, not already registered and from an allowed domain.
3. password - must be longer than 0 characters, and shorter than 128.
4. website - must be a valid url.
5. country - must be a valid country code
6. affiliation - must be shorter than 128 characters.

****4. Check registration code****

```
# Check registration code if required
if get_config("registration_code"):
    registration_code = req.get("registration_code", "")
    if registration_code.lower() != str(get_config("registration_code", "")).lower():
        errors.append("Invalid registration code")
```

This part checks whether `registration_code` exists in the configuration. If it does, it compares it
against a user supplied `registration_code`.


****5. Process custom fields****

```
# Process custom fields
fields = {}
for field in UserFields.query.all():
    field_value = req.get(f"fields[{field.id}]", "").strip()
    if field.required and not field_value:
        errors.append(f"Field '{field.name}' is required")
    fields[field.id] = field_value
```

This part runs through every field in `UserFields`, and checks whether it is was providedbu the user.
If it wasn't, and that field is required, we throw an error. otherwise, we assign `fields[field.id]` to it.

****6. Raise errors****

```
if errors:
    return {"success": False, "errors": errors}, 400
```

This part checks whether we got an error in any previous step, and returns a list containing those errors
if so.

****7. Create user****

```
# Create user
user = Users(name=name, email=email_address, password=password)
if website:
    user.website = website
if affiliation:
    user.affiliation = affiliation
if country:
    user.country = country

db.session.add(user)
db.session.commit()
```

This part is responsible for creating the user. We first create a new `User` instance, and then add
`website`, `affiliation`, and `country` if they exist.

****8. Add custom field entries****

```
# Add custom field entries
for field_id, value in fields.items():
    entry = UserFieldEntries(
        field_id=field_id,
        value=value,
        user_id=user.id
    )
    db.session.add(entry)
db.session.commit()
```

This part is responsible for adding the custom fields we added in step 5 to the user.

****9. Send verification email****

```
# Send verification email if configured
if get_config("verify_emails") and can_send_mail():
    email.verify_email_address(user.email)
    verified = False
else:
    user.verified = True
    db.session.commit()
    verified = True
    if can_send_mail():
        email.successful_registration_notification(user.email)
```

This part checks whether "verify_emails" is enabled in the configuration and whether we can send the email.
If both are True, we send the email and set `verified` to False. Otherwise, we set `verified` to True,
and if we can an email, we send a successful registration notification.

****10. Set session****

```
# Set session
session["id"] = user.id
session["name"] = user.name
session["type"] = user.type
session["verified"] = verified
session.permanent = True
```

This part sets the `id`, `name`, `type`, `verified` and `permanent` variables in the session object.

****11. Return****

```
return {
    "success": True,
    "data": {
        "user_id": user.id,
        "username": user.name,
        "email": user.email,
        "verified": verified
    }
}
```

Finally, we return the `user.id`, `user.name`, `user.email`, and `verfied` that we got earlier in the
function.

***/login***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/auth.py#L148
Accepted Methods: `POST`.
Required Parameters: `name`, `password`.
Optional Parameters: None.
Description: This endpoint is responsible for logging in to existing accounts.

****1. Get login data****

```
req = request.get_json()
name = req.get("name", "").strip()
password = req.get("password", "").strip()
```

This part assigns the `name` and `password` variables to the user supplied `name` and `password`.

****2. Check if `name` is an email or a username****

```
# Check if email or username
if validators.validate_email(name):
    user = Users.query.filter_by(email=name).first()
else:
    user = Users.query.filter_by(name=name).first()
```

This part checks whether the `name` variable is an email or a username, and gets the user based on that
(either by filtering via email or via username).

****3. Check whether user exists****

```
if user:
```

This if statement simply checks if the user we got from step 2 exists. Both step 4 and step 5 will
happen inside this if statement.

****4. Check whether account is registered via OAuth****

```
if user.password is None:
    return {
        "success": False,
        "errors": ["Account registered via OAuth. Please use OAuth to login"]
    }, 401
```

This part checks whether the user has a password. If he doesn't, we raise an error saying that the
account is registered via OAuth.

****5. Verify password****

```
if verify_password(password, user.password):
    # Set session
    session["id"] = user.id
    session["name"] = user.name
    session["type"] = user.type
    session["verified"] = user.verified
    session.permanent = req.get("remember_me", False)

    return {
        "success": True,
        "data": {
            "user_id": user.id,
            "username": user.name,
            "email": user.email,
            "type": user.type,
            "verified": user.verified,
            "team_id": user.team_id
        }
    }
```

This part checks whether the password is correct, and if so, it sets the session variables `id`,
`name`, `type`, `verified` and `permanent`. Then we return `user.id`, `user.name`, `user.type`,
`user.verified`, and `user.team_id`.

****6. Return****

```
return {"success": False, "errors": ["Invalid credentials"]}, 401
```

This part happens when the part before it don't return, meaning the account is not registered via
OAuth and the password is incorrect.

***/logout***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/auth.py#L198
Accepted Methods: `POST`.
Required Parameters: None.
Optional Parameters: None.
Description: This endpoint is responsible for handling logout.

****1. Clear session****

```
session.clear()
```

This part clears the contents of a session, effectively logging the user out.

****2. Return****

```
return {
    "success": True,
    "data": {"message": "Successfully logged out"}
}
```

This part is responsible for returning a success message saying: "Successfully logged out".

***/verify/<token>***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/auth.py#L214
Accepted Methods: `GET`.
Required Parameters: `token`.
Optional Parameters: None.
Description: This endpoint is responsible for verifying an email address with a token.

****1. Get user email from token****

```
"""Verify email with token"""
try:
    user_email = unserialize(token, max_age=1800)
except (BadTimeSignature, SignatureExpired):
    return {"success": False, "errors": ["Your confirmation link has expired"]}, 400
except (BadSignature, TypeError, base64.binascii.Error):
    return {"success": False, "errors": ["Your confirmation token is invalid"]}, 400
```

This part uses the `unserialize` function to get the email from the token. You can think of `token` as an
encrypted email, and `unserialize` decrypts it and puts the result in `user_email`.

****2. Check whether user exists****

```
user = Users.query.filter_by(email=user_email).first()
if not user:
    return {"success": False, "errors": ["User not found"]}, 404
``` 

This part queries the database for a user with the provided email address. If it doesn't exist, we return
an error.

****3. Check whether the user is already verified****

```
if user.verified:
    return {"success": True, "data": {"message": "Email already verified"}}
```

This part checks whether the user is already verified. If he is, we return an error.

****4. Verify user****

```
user.verified = True
db.session.commit()

if can_send_mail():
    email.successful_registration_notification(user.email)
```

This part is responsible for verifying the user. It sets `user.verified` to True, and sends a successful
registration notification if it can.

****5. Return****

```
return {
    "success": True,
    "data": {"message": "Email successfully verified"}
}
```

This part returns a success message saying: "Email successfully verified".

***/forgot-password***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/auth.py#L251
Accepted Methods: `POST`.
Required Parameters: None.
Optional Parameters: None.
Description: This endpoint is responsible for sending a reset password link to some email.

****1. Get email****

```
req = request.get_json()
email_address = req.get("email", "").strip()
```

This part assigns `email_address` to the user supplied `email`.

****2. Get user****

```
user = Users.query.filter_by(email=email_address).first()
```

This part queries the database to find a user with this email address.

****3. Send reset link****

```
if user and not user.oauth_id:
    email.forgot_password(email_address)
```

This part checks whether the user exists and whether he's not registered via OAuth. If both are True, we
send a forgot password link to the provided email from step 1.

****4. Return****

```
# Always return success to avoid user enumeration
return {
    "success": True,
    "data": {"message": "If the account exists, a reset email has been sent"}
}
```

This part returns a success message saying: "If the account exists, a reset email has been sent".

***/reset-password/<token>***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/auth.py#L281
Accepted Methods: `POST`.
Required Parameters: `token`, `password`.
Optional Parameters: None.
Description: This endpoint is responsible for changing the password of a user.

****1. Get email address from token****

```
"""Reset password with token"""
try:
    email_address = unserialize(token, max_age=1800)
except (BadTimeSignature, SignatureExpired):
    return {"success": False, "errors": ["Your reset link has expired"]}, 400
except (BadSignature, TypeError, base64.binascii.Error):
    return {"success": False, "errors": ["Your reset token is invalid"]}, 400
```

This part uses the `unserialize` function to get the email from the token. You can think of `token` as an
encrypted email, and `unserialize` decrypts it and puts the result in `email_address`.

****2. Get password from user****

```
req = request.get_json()
password = req.get("password", "").strip()
```

This parts assigns the `password` variable to the user supplied `password`.

****3. Password validation****

```
if len(password) == 0:
    return {"success": False, "errors": ["Please provide a password"]}, 400

if len(password) > 128:
    return {"success": False, "errors": ["Password is too long"]}, 400
```

This part checks whether the password is valid. It does so with the following two checks:

1. Length must not be 0
2. Length must be less than 128

****4. Get user****

```
user = Users.query.filter_by(email=email_address).first()
if not user:
    return {"success": False, "errors": ["User not found"]}, 404
```

This part queries the database to find a user with `email_address`. If it didn't a user with that email
address, it returns an error.

****5. Check if account is registered via OAuth

```
if user.oauth_id:
    return {
        "success": False,
        "errors": ["Account registered via OAuth cannot reset password"]
    }, 400
```

This part checks whether the account is registered via OAuth. If it is, we return an error.

****6. Change passowrd****

```
user.password = password
db.session.commit()
```

This part assigns `user.password` to the user supplied `password`.

****7. Send password change alert email****

```
if can_send_mail():
    email.password_change_alert(user.email)
```

This part checks whether it can send an email, and if it can, it sends a password change alert email to
`user.email`.

****8. Return****

```
return {
    "success": True,
    "data": {"message": "Password successfully reset"}
}
```

This part returns a success message saying: "Password successfully reset".
