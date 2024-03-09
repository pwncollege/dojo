from flask import Blueprint, render_template
from ..utils.awards import get_belts

belts = Blueprint("pwncollege_belts", __name__)

@belts.route("/belts")
def view_belts():
    return render_template("belts.html", belt_data=get_belts())
