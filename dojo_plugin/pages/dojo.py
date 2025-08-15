import collections
import traceback
import datetime
import ruamel
import sys

from flask import Blueprint, render_template, abort, send_file, redirect, url_for, Response, stream_with_context, request, g
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import and_, or_
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import db, Solves, Users
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.helpers import get_infos

from ..utils import get_current_container, get_all_containers, render_markdown
from ..utils.stats import get_container_stats, get_dojo_stats
from ..utils.dojo import dojo_route, get_current_dojo_challenge, dojo_update, dojo_admins_only
from ..models import Dojos, DojoUsers, DojoStudents, DojoModules, DojoMembers, DojoChallenges

dojo = Blueprint("pwncollege_dojo", __name__)
#pylint:disable=redefined-outer-name


def find_description_edit_url(dojo, base_path, candidates, yaml_search_paths=None, resource_name=None):
    """Find description file and return GitHub edit URL with line number"""
    if not (dojo.official and dojo.repository):
        return None
        
    for candidate in candidates:
        if isinstance(candidate, tuple):
            relative_path, full_path = candidate
        else:
            full_path = base_path / candidate
            try:
                relative_path = full_path.relative_to(dojo.path)
            except ValueError:
                relative_path = candidate
            
        if full_path.exists():
            line_num = 1  # Default to line 1 for .md files
            
            if str(relative_path).endswith('.yml') and (yaml_search_paths or resource_name):
                try:
                    yaml = ruamel.YAML()
                    yaml.preserve_quotes = True
                    
                    with open(full_path, 'r') as f:
                        data = yaml.load(f)
                    
                    # If looking for a resource by name, search in resources array
                    if resource_name and 'resources' in data:
                        for i, res in enumerate(data['resources']):
                            if isinstance(res, dict) and res.get('name') == resource_name:
                                # Get line number of this specific resource entry
                                if hasattr(res, 'lc'):
                                    line_num = res.lc.line + 1
                                    break
                    
                    # Otherwise use the provided search paths
                    if line_num == 1 and yaml_search_paths:
                        for path in yaml_search_paths:
                            parts = path.split('.')
                            current = data
                            
                            try:
                                for part in parts:
                                    if '[' in part and ']' in part:
                                        key, idx = part.split('[')
                                        idx = int(idx.rstrip(']'))
                                        current = current[key][idx]
                                    else:
                                        current = current[part]
                                
                                if hasattr(current, 'lc'):
                                    line_num = current.lc.line + 1
                                    break
                                elif hasattr(data, 'lc') and path in data:
                                    line_num = data.lc.key(path)[0] + 1
                                    break
                            except (KeyError, IndexError, AttributeError, TypeError):
                                continue
                    
                    # Fallback to simple keys
                    if line_num == 1:
                        for key in ['description', 'content']:
                            if key in data and hasattr(data, 'lc'):
                                line_num = data.lc.key(key)[0] + 1
                                break
                except Exception:
                    pass
            
            return f"https://github.com/{dojo.repository}/edit/main/{relative_path}#L{line_num}"
    
    return None


@dojo.route("/<dojo>")
@dojo.route("/<dojo>/")
@dojo_route
def listing(dojo):
    infos = get_infos()
    user = get_current_user()
    dojo_user = DojoUsers.query.filter_by(dojo=dojo, user=user).first()
    stats = get_dojo_stats(dojo)
    awards = dojo.awards()
    module_container_counts = collections.Counter(
        container["module"]
        for container in get_container_stats()
        if container["dojo"] == dojo.reference_id
    )
    stats["active"] = sum(module_container_counts.values())
    
    description_edit_url = None
    if dojo.description and dojo.path.exists():
        description_edit_url = find_description_edit_url(dojo, dojo.path, ["DESCRIPTION.md", "dojo.yml"], ['description'])
    
    return render_template(
        "dojo.html",
        dojo=dojo,
        user=user,
        dojo_user=dojo_user,
        stats=stats,
        infos=infos,
        awards=awards,
        module_container_counts=module_container_counts,
        description_edit_url=description_edit_url,
    )


@dojo.route("/<dojo>/<path>")
@dojo.route("/<dojo>/<path>/")
@dojo.route("/<dojo>/<path>/<subpath>")
@dojo.route("/<dojo>/<path>/<subpath>/")
@dojo_route
def view_dojo_path(dojo, path, subpath=None):
    module = DojoModules.query.filter_by(dojo=dojo, id=path).first()
    if module:
        if subpath:
            DojoChallenges.query.filter_by(dojo=dojo, module=module, id=subpath).first_or_404()
        return view_module(dojo, module)
    elif path in dojo.pages and not subpath:
        return view_page(dojo, path)
    else:
        abort(404)


@dojo.route("/active-module")
@dojo.route("/active-module/")
@authed_only
def active_module():
    active_challenge = get_current_dojo_challenge()
    if not active_challenge:
        return {}

    g.dojo = active_challenge.dojo

    current_challenge = active_challenge
    challenges = list(filter(lambda x: x.visible(), current_challenge.module.challenges))
    current_index = challenges.index(current_challenge)

    previous_challenge = challenges[current_index - 1] if current_index > 0 else None
    next_challenge = challenges[current_index + 1] if current_index < (len(challenges) - 1) else None

    def challenge_info(challenge):
        if not challenge:
            return {}
        return {
            "module_name": challenge.module.name,
            "module_id": challenge.module.id,
            "dojo_name": challenge.dojo.name,
            "dojo_reference_id": challenge.dojo.reference_id,
            "challenge_id": challenge.challenge_id,
            "challenge_name": challenge.name,
            "challenge_reference_id": challenge.id,
            "description": render_markdown(challenge.description).strip() if challenge == current_challenge else None,
        }

    return {
        "c_previous": challenge_info(previous_challenge),
        "c_current": challenge_info(current_challenge),
        "c_next": challenge_info(next_challenge),
    }


@dojo.route("/dojo/<dojo>")
@dojo_route
def view_dojo(dojo):
    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.reference_id))


@dojo.route("/dojo/<dojo>/join")
@dojo.route("/dojo/<dojo>/join/")
@dojo.route("/dojo/<dojo>/join/<password>")
@authed_only
def join_dojo(dojo, password=None):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        abort(404)

    if dojo.password and dojo.password != password:
        abort(403)

    try:
        member = DojoMembers(dojo=dojo, user=get_current_user())
        db.session.add(member)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.reference_id))


@dojo.route("/dojo/<dojo>/update/", methods=["GET", "POST"])
@dojo.route("/dojo/<dojo>/update/<update_code>", methods=["GET", "POST"])
@bypass_csrf_protection
def update_dojo(dojo, update_code=None):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        return {"success": False, "error": "Not Found"}, 404

    if dojo.update_code != update_code:
        return {"success": False, "error": "Forbidden"}, 403

    try:
        dojo_update(dojo)
        db.session.commit()
    except Exception as e:
        print(f"ERROR: Dojo failed for {dojo}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}, 400
    return {"success": True}

@dojo.route("/dojo/<dojo>/delete/", methods=["POST"])
@authed_only
def delete_dojo(dojo):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        return {"success": False, "error": "Not Found"}, 404

    # Check if the current user is an admin of the dojo
    if not is_admin():
        abort(403)

    try:
        DojoUsers.query.filter(DojoUsers.dojo_id == dojo.dojo_id).delete()
        Dojos.query.filter(Dojos.dojo_id == dojo.dojo_id).delete()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Dojo failed for {dojo}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}, 400
    return {"success": True}

@dojo.route("/dojo/<dojo>/admin/")
@dojo_route
@dojo_admins_only
def view_dojo_admin(dojo):
    return render_template("dojo_admin.html", dojo=dojo, is_admin=is_admin)


@dojo.route("/dojo/<dojo>/admin/activity")
@dojo_route
@dojo_admins_only
def view_dojo_activity(dojo):
    containers = get_all_containers(dojo)

    actives = []
    now = datetime.datetime.now()
    for container in containers:
        user_id = container.labels["dojo.user_id"]
        dojo_id = container.labels["dojo.dojo_id"]
        module_id = container.labels["dojo.module_id"]
        challenge_id = container.labels["dojo.challenge_id"]

        user = Users.query.filter_by(id=user_id).first()
        challenge = DojoChallenges.from_id(dojo_id, module_id, challenge_id).first()

        created = datetime.datetime.fromisoformat(container.attrs["Created"].split(".")[0])
        uptime = now - created

        actives.append(dict(user=user, challenge=challenge, uptime=uptime))
    actives.sort(key=lambda active: active["uptime"])

    solves = dojo.solves().order_by(Solves.date).all()

    return render_template("dojo_activity.html", dojo=dojo, actives=actives, solves=solves)


@dojo.route("/dojo/<dojo>/solves/", methods=["GET", "POST"])
@dojo.route("/dojo/<dojo>/solves/<solves_code>/<format>", methods=["GET", "POST"])
@bypass_csrf_protection
def dojo_solves(dojo, solves_code=None, format="csv"):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        return {"success": False, "error": "Not Found"}, 404

    if dojo.solves_code != solves_code:
        return {"success": False, "error": "Forbidden"}, 403

    solves_query = (
        dojo
        .solves(ignore_visibility=True)
        .filter(or_(DojoUsers.user_id != None, ~Users.hidden))
        .order_by(DojoChallenges.module_index, DojoChallenges.challenge_index, Solves.date)
        .with_entities(Solves.user_id, Users.name, DojoModules.id, DojoChallenges.id, Solves.date)
    )
    solves = ((user_id, user_name, module, challenge, time.replace(tzinfo=datetime.timezone.utc))
              for user_id, user_name, module, challenge, time in solves_query)

    if format == "csv":
        def stream():
            yield "user_id,module,challenge,time\n"
            for user_id, _, module, challenge, time in solves:
                yield f"{user_id},{module},{challenge},{time}\n"
        headers = {"Content-Disposition": "attachment; filename=data.csv"}
        return Response(stream_with_context(stream()), headers=headers, mimetype="text/csv")
    elif format == "json":
        username_filter = request.args.get("user_name", None)
        return [
            dict(zip(("user_id","user_name","module","challenge","time"), row))
            for row in solves
            if username_filter is None or row[1] == username_filter
        ]
    else:
        return {"success": False, "error": "Invalid format"}, 400


def view_module(dojo, module):
    user = get_current_user()
    user_solves = set(solve.challenge_id for solve in (
        module.solves(user=user, ignore_visibility=True, ignore_admins=False) if user else []
    ))
    total_solves = dict(module.solves()
                        .group_by(Solves.challenge_id)
                        .with_entities(Solves.challenge_id, db.func.count()))
    current_dojo_challenge = get_current_dojo_challenge()

    student = DojoStudents.query.filter_by(dojo=dojo, user=user).first()
    assessments = []
    if student or dojo.is_admin(user):
        now = datetime.datetime.now(datetime.timezone.utc)
        for assessment in module.assessments:
            date = datetime.datetime.fromisoformat(assessment["date"])
            until = date.astimezone(datetime.timezone.utc) - now
            if until < datetime.timedelta(0):
                continue
            date = str(date)
            until = " ".join(
                f"{count} {unit}{'s' if count != 1 else ''}"
                for count, unit in zip(
                    (until.days, *divmod(until.seconds // 60, 60)),
                    ("day", "hour", "minute")
                ) if count
            ) or "now"
            assessments.append(dict(
                name=assessment["type"].title(),
                date=date,
                until=until,
            ))

    challenge_container_counts = collections.Counter(
        container["challenge"]
        for container in get_container_stats()
        if container["module"] == module.id and container["dojo"] == dojo.reference_id
    )
    
    module_description_edit_url = None
    challenge_description_edit_urls = {}
    resource_description_edit_urls = {}
    
    if dojo.path.exists():
        module_path = dojo.path / module.id
        
        if module.description:
            module_description_edit_url = find_description_edit_url(dojo, module_path, [
                "DESCRIPTION.md",
                "module.yml",
                ("dojo.yml", dojo.path / "dojo.yml")
            ], ['description'])
        
        for challenge in module.challenges:
            if challenge.description:
                challenge_path = module_path / challenge.id
                challenge_description_edit_urls[challenge.id] = find_description_edit_url(dojo, challenge_path, [
                    "DESCRIPTION.md",
                    "challenge.yml",
                    ("module.yml", module_path / "module.yml"),
                    ("dojo.yml", dojo.path / "dojo.yml")
                ], [f'challenges.{challenge.id}.description', 'description'])
        
        for resource in module.resources:
            if resource.type == "markdown":
                resource_description_edit_urls[resource.resource_index] = find_description_edit_url(
                    dojo, module_path, 
                    ["module.yml", ("dojo.yml", dojo.path / "dojo.yml")],
                    resource_name=resource.name
                )

    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        challenges=module.visible_challenges(),
        user_solves=user_solves,
        total_solves=total_solves,
        user=user,
        current_dojo_challenge=current_dojo_challenge,
        assessments=assessments,
        challenge_container_counts=challenge_container_counts,
        module_description_edit_url=module_description_edit_url,
        challenge_description_edit_urls=challenge_description_edit_urls,
        resource_description_edit_urls=resource_description_edit_urls,
    )


def view_page(dojo, page):
    if (dojo.path / page).is_file():
        assert dojo.privileged or dojo.official
        path = (dojo.path / page).resolve()
        return send_file(path)

    elif (dojo.path / f"{page}.md").is_file():
        content = render_markdown((dojo.path / f"{page}.md").read_text())
        return render_template("markdown.html", dojo=dojo, content=content)

    elif (dojo.path / page).is_dir():
        user = get_current_user()
        if user and (dojo.path / page / f"{user.id}").is_file():
            assert dojo.privileged or dojo.official
            path = (dojo.path / page / f"{user.id}").resolve()
            return send_file(path)
        elif user and (dojo.path / page / f"{user.id}.md").is_file():
            content = render_markdown((dojo.path / page / f"{user.id}.md").read_text())
            return render_template("markdown.html", dojo=dojo, content=content)
        elif (dojo.path / page / "default.md").is_file():
            content = render_markdown((dojo.path / page / "default.md").read_text())
            return render_template("markdown.html", dojo=dojo, content=content)

    abort(404)
