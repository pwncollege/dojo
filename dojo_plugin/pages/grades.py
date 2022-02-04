import math
import datetime

import yaml
from flask import Blueprint, render_template, request
from CTFd.models import db, Challenges, Solves, Users
from CTFd.utils import get_config
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only

from ..models import DiscordUsers
from ..utils import active_dojo_id, dojo_modules
from .writeups import WriteupComments, writeup_weeks, all_writeups
from .discord import discord_reputation


grades = Blueprint("grades", __name__)


def average(data):
    data = list(data)
    if not data:
        return 0.0
    return sum(data) / len(data)


def helpful_credit(reputation, max_reputation):
    if not reputation or not max_reputation:
        return 0.0
    return round(100 * (math.log2(reputation + 0.1) / math.log2(max_reputation + 0.1))) / 1000


def shared_helpful_extra_credit():
    students = yaml.safe_load(get_config("students"))
    student_ids = set(int(student["dojo_id"]) for student in students)

    all_reputation = discord_reputation()
    max_reputation = max(all_reputation.values(), default=None)

    discord_users = {
        discord_user.discord_id: discord_user.user_id
        for discord_user in DiscordUsers.query.all()
    }

    all_shared_credit = [
        helpful_credit(reputation, max_reputation)
        for discord_id, reputation in all_reputation.items()
        if discord_users.get(discord_id) not in student_ids
    ]

    return sum(all_shared_credit) / len(students)


def compute_grades(user_id, when=None):
    modules = dojo_modules(active_dojo_id(user_id))
    deadlines = {
        module["category"]: module["deadline"]
        for module in modules
        if "category" in module and "deadline" in module
    }
    lates = {
        module["category"]: float(module["late"])
        for module in modules
        if "category" in module and "late" in module
    }

    grades = []
    available_total = 0
    solves_total = 0
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

        late = lates.get(category, 0.0)
        grade = (num_solves + late * (makeup_num_solves - num_solves)) / num_available

        now = datetime.datetime.utcnow()
        if deadline and deadline > now:
            remainder = datetime.timedelta(seconds=int((deadline - now).total_seconds()))
            due = f"{deadline} ({remainder})"
        elif deadline:
            due = f"{deadline}"
        else:
            due = ""

        grades.append({
                "category": category,
                "due": due,
                "solves": f"{makeup_num_solves}/{num_available} ({num_solves}/{num_available})",
                "grade": grade,
        })

    max_time = datetime.datetime.max
    grades.sort(key=lambda k: (deadlines.get(k["category"], max_time), k["category"]))

    module_average_grade = average(grade["grade"] for grade in grades)
    grades.append({
        "category": "module average",
        "due": "",
        "solves": f"{makeup_solves_total}/{available_total} ({solves_total}/{available_total})",
        "grade": module_average_grade,
    })

    weeks_accepted = {week: None for week in writeup_weeks()}
    for week, writeup in all_writeups(user_id):
        comment = (
            WriteupComments.query.filter_by(writeup_id=writeup.id)
            .order_by(WriteupComments.date.desc())
            .first()
        )
        weeks_accepted[week] = comment and comment.accepted
    accepted = len([... for week, accepted in weeks_accepted.items() if accepted])
    ctf_grade = accepted / 100
    grades.append({
        "category": "EC: ctf",
        "due": "",
        "solves": f"{accepted}/{len(weeks_accepted)}",
        "grade": ctf_grade,
    })

    discord_user = DiscordUsers.query.filter_by(user_id=user_id).first()

    reputation = 0
    helpful_personal_grade = 0.0
    if discord_user:
        all_reputation = discord_reputation()
        reputation = all_reputation.get(discord_user.discord_id, 0)
        max_reputation = max(all_reputation.values(), default=None)
        helpful_personal_grade = helpful_credit(reputation, max_reputation)
    grades.append({
        "category": "EC: helpful personal",
        "due": "",
        "solves": f"{reputation}",
        "grade": helpful_personal_grade,
    })

    helpful_shared_grade = shared_helpful_extra_credit()
    grades.append({
        "category": "EC: helpful shared",
        "due": "",
        "solves": "",
        "grade": helpful_shared_grade,
    })


    meme_weeks = yaml.safe_load(get_config("memes"))
    memes_count = sum(int(discord_user.discord_id in week["users"]) for week in meme_weeks) if discord_user else 0
    memes_grade = memes_count / 200
    grades.append({
        "category": "EC: memes",
        "due": "",
        "solves": f"{memes_count}/{len(meme_weeks)}",
        "grade": memes_grade,
    })

    overall_grade = (
        module_average_grade +
        ctf_grade +
        helpful_personal_grade +
        helpful_shared_grade +
        memes_grade
    )
    grades.append({
        "category": "overall",
        "due": "",
        "solves": "",
        "grade": overall_grade,
    })

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


@grades.route("/admin/grades", methods=["GET"])
@admins_only
def view_all_grades():
    when = request.args.get("when")
    if when:
        when = datetime.datetime.fromtimestamp(int(when))

    students = yaml.safe_load(get_config("students"))

    grades = []
    for student in students:
        user_id = int(student["dojo_id"])
        if user_id == -1:
            continue
        category_grades = compute_grades(user_id, when)
        user = Users.query.filter_by(id=user_id).first()
        user_grades = {
            "email": user.email,
            "id": user_id,
        }
        category_grades.insert(0, category_grades.pop())  # Move overall to the start
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

    return render_template("admin_grades.html", grades=grades, statistics=statistics)
