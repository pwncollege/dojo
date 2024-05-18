from flask import render_template
from CTFd.views import static_html

def static_html_override(route):
    if route != "index":
        return static_html(route)
    else:
        return render_template("index.html")
