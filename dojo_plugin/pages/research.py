from flask import Blueprint, Response, render_template, abort

from ..utils.awards import get_belts


research = Blueprint("research", __name__)


@research.route("/research")
def view_research():
    return render_template("research.html")