from flask import Blueprint, render_template, redirect, url_for


dojos = Blueprint("pwncollege_dojos", __name__)

@dojos.route("/dojos")
def listing():
    dojos = [{
        "name": "Computer Systems Security (CSE 466)",
        "permalink": "cse466",
        "challenges_solved": 0,
        "challenges_count": 0,
    }]

    return render_template(
        "dojos.html",
        dojos=dojos,
    )


@dojos.route("/dojo/<dojo>")
def view_dojo(dojo):
    return redirect(url_for("pwncollege_challenges.listing", dojo=dojo))
