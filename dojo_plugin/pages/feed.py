from flask import Blueprint, render_template
from CTFd.utils.decorators.visibility import check_account_visibility

from ..utils.feed import get_recent_events

feed = Blueprint("pwncollege_feed", __name__)


@feed.route("/feed")
@check_account_visibility
def feed_page():
    initial_events = get_recent_events(limit=20)
    
    return render_template(
        "feed.html",
        initial_events=initial_events
    )
