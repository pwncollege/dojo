from flask import Blueprint, render_template, abort
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.models import Users

from ..utils import user_dojos, dojo_challenges, module_visible
from ..api.v1.scoreboard import belt_asset_for

users = Blueprint("pwncollege_users", __name__)

def dojo_full_stats(dojo, user):
    challenges = dojo_challenges(dojo, user=user)
    visible_modules = [ m for m in dojo.modules if module_visible(dojo, m, None) ]
    module_challenges = { m["id"]: dojo_challenges(dojo, module=m, user=user) for m in visible_modules }
    return {
        "count": len(challenges),
        "solved": len([c for c in challenges if c.solved]),
        "visible_modules": visible_modules,
        "module_stats": {
            m["id"]: {
                "solved_names": [ c.name for c in module_challenges[m["id"]] if c.solved ],
                "unsolved_names": [ c.name for c in module_challenges[m["id"]] if not c.solved ],
                "count": len(module_challenges[m["id"]]),
                "solved": len([c for c in module_challenges[m["id"]] if c.solved])
            } for m in visible_modules
        }
    }


def view_profile(user):
    current_user = get_current_user()
    dojos = user_dojos(user)
    if user is not current_user:
        other_dojos = user_dojos(current_user)
        dojos = [ d for d in dojos if d in other_dojos ]

    public_dojos = [ d for d in dojos if d.public and not d.archived ]
    private_dojos = [ d for d in dojos if not d.public and not d.archived ]
    archived_dojos = [ d for d in dojos if d.archived ]
    stats = { d.id: dojo_full_stats(d, user) for d in dojos }

    return render_template(
        "hacker.html",
        public_dojos=public_dojos, private_dojos=private_dojos, archived_dojos=archived_dojos, stats=stats,
        user=user, current_user=current_user, belt=belt_asset_for(user.id)
    )

@users.route("/hackers/<int:user_id>")
def view_other(user_id):
    user = Users.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return view_profile(user)

@users.route("/hacker")
@authed_only
def view_self():
    return view_profile(get_current_user())
