import base64

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from itsdangerous.exc import BadSignature, BadTimeSignature, SignatureExpired
from markupsafe import Markup

from ..api.v1.auth import lookup_login, registration_errors
from ..models import Users, db, get_config, verify_password
from ..utils import email, registration_visible, unserialize
from ..utils.decorators import ratelimit
from ..utils.email import can_send_mail
from ..utils.user import audit_log, authed, clear_user_session, login_user, logout_user
from ..utils.validators import is_safe_url


auth = Blueprint("auth", __name__)

REGISTRATION_MESSAGES = {
    "email_invalid": "Please enter a valid email address",
    "email_domain": "Your email address is not from an allowed domain",
    "name_taken": "That user name is already taken",
    "name_is_email": "Your user name cannot be an email address",
    "email_taken": "That email has already been used",
    "password_empty": "Pick a longer password",
    "password_long": "Pick a shorter password",
    "name_empty": "Pick a longer user name",
}


@auth.route("/confirm", methods=["POST", "GET"])
@auth.route("/confirm/<data>", methods=["POST", "GET"])
@ratelimit(method="POST", limit=10, interval=60)
def confirm(data=None):
    if not get_config("verify_emails"):
        return redirect(url_for("challenges.listing"))

    if data and request.method == "GET":
        try:
            user_email = unserialize(data, max_age=1800)
        except (BadTimeSignature, SignatureExpired):
            return render_template("confirm.html", errors=["Your confirmation link has expired"])
        except (BadSignature, TypeError, base64.binascii.Error):
            return render_template("confirm.html", errors=["Your confirmation token is invalid"])

        user = Users.query.filter_by(email=user_email).first_or_404()
        if user.verified:
            return redirect(url_for("views.settings"))

        user.verified = True
        audit_log("registrations", f"successful confirmation for {user.name}")
        db.session.commit()
        clear_user_session(user_id=user.id)
        email.successful_registration_notification(user.email)
        db.session.close()

        if authed():
            return redirect(url_for("challenges.listing"))
        return redirect(url_for("auth.login"))

    if authed() is False:
        return redirect(url_for("auth.login"))

    user = Users.query.filter_by(id=session["id"]).first_or_404()
    if user.verified:
        return redirect(url_for("views.settings"))

    if data is None:
        if request.method == "POST":
            email.verify_email_address(user.email)
            audit_log("registrations", f"{user.name} initiated a confirmation email resend")
            return render_template("confirm.html", infos=[f"Confirmation email sent to {user.email}!"])
        elif request.method == "GET":
            return render_template("confirm.html")


@auth.route("/reset_password", methods=["POST", "GET"])
@auth.route("/reset_password/<data>", methods=["POST", "GET"])
@ratelimit(method="POST", limit=10, interval=60)
def reset_password(data=None):
    if can_send_mail() is False:
        return render_template("reset_password.html", errors=[Markup(
            "This CTF is not configured to send email.<br> Please contact an organizer to have your password reset.")])

    if data is not None:
        try:
            email_address = unserialize(data, max_age=1800)
        except (BadTimeSignature, SignatureExpired):
            return render_template("reset_password.html", errors=["Your link has expired"])
        except (BadSignature, TypeError, base64.binascii.Error):
            return render_template("reset_password.html", errors=["Your reset token is invalid"])

        if request.method == "GET":
            return render_template("reset_password.html", mode="set")

        if request.method == "POST":
            password = request.form.get("password", "").strip()
            user = Users.query.filter_by(email=email_address).first_or_404()

            if user.oauth_id:
                return render_template("reset_password.html", infos=[
                    "Your account was registered via an authentication provider and does not have an associated password. Please login via your authentication provider."])

            if len(password) == 0:
                return render_template("reset_password.html", errors=["Please pick a longer password"])

            user.password = password
            db.session.commit()
            clear_user_session(user_id=user.id)
            audit_log("logins", f"successful password reset for {user.name}")
            db.session.close()

            email.password_change_alert(user.email)
            return redirect(url_for("auth.login"))

    if request.method == "POST":
        email_address = request.form["email"].strip()
        user = Users.query.filter_by(email=email_address).first()

        if not user:
            return render_template("reset_password.html", infos=[
                "If that account exists you will receive an email, please check your inbox"])

        if user.oauth_id:
            return render_template("reset_password.html", infos=[
                "The email address associated with this account was registered via an authentication provider and does not have an associated password. Please login via your authentication provider."])

        email.forgot_password(email_address)

        return render_template("reset_password.html", infos=[
            "If that account exists you will receive an email, please check your inbox"])

    return render_template("reset_password.html")


@auth.route("/register", methods=["POST", "GET"])
@ratelimit(method="POST", limit=10, interval=5)
def register():
    if not registration_visible():
        abort(404)
    if authed():
        return redirect(url_for("challenges.listing"))
    num_users_limit = int(get_config("num_users", default=0))
    if num_users_limit and Users.query.filter_by(banned=False, hidden=False).count() >= num_users_limit:
        abort(403, description=f"Reached the maximum number of users ({num_users_limit}).")
    if request.method != "POST":
        return render_template("register.html", errors=[])

    name = request.form.get("name", "").strip()
    email_address = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    errors = []
    registration_code = get_config("registration_code")
    if registration_code and request.form.get("registration_code", "").lower() != str(registration_code).lower():
        errors.append("The registration code you entered was incorrect")
    failed = registration_errors(name, email_address, password)
    errors += [message for code, message in REGISTRATION_MESSAGES.items() if code in failed]
    if errors:
        return render_template("register.html", errors=errors, name=request.form["name"],
                               email=request.form["email"], password=request.form["password"])

    user = Users(name=name, email=email_address, password=password)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    if can_send_mail() and get_config("verify_emails"):
        audit_log("registrations", f"{user.name} registered (UNCONFIRMED) with {user.email}")
        email.verify_email_address(user.email)
        db.session.close()
        return redirect(url_for("auth.confirm"))
    if can_send_mail():
        email.successful_registration_notification(user.email)
    audit_log("registrations", f"{user.name} registered with {user.email}")
    db.session.close()
    return redirect(url_for("challenges.listing"))


@auth.route("/login", methods=["POST", "GET"])
@ratelimit(method="POST", limit=10, interval=5)
def login():
    if request.method != "POST":
        db.session.close()
        return render_template("login.html", errors=[])
    user = lookup_login(request.form["name"])
    if user and user.password is None:
        return render_template("login.html", errors=[
            "Your account was registered with a 3rd party authentication provider. "
            "Please try logging in with a configured authentication provider."])
    if user and verify_password(request.form["password"], user.password):
        session.regenerate()
        login_user(user)
        audit_log("logins", f"{user.name} logged in")
        db.session.close()
        if request.args.get("next") and is_safe_url(request.args.get("next")):
            return redirect(request.args.get("next"))
        return redirect(url_for("challenges.listing"))
    if user:
        audit_log("logins", f"submitted invalid password for {user.name}")
    else:
        audit_log("logins", "submitted invalid account information")
    db.session.close()
    return render_template("login.html", errors=["Your username or password is incorrect"])


@auth.route("/logout")
def logout():
    if authed():
        logout_user()
    return redirect(url_for("views.static_html"))
