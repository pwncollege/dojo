from flask import url_for, redirect, render_template
from CTFd.views import static_html

from .dojos import listing

def static_html_override(route):
    if route != "index":
        return static_html(route)
    else:
        return listing("index.html")

@app.route('/research')
def research():
    return render_template('research.html')
