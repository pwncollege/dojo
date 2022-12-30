from flask import Blueprint, render_template, redirect, url_for
from CTFd.utils.user import get_current_user

from ..models import Dojos
from ..utils import user_dojos
from ..utils.dojo import dojo_route


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


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
