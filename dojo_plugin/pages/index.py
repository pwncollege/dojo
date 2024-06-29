from flask import url_for, redirect
from CTFd.views import static_html

def static_html_override(route):
    if route != "index":
        return static_html(route)
    else:
        return redirect(url_for("pwncollege_dojos.listing"), code=302)
