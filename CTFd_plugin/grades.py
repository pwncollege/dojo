import datetime

from flask import Blueprint, render_template, request
from CTFd.models import db, Challenges, Solves, Awards, Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only


grades = Blueprint("grades", __name__, template_folder="assets/grades/")

deadlines = {
    "babysuid": datetime.datetime(2020, 9, 2, 23),
    "babyshell": datetime.datetime(2020, 9, 9, 23),
    "babyjail": datetime.datetime(2020, 9, 16, 23),
    "babyrev": datetime.datetime(2020, 9, 30, 23),
    "babymem": datetime.datetime(2020, 10, 7, 23),
    "toddler1": datetime.datetime(2020, 10, 21, 23),
    "babyrop": datetime.datetime(2020, 10, 28, 23),
    "babykernel": datetime.datetime(2020, 11, 4, 23),
    "babyheap": datetime.datetime(2020, 11, 18, 23),
    "babyrace": datetime.datetime(2020, 11, 25, 23),
    "toddler2": datetime.datetime(2020, 12, 16, 23),
    "babyauto": datetime.datetime(2020, 12, 16, 23, 1),
}


def average(data):
    data = list(data)
    if not data:
        return 0.0
    return sum(data) / len(data)


def compute_grades(user_id, when=None):
    grades = []
    available_total = 0
    solves_total = 0

    makeup_grades = []
    makeup_solves_total = 0

    challenges = (
        db.session.query(Challenges.category, db.func.count())
        .filter(Challenges.state == "visible")
        .filter(Challenges.value > 0)
        .group_by(Challenges.category)
    )
    for category, num_available in challenges:
        solves = (
            Solves.query.filter_by(user_id=user_id)
            .join(Challenges)
            .filter(Challenges.category == category)
        )

        if when:
            solves = solves.filter(Solves.date < when)

        makeup_solves = solves

        deadline = deadlines.get(category)
        if deadline:
            solves = solves.filter(Solves.date < deadline)

        num_solves = solves.count()
        makeup_num_solves = makeup_solves.count()

        available_total += num_available
        solves_total += num_solves
        makeup_solves_total += makeup_num_solves

        grades.append(
            {
                "category": category,
                "due": str(deadline or ""),
                "completed": f"{num_solves}/{num_available}",
                "grade": num_solves / num_available,
            }
        )

        if category == "babyauto":
            continue
        makeup_grades.append(makeup_num_solves / num_available)

    max_time = datetime.datetime.max
    grades.sort(key=lambda k: (deadlines.get(k["category"], max_time), k["category"]))

    weighted_grades = [g["grade"] for g in grades if g["category"] != "babyauto"]
    makeup_grade = average(makeup_grades)
    weighted_grades += [makeup_grade] * len(weighted_grades)
    overall_grade = average(weighted_grades)
    overall_grade += (
        next(g["grade"] for g in grades if g["category"] == "babyauto") * 0.10
    )

    num_awards = Awards.query.filter_by(user_id=user_id).count()
    extra_credit = num_awards * 0.01
    grades.append(
        {
            "category": "extra",
            "due": "",
            "completed": f"{num_awards}",
            "grade": extra_credit,
        }
    )
    overall_grade += extra_credit

    grades.append(
        {
            "category": "makeup",
            "due": "",
            "completed": f"{makeup_solves_total}/{available_total}",
            "grade": makeup_grade,
        }
    )

    grades.append(
        {
            "category": "overall",
            "due": "",
            "completed": f"{solves_total}/{available_total}",
            "grade": overall_grade,
        }
    )

    return grades


@grades.route("/grades", methods=["GET"])
@authed_only
def view_grades():
    user_id = get_current_user().id
    if request.args.get("id") and is_admin():
        try:
            user_id = int(request.args.get("id"))
        except ValueError:
            pass

    when = request.args.get("when")
    if when:
        when = datetime.datetime.fromtimestamp(int(when))

    grades = compute_grades(user_id, when)

    for grade in grades:
        grade["grade"] = f'{grade["grade"] * 100.0:.2f}%'

    return render_template("grades.html", grades=grades)


@grades.route("/grades/all", methods=["GET"])
@admins_only
def view_all_grades():
    when = request.args.get("when")
    if when:
        when = datetime.datetime.fromtimestamp(int(when))

    # TODO: this is the class student ids, should probably exist in a db
    students = [1]

    grades = []
    for user_id in students:
        category_grades = compute_grades(user_id, when)
        user = Users.query.filter_by(id=user_id).first()
        user_grades = {
            "email": user.email,
            "id": user_id,
            "overall": [
                e["grade"] for e in category_grades if e["category"] == "overall"
            ][0],
            "makeup": [
                e["grade"] for e in category_grades if e["category"] == "makeup"
            ][0],
            "extra": [e["grade"] for e in category_grades if e["category"] == "extra"][
                0
            ],
        }
        for category_grade in category_grades:
            category = category_grade["category"]
            grade = category_grade["grade"]
            user_grades[category] = grade
        grades.append(user_grades)

    grades.sort(key=lambda k: (k["overall"], k["id"]), reverse=True)

    statistics = []

    average_grades = {"email": "average", "id": ""}
    for key in user_grades:
        if key not in average_grades:
            average_grades[key] = []
    for user_grades in grades:
        for key, value in user_grades.items():
            if key in ["email", "id"]:
                continue
            average_grades[key].append(value)
    for key, value in average_grades.items():
        if key in ["email", "id"]:
            continue
        average_grades[key] = average(value)
    statistics.append(average_grades)

    for user_grades in grades:
        for key, value in user_grades.items():
            if key in ["email", "id"]:
                continue
            user_grades[key] = f"{value * 100.0:.2f}%"

    for statistic in statistics:
        for key, value in statistic.items():
            if key in ["email", "id"]:
                continue
            statistic[key] = f"{value * 100.0:.2f}%"

    return render_template("all_grades.html", grades=grades, statistics=statistics)
