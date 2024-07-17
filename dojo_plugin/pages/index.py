from flask import url_for, redirect
from CTFd.views import static_html

from .dojos import listing

def static_html_override(route):
    if route != "index":
        return static_html(route)
    else:
        return listing("index.html")
