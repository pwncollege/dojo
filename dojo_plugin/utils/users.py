from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin

from ..models import UserVisibilityUpdates


def refresh_user(user):
    if user is None:
        return None
    return Users.query.populate_existing().filter_by(id=user.id).first()


def can_view_user(user, *, admins=False):
    user = refresh_user(user)
    if user is None:
        return False
    current_user = get_current_user()
    if user.banned:
        return admins and is_admin()
    visibility_pending = UserVisibilityUpdates.query.filter_by(
        user_id=user.id
    ).first() is not None
    return (
        (not user.hidden and not visibility_pending)
        or (current_user is not None and current_user.id == user.id)
        or (admins and is_admin())
    )
