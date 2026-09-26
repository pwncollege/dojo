import datetime
from flask import request, session
from flask_restx import Namespace, Resource
from ...models import Users, db, get_config, verify_password
from ...utils import validators, email, registration_visible, unserialize
from ...utils.validators import ValidationError
from ...utils.email import can_send_mail
from ...utils.decorators import ratelimit
from itsdangerous.exc import BadSignature, BadTimeSignature, SignatureExpired
import base64

auth_namespace = Namespace("auth", description="Authentication endpoints")

REGISTRATION_ERRORS = {
    "name_empty": "Please provide a username",
    "name_taken": "That username is already taken",
    "name_is_email": "Username cannot be an email address",
    "email_invalid": "Please enter a valid email address",
    "email_taken": "That email is already registered",
    "email_domain": "Email address is not from an allowed domain",
    "password_empty": "Please provide a password",
    "password_long": "Password is too long",
}


def registration_errors(name, email_address, password):
    checks = {
        "name_empty": len(name) == 0,
        "name_taken": Users.query.filter_by(name=name).first(),
        "name_is_email": validators.validate_email(name),
        "email_invalid": not validators.validate_email(email_address),
        "email_taken": Users.query.filter_by(email=email_address).first(),
        "email_domain": not email.check_email_is_whitelisted(email_address),
        "password_empty": len(password) == 0,
        "password_long": len(password) > 128,
    }
    return {code for code, failed in checks.items() if failed}


def lookup_login(name):
    if validators.validate_email(name):
        return Users.query.filter_by(email=name).first()
    return Users.query.filter_by(name=name).first()


@auth_namespace.route("/register")
class Register(Resource):
    @ratelimit(method="POST", limit=10, interval=5)
    @auth_namespace.doc(
        description="Register a new user and set session",
        responses={
            200: "Success",
            400: "Validation error",
            403: "Registration disabled",
        },
    )
    def post(self):
        if not registration_visible():
            return {"success": False, "errors": ["Registration is currently disabled"]}, 403

        req = request.get_json()
        errors = []

        # Get registration data
        name = req.get("name", "").strip()
        email_address = req.get("email", "").strip().lower()
        password = req.get("password", "").strip()
        website = req.get("website")
        affiliation = req.get("affiliation")
        country = req.get("country")

        # Check user limit
        num_users_limit = int(get_config("num_users", default=0))
        num_users = Users.query.filter_by(banned=False, hidden=False).count()
        if num_users_limit and num_users >= num_users_limit:
            return {"success": False, "errors": [f"Reached maximum users ({num_users_limit})"]}, 403

        failed = registration_errors(name, email_address, password)
        errors = [message for code, message in REGISTRATION_ERRORS.items() if code in failed]

        if website and not validators.validate_url(website):
            errors.append("Website must be a valid URL")

        if country:
            try:
                validators.validate_country_code(country)
            except ValidationError:
                errors.append("Invalid country")

        if affiliation and len(affiliation) > 128:
            errors.append("Affiliation is too long")

        # Check registration code if required
        if get_config("registration_code"):
            registration_code = req.get("registration_code", "")
            if registration_code.lower() != str(get_config("registration_code", "")).lower():
                errors.append("Invalid registration code")

        if errors:
            return {"success": False, "errors": errors}, 400

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

        # Set session
        session["id"] = user.id
        session["name"] = user.name
        session["type"] = user.type
        session["verified"] = verified
        session.permanent = True

        return {
            "success": True,
            "data": {
                "user_id": user.id,
                "username": user.name,
                "email": user.email,
                "verified": verified
            }
        }


@auth_namespace.route("/login")
class Login(Resource):
    @ratelimit(method="POST", limit=10, interval=5)
    @auth_namespace.doc(
        description="Login and set session",
        responses={
            200: "Success",
            401: "Invalid credentials",
        },
    )
    def post(self):
        req = request.get_json()
        name = req.get("name", "").strip()
        password = req.get("password", "").strip()

        user = lookup_login(name)

        if user:
            if user.password is None:
                return {
                    "success": False,
                    "errors": ["Account registered via OAuth. Please use OAuth to login"]
                }, 401

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
                        "team_id": None
                    }
                }

        return {"success": False, "errors": ["Invalid credentials"]}, 401


@auth_namespace.route("/logout")
class Logout(Resource):
    @auth_namespace.doc(
        description="Logout and clear session",
        responses={
            200: "Success",
        },
    )
    def post(self):
        session.clear()
        return {
            "success": True,
            "data": {"message": "Successfully logged out"}
        }


@auth_namespace.route("/verify/<token>")
class VerifyEmail(Resource):
    @auth_namespace.doc(
        description="Verify email address with token",
        responses={
            200: "Success",
            400: "Invalid or expired token",
        },
    )
    def get(self, token):
        """Verify email with token"""
        try:
            user_email = unserialize(token, max_age=1800)
        except (BadTimeSignature, SignatureExpired):
            return {"success": False, "errors": ["Your confirmation link has expired"]}, 400
        except (BadSignature, TypeError, base64.binascii.Error):
            return {"success": False, "errors": ["Your confirmation token is invalid"]}, 400

        user = Users.query.filter_by(email=user_email).first()
        if not user:
            return {"success": False, "errors": ["User not found"]}, 404

        if user.verified:
            return {"success": True, "data": {"message": "Email already verified"}}

        user.verified = True
        db.session.commit()

        if can_send_mail():
            email.successful_registration_notification(user.email)

        return {
            "success": True,
            "data": {"message": "Email successfully verified"}
        }


@auth_namespace.route("/forgot-password")
class ForgotPassword(Resource):
    @ratelimit(method="POST", limit=10, interval=60)
    @auth_namespace.doc(
        description="Request password reset email",
        responses={
            200: "Success",
        },
    )
    def post(self):
        """Request password reset"""
        if not can_send_mail():
            return {
                "success": False,
                "errors": ["Email functionality is not configured"]
            }, 400

        req = request.get_json()
        email_address = req.get("email", "").strip()

        user = Users.query.filter_by(email=email_address).first()
        if user and not user.oauth_id:
            email.forgot_password(email_address)

        # Always return success to avoid user enumeration
        return {
            "success": True,
            "data": {"message": "If the account exists, a reset email has been sent"}
        }


@auth_namespace.route("/reset-password/<token>")
class ResetPassword(Resource):
    @ratelimit(method="POST", limit=10, interval=60)
    @auth_namespace.doc(
        description="Reset password with token",
        responses={
            200: "Success",
            400: "Invalid token or request",
        },
    )
    def post(self, token):
        """Reset password with token"""
        try:
            email_address = unserialize(token, max_age=1800)
        except (BadTimeSignature, SignatureExpired):
            return {"success": False, "errors": ["Your reset link has expired"]}, 400
        except (BadSignature, TypeError, base64.binascii.Error):
            return {"success": False, "errors": ["Your reset token is invalid"]}, 400

        req = request.get_json()
        password = req.get("password", "").strip()

        if len(password) == 0:
            return {"success": False, "errors": ["Please provide a password"]}, 400

        if len(password) > 128:
            return {"success": False, "errors": ["Password is too long"]}, 400

        user = Users.query.filter_by(email=email_address).first()
        if not user:
            return {"success": False, "errors": ["User not found"]}, 404

        if user.oauth_id:
            return {
                "success": False,
                "errors": ["Account registered via OAuth cannot reset password"]
            }, 400

        user.password = password
        db.session.commit()

        if can_send_mail():
            email.password_change_alert(user.email)

        return {
            "success": True,
            "data": {"message": "Password successfully reset"}
        }