from flask import Blueprint, render_template
from CTFd.utils.decorators.visibility import check_account_visibility

from ..utils.feed import get_feed_snapshot

feed = Blueprint("pwncollege_feed", __name__)


@feed.route("/feed")
@check_account_visibility
def feed_page():
    initial_events, feed_cursor, legacy_feed_cursor = get_feed_snapshot(limit=20)
    
    return render_template(
        "feed.html",
        initial_events=initial_events,
        feed_cursor=feed_cursor,
        legacy_feed_cursor=legacy_feed_cursor,
    )
