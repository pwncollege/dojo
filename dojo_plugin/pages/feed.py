from flask import Blueprint, render_template, request
from CTFd.utils.decorators.visibility import check_account_visibility

from ..utils.feed import get_recent_events

feed = Blueprint("pwncollege_feed", __name__)


@feed.route("/feed")
@check_account_visibility
def feed_page():
    dojo_id = request.args.get("dojo")
    initial_events = get_recent_events(limit=20, dojo_id=dojo_id)
    
    return render_template(
        "feed.html",
        initial_events=initial_events,
        dojo_id=dojo_id
    )
