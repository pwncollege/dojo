from flask import Blueprint, render_template, redirect, url_for
from CTFd.models import db
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only, admins_only

from ..models import Dojos
from ..utils import user_dojos
from ..utils.dojo import dojo_route, generate_ssh_keypair, dojo_update


dojos = Blueprint("pwncollege_dojos", __name__)

def dojo_stats(dojo):
    challenges = dojo.challenges(user=get_current_user())
    return {
        "count": len(challenges),
        "solved": sum(1 for challenge in challenges if challenge.solved),
    }


@dojos.route("/dojos")
def listing():
    user = get_current_user()
    dojos = Dojos.viewable(user=user)
    return render_template("dojos.html", user=user, dojos=dojos)


@dojos.route("/dojo/<dojo>")
@dojo_route
def view_dojo(dojo):
    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.id))


@dojos.route("/dojo/<dojo>/update")
@dojo_route
@admins_only
def update_dojo(dojo):
    try:
        dojo_update(dojo)
        db.session.commit()
    except Exception as e:
        return '<br>'.join(f"<div><code>{line}</code></div>" for line in str(e).splitlines())
    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.id))


@dojos.route("/dojos/settings")
@authed_only
def dojo_create():
    user = get_current_user()
    dojos = Dojos.viewable(user=user)
    public_key, private_key = generate_ssh_keypair()
    return render_template(
        "dojos_settings.html",
        user=user,
        dojos=dojos,
        public_key=public_key,
        private_key=private_key,
    )


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
