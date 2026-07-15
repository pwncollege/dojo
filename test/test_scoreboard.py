import json
import random
import string

import pytest
import yaml

from utils import DOJO_URL, login, create_dojo_yml, dojo_run, workspace_run, start_challenge, solve_challenge, wait_for_background_worker, get_user_id, make_dojo_official, remove_workspace_container


def get_all_standings(session, dojo, module=None):
    """
    Return a big list of all the standings, going through all the available pages.
    """
    to_return = []

    page_number = 1
    done = False

    if module is None:
        module = "_"

    while not done:
        response = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/{page_number}")
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        response = response.json()

        to_return.extend(response["standings"])

        next_page = page_number + 1

        if next_page in response["pages"]:
            page_number += 1
        else:
            done = True

    return to_return


def get_module_cache_states(dojo):
    result = dojo_flask_run(f"""
import json
from CTFd.plugins.dojo_plugin.models import Dojos
from CTFd.plugins.dojo_plugin.utils.module_cache import module_challenge_solves_cache_key, module_scoreboard_cache_key, module_scores_cache_key

dojo = Dojos.from_id({dojo!r}).one()
print("CACHE-STATES=" + json.dumps([
    {{
        "id": module.id,
        "dojo_id": module.dojo_id,
        "index": module.module_index,
        "identity": module.cache_identity,
        "stored_identity": (module.data or {{}}).get("cache_identity"),
        "launched_at": module.cache_launched_at.isoformat(),
        "stored_launched_at": (module.data or {{}}).get("cache_launched_at"),
        "scoreboard": module_scoreboard_cache_key(module, 0),
        "crews": module_scoreboard_cache_key(module, 0, "crews"),
        "challenge_solves": module_challenge_solves_cache_key(module),
        "scores": module_scores_cache_key(module),
    }}
    for module in dojo.modules
], sort_keys=True))
""")
    return json.loads(next(
        line.removeprefix("CACHE-STATES=")
        for line in result.stdout.splitlines()
        if line.startswith("CACHE-STATES=")
    ))


def legacy_module_cache_keys(dojo_id, module_indexes):
    keys = set()
    for module_index in module_indexes:
        keys.update({
            f"stats:challenge_solves:module:{dojo_id}:{module_index}",
            f"stats:scores:module:{dojo_id}:{module_index}",
        })
        for duration in (0, 7, 30):
            keys.add(f"stats:scoreboard:module:{dojo_id}:{module_index}:{duration}")
            keys.add(f"stats:crews:module:{dojo_id}:{module_index}:{duration}")
    return keys | {
        metadata_key
        for key in keys
        for metadata_key in (f"{key}:updated", f"{key}:version")
    }


def identity_module_cache_keys(dojo_id, cache_identity):
    keys = {
        f"stats:challenge_solves:module:{dojo_id}:{cache_identity}",
        f"stats:scores:module:{dojo_id}:{cache_identity}",
    }
    for duration in (0, 7, 30):
        keys.add(f"stats:scoreboard:module:{dojo_id}:{cache_identity}:{duration}")
        keys.add(f"stats:crews:module:{dojo_id}:{cache_identity}:{duration}")
    return keys | {
        metadata_key
        for key in keys
        for metadata_key in (f"{key}:updated", f"{key}:version")
    }


def prime_module_cache_state(state, value="stale"):
    keys = (
        identity_module_cache_keys(state["dojo_id"], state["identity"])
        | legacy_module_cache_keys(state["dojo_id"], {state["index"]})
    )
    redis_cli("MSET", *[
        item
        for key in sorted(keys)
        for item in (key, value)
    ])
    return keys


def assert_module_cache_state_populated(state):
    keys = identity_module_cache_keys(state["dojo_id"], state["identity"])
    assert redis_cli("EXISTS", *sorted(keys)) == str(len(keys))


def redis_cli(*args):
    return dojo_run("docker", "exec", "cache", "redis-cli", *args).stdout.strip()


def dojo_flask_run(script):
    marker = "DOJO-FLASK-OK-" + "".join(
        random.choices(string.ascii_letters, k=16)
    )
    result = dojo_run(
        "dojo",
        "flask",
        input=(
            f"print(); exec(compile({script!r}, '<dojo-test>', 'exec'), "
            f"globals(), globals()); print('\\n' + {marker!r})\n"
        ),
        check=False,
    )
    assert result.returncode == 0 and marker in result.stdout.splitlines(), (
        f"dojo flask script failed with return code {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def test_dojo_flask_run_rejects_inner_assertion_failure():
    with pytest.raises(AssertionError, match="intentional inner assertion"):
        dojo_flask_run('raise AssertionError("intentional inner assertion")')


def cache_identity_module(module_id, challenge_id):
    return {
        "id": module_id,
        "name": module_id.title(),
        "challenges": [{
            "id": challenge_id,
            "name": challenge_id.title(),
            "image": "pwncollege/challenge-simple",
        }],
    }


def test_scoreboard(random_user_name, random_user_session, example_dojo):
    dojo = example_dojo
    module = "hello"
    challenge = "apple"

    prior_standings = get_all_standings(random_user_session, dojo, module)

    start_challenge(dojo, module, challenge, session=random_user_session)
    result = workspace_run("/challenge/apple", user=random_user_name)
    flag = result.stdout.strip()
    solve_challenge(dojo, module, challenge, session=random_user_session, flag=flag)

    wait_for_background_worker(timeout=2)

    new_standings = get_all_standings(random_user_session, dojo, module)
    assert len(prior_standings) != len(new_standings), "Expected to have a new entry in the standings"

    found_me = False
    for standing in new_standings:
        if standing['name'] == random_user_name:
            found_me = True
            break
    assert found_me, f"Unable to find new user {random_user_name} in new standings after solving a challenge"


def bracket_name_solver(example_dojo, tag):
    user_id = "".join(random.choices(string.ascii_lowercase, k=12))
    name = f"{user_id} [{tag}]"
    session = login(name, user_id, register=True, email=f"{user_id}@example.com")
    start_challenge(example_dojo, "hello", "apple", session=session)
    result = workspace_run("/challenge/apple", user=name)
    solve_challenge(example_dojo, "hello", "apple", session=session, flag=result.stdout.strip())
    remove_workspace_container(name)
    wait_for_background_worker(timeout=30)
    return name, session


@pytest.mark.timeout(180)
def test_scoreboard_bracket_name_passthrough(example_dojo):
    name, session = bracket_name_solver(example_dojo, "CrewTag")
    standings = get_all_standings(session, example_dojo)
    assert any(standing["name"] == name for standing in standings), \
        f"user {name!r} not found verbatim in standings"


@pytest.mark.timeout(180)
def test_scoreboard_hostile_tag_passthrough(example_dojo):
    name, session = bracket_name_solver(example_dojo, '<b x="y">&amp;')
    standings = get_all_standings(session, example_dojo)
    assert any(standing["name"] == name for standing in standings), \
        f"user {name!r} not found verbatim in standings"


def test_scoreboard_empty_module_contract(admin_session, example_dojo):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = f"""
id: empty-board-{suffix}
name: Empty Board
modules:
  - id: hello
    name: Hello
    challenges:
      - id: apple
        import:
          dojo: example
          module: hello
          challenge: apple
"""
    dojo = create_dojo_yml(spec, session=admin_session)
    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/hello/0/1")
    assert response.status_code == 200
    result = response.json()
    assert result["standings"] == []
    assert result["pages"] == []


@pytest.mark.timeout(180)
def test_new_dojo_creation_refreshes_imported_module_caches(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_spec = {
        "id": f"creation-source-{suffix}",
        "name": "Creation Source",
        "type": "public",
        "modules": [cache_identity_module("source", "shared")],
    }
    source = create_dojo_yml(yaml.safe_dump(source_spec), session=admin_session)
    dojo_flask_run(f"""
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules

module = DojoModules.from_id({source!r}, "source").one()
user = Users(
    name={f'creation-solver-{suffix}'!r},
    email={f'creation-solver-{suffix}@example.com'!r},
    password="password",
)
db.session.add(user)
db.session.flush()
db.session.add(Solves(
    user_id=user.id,
    challenge_id=module.challenges[0].challenge_id,
    ip="127.0.0.1",
    provided="creation",
))
db.session.commit()
print("OK")
""")

    def consumer_spec(reference_id):
        return {
            "id": reference_id,
            "name": "Creation Consumer",
            "type": "public",
            "modules": [
                {
                    "id": module_id,
                    "name": module_id.title(),
                    "resources": [
                        {
                            "type": "challenge",
                            "id": f"local-{module_id}",
                            "image": "pwncollege/challenge-simple",
                        },
                        {
                            "type": "challenge",
                            "import": {
                                "dojo": source,
                                "module": "source",
                                "challenge": "shared",
                            },
                        },
                    ],
                    "challenges": [{
                        "id": f"legacy-{module_id}",
                        "image": "pwncollege/challenge-simple",
                    }],
                }
                for module_id in ("first", "second")
            ],
        }

    api_spec = consumer_spec(f"creation-api-{suffix}")
    api_dojo = create_dojo_yml(
        yaml.safe_dump(api_spec),
        session=admin_session,
    )
    repository_spec = consumer_spec(f"creation-repository-{suffix}")
    repository_result = dojo_flask_run(f"""
import json
from unittest.mock import patch

from CTFd.models import Users, db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModuleCacheInvalidations
import CTFd.plugins.dojo_plugin.utils.dojo as dojo_utils
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    with patch.object(
        dojo_utils,
        "dojo_clone",
        side_effect=lambda repository, private_key: dojo_utils.dojo_yml_dir(
            json.dumps({repository_spec!r})
        ),
    ):
        dojo = dojo_utils.dojo_create(
            Users.query.filter_by(name="admin").one(),
            {f'creation-owner-{suffix}/creation-repository-{suffix}'!r},
            "public-key",
            "private-key",
            None,
        )
    db.session.expire_all()
    assert DojoCacheRefreshes.query.filter_by(
        dojo_id=dojo.dojo_id,
    ).count() == len(dojo.modules) + 1
    for module in dojo.modules:
        assert DojoCacheRefreshes.query.filter_by(
            kind="module",
            dojo_id=dojo.dojo_id,
            module_id=module.id,
            cache_identity=module.cache_identity,
        ).count() == 1
        cache_keys = module_cache.module_identity_cache_keys(
            module.dojo_id,
            module.cache_identity,
        )
        assert DojoModuleCacheInvalidations.query.filter(
            DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
        ).count() == len(cache_keys)
    repository_dojo = dojo.reference_id
    db.session.rollback()
    print("REPOSITORY-DOJO=" + repository_dojo)
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    repository_dojo = next(
        line.removeprefix("REPOSITORY-DOJO=")
        for line in repository_result.stdout.splitlines()
        if line.startswith("REPOSITORY-DOJO=")
    )
    initial_states = {
        api_dojo: get_module_cache_states(api_dojo),
        repository_dojo: get_module_cache_states(repository_dojo),
    }
    for dojo_reference, spec in (
        (api_dojo, api_spec),
        (repository_dojo, repository_spec),
    ):
        response = admin_session.post(
            f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_reference}/update",
            json=spec,
        )
        assert response.status_code == 200
        current_states = get_module_cache_states(dojo_reference)
        assert [state["identity"] for state in current_states] == [
            state["identity"] for state in initial_states[dojo_reference]
        ]
        assert [state["launched_at"] for state in current_states] == [
            state["launched_at"] for state in initial_states[dojo_reference]
        ]

    result = dojo_flask_run(f"""
import json

from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_message_timestamp, get_redis_client
from CTFd.plugins.dojo_plugin.utils.crews import aggregate_crews
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh
import CTFd.plugins.dojo_plugin.worker.handlers.scoreboard as scoreboard_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scores as scores_handler
import CTFd.plugins.dojo_plugin.worker.handlers.solve as solve_handler

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    dojos = [Dojos.from_id(reference_id).one() for reference_id in {
        (api_dojo, repository_dojo)!r
    }]
    dojo_ids = [dojo.dojo_id for dojo in dojos]
    while True:
        refreshes = DojoCacheRefreshes.query.filter(
            DojoCacheRefreshes.dojo_id.in_(dojo_ids)
        ).order_by(
            DojoCacheRefreshes.kind,
            DojoCacheRefreshes.dojo_id,
            DojoCacheRefreshes.module_id,
        ).all()
        if not refreshes:
            break
        for refresh in refreshes:
            payload = {{
                "dojo_id": refresh.dojo_id,
                "generation": refresh.generation,
            }}
            if refresh.kind == "module":
                payload.update({{
                    "module_id": refresh.module_id,
                    "cache_identity": refresh.cache_identity,
                }})
                assert cache_refresh.handle_module_cache_refresh(payload)
            else:
                assert cache_refresh.handle_dojo_cache_refresh(payload)
        db.session.expire_all()

    def json_value(value):
        return json.loads(json.dumps(value))

    redis_client = get_redis_client()
    for dojo in dojos:
        assert len(dojo.modules) == 2
        for module in dojo.modules:
            assert [(challenge.id, challenge.name) for challenge in module.challenges] == [
                (f"local-{{module.id}}", f"Local {{module.id.title()}}"),
                ("shared", "Shared"),
                (f"legacy-{{module.id}}", f"Legacy {{module.id.title()}}"),
            ]
            identity_keys = module_cache.module_identity_cache_keys(
                module.dojo_id,
                module.cache_identity,
            )
            assert redis_client.exists(*identity_keys) == len(identity_keys)
            for duration in module_cache.SCOREBOARD_DURATIONS:
                assert get_cached_stat(
                    module_cache.module_scoreboard_cache_key(module, duration)
                ) == []
                assert get_cached_stat(
                    module_cache.module_scoreboard_cache_key(
                        module,
                        duration,
                        "crews",
                    )
                ) == []
            assert get_cached_stat(
                module_cache.module_challenge_solves_cache_key(module)
            ) == {{}}
            assert get_cached_stat(
                module_cache.module_scores_cache_key(module)
            ) == {{"ranks": [], "solves": {{}}}}

    source_module = DojoModules.from_id({source!r}, "source").one()
    post_launch_user = Users(
        name={f'creation-post-launch-{suffix}'!r},
        email={f'creation-post-launch-{suffix}@example.com'!r},
        password="password",
    )
    db.session.add(post_launch_user)
    db.session.flush()
    post_launch_user_id = post_launch_user.id
    solve = Solves(
        user_id=post_launch_user_id,
        challenge_id=source_module.challenges[0].challenge_id,
        ip="127.0.0.1",
        provided="post-launch",
    )
    db.session.add(solve)
    db.session.commit()
    assert solve_handler.handle_challenge_solve({{
        "user_id": post_launch_user_id,
        "challenge_id": solve.challenge_id,
        "solve_date": solve.date.isoformat(),
    }}, get_message_timestamp(
        redis_client.xadd(
            "stat:test-timestamps",
            {{"event": "creation-post-launch"}},
        )
    ))

    db.session.expire_all()
    dojos = [Dojos.from_id(reference_id).one() for reference_id in {
        (api_dojo, repository_dojo)!r
    }]
    for dojo in dojos:
        for module in dojo.modules:
            redis_client.delete(*module_cache.module_identity_cache_keys(
                module.dojo_id,
                module.cache_identity,
            ))
            assert scoreboard_handler.populate_module_scoreboard_caches(
                module_cache.module_cache_target(module)
            )
        assert scores_handler.handle_scores_update({{
            "dojo_id": dojo.dojo_id,
        }})

    db.session.expire_all()
    dojos = [Dojos.from_id(reference_id).one() for reference_id in {
        (api_dojo, repository_dojo)!r
    }]
    for dojo in dojos:
        for module in dojo.modules:
            identity_keys = module_cache.module_identity_cache_keys(
                module.dojo_id,
                module.cache_identity,
            )
            assert redis_client.exists(*identity_keys) == len(identity_keys)
            for duration in module_cache.SCOREBOARD_DURATIONS:
                scoreboard = scoreboard_handler.calculate_scoreboard(
                    module,
                    duration,
                )
                member_challenges = scoreboard_handler.calculate_member_challenges(
                    module,
                    duration,
                    scoreboard,
                )
                assert [entry["user_id"] for entry in scoreboard] == [
                    post_launch_user_id
                ]
                assert get_cached_stat(
                    module_cache.module_scoreboard_cache_key(module, duration)
                ) == json_value(scoreboard)
                assert get_cached_stat(
                    module_cache.module_scoreboard_cache_key(
                        module,
                        duration,
                        "crews",
                    )
                ) == json_value(aggregate_crews(scoreboard, member_challenges))
            challenge_solves = scoreboard_handler.calculate_challenge_solves(
                module
            )
            scores = scores_handler.calculate_module_scores(module)
            assert list(challenge_solves.values()) == [1]
            assert scores == {{
                "ranks": [post_launch_user_id],
                "solves": {{post_launch_user_id: 1}},
            }}
            assert get_cached_stat(
                module_cache.module_challenge_solves_cache_key(module)
            ) == json_value(challenge_solves)
            assert get_cached_stat(
                module_cache.module_scores_cache_key(module)
            ) == json_value(scores)
    db.session.rollback()
    print("OK")
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    assert "OK" in result.stdout


def test_module_cache_identity_lifecycle(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-identity-{suffix}",
        "name": "Cache Identity",
        "type": "public",
        "modules": [
            cache_identity_module("first", "one"),
            cache_identity_module("second", "two"),
        ],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    wait_for_background_worker(timeout=30)
    initial = get_module_cache_states(dojo)
    initial_by_id = {state["id"]: state for state in initial}
    assert all(state["stored_identity"] == state["identity"] for state in initial)
    assert all(
        state["stored_launched_at"] == state["launched_at"]
        for state in initial
    )
    assert all(len(state["identity"]) == 32 for state in initial)
    assert all(
        state["scoreboard"].split(":")[-2] == state["identity"]
        and state["scoreboard"].split(":")[-2] != str(state["index"])
        for state in initial
    )

    dojo_id = int(dojo.split("~")[-1], 16)
    if dojo_id >= 2 ** 31:
        dojo_id -= 2 ** 32
    old_indexes = {state["index"] for state in initial}
    legacy_keys = legacy_module_cache_keys(dojo_id, old_indexes)
    preserved_key = initial_by_id["first"]["scoreboard"]
    redis_cli("MSET", *[
        value
        for key in sorted(legacy_keys)
        for value in (key, "stale")
    ])
    redis_cli("SET", preserved_key, "preserved")

    spec["modules"].reverse()
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=spec,
    )
    assert response.status_code == 200
    reordered = get_module_cache_states(dojo)
    reordered_by_id = {state["id"]: state for state in reordered}
    assert reordered_by_id["first"]["identity"] == initial_by_id["first"]["identity"]
    assert reordered_by_id["second"]["identity"] == initial_by_id["second"]["identity"]
    assert reordered_by_id["first"]["launched_at"] == initial_by_id["first"]["launched_at"]
    assert reordered_by_id["second"]["launched_at"] == initial_by_id["second"]["launched_at"]
    assert reordered_by_id["first"]["index"] != initial_by_id["first"]["index"]
    assert redis_cli("EXISTS", *sorted(legacy_keys)) == "0"
    assert redis_cli("GET", preserved_key) == "preserved"

    retired_identity = reordered[0]["identity"]
    retired_keys = identity_module_cache_keys(dojo_id, retired_identity)
    redis_cli("MSET", *[
        value
        for key in sorted(retired_keys)
        for value in (key, "retired")
    ])
    spec["modules"][0] = cache_identity_module("fresh", "three")
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=spec,
    )
    assert response.status_code == 200
    replaced = get_module_cache_states(dojo)
    replaced_by_id = {state["id"]: state for state in replaced}
    assert replaced[0]["index"] == reordered[0]["index"]
    assert replaced_by_id["fresh"]["identity"] != retired_identity
    assert replaced_by_id["fresh"]["launched_at"] != reordered[0]["launched_at"]
    assert redis_cli("EXISTS", *sorted(retired_keys)) == "0"
    assert redis_cli("GET", preserved_key) == "preserved"

    stale_scoreboard_key = reordered[0]["scoreboard"]
    redis_cli("SET", stale_scoreboard_key, json.dumps([{
        "rank": 1,
        "solves": 999,
        "user_id": 1,
        "name": "stale",
        "email": "stale@example.com",
    }]))
    response = admin_session.get(
        f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/fresh/0/1"
    )
    assert response.status_code == 200
    assert response.json()["standings"] == []

    first_only = {**spec, "modules": [spec["modules"][1]]}
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=first_only,
    )
    assert response.status_code == 200
    recreated_spec = {
        **spec,
        "modules": [
            spec["modules"][1],
            cache_identity_module("fresh", "three"),
        ],
    }
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=recreated_spec,
    )
    assert response.status_code == 200
    recreated = get_module_cache_states(dojo)
    recreated_by_id = {state["id"]: state for state in recreated}
    assert recreated_by_id["fresh"]["identity"] != replaced_by_id["fresh"]["identity"]
    assert recreated_by_id["fresh"]["launched_at"] != replaced_by_id["fresh"]["launched_at"]


def test_recreated_module_resets_launch_cutoff(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-recreated-launch-{suffix}",
        "name": "Cache Recreated Launch",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    result = dojo_flask_run(f"""
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh
import CTFd.plugins.dojo_plugin.worker.handlers.scoreboard as scoreboard_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scores as scores_handler

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    module = DojoModules.from_id({dojo!r}, "module").one()
    original_identity = module.cache_identity
    original_launch = module.cache_launched_at
    original_target = module_cache.module_cache_target(module)
    module_cache.queue_cache_refreshes(module_targets=(original_target,))
    db.session.commit()
    assert DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=original_target.dojo_id,
        module_id=original_target.module_id,
        cache_identity=original_target.cache_identity,
    ).count() == 1
    prior_user = Users(
        name={f'recreated-prior-{suffix}'!r},
        email={f'recreated-prior-{suffix}@example.com'!r},
        password="password",
    )
    db.session.add(prior_user)
    db.session.flush()
    prior_user_id = prior_user.id
    challenge_id = module.challenges[0].challenge_id
    prior_solve = Solves(
        user_id=prior_user.id,
        challenge_id=challenge_id,
        ip="127.0.0.1",
        provided="prior",
    )
    db.session.add(prior_solve)
    db.session.commit()
    assert prior_solve.date >= original_launch
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert cache_refresh._write_module_caches(module)
    assert [
        entry["user_id"]
        for entry in get_cached_stat(
            module_cache.module_scoreboard_cache_key(module, 0)
        )
    ] == [prior_user.id]

    dojo_model = Dojos.from_id({dojo!r}).one()
    dojo_from_spec({{**{spec!r}, "modules": []}}, dojo=dojo_model)
    db.session.commit()
    assert not DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=original_target.dojo_id,
        module_id=original_target.module_id,
        cache_identity=original_target.cache_identity,
    ).count()
    dojo_model = Dojos.from_id({dojo!r}).one()
    dojo_from_spec({spec!r}, dojo=dojo_model)
    db.session.commit()
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert module.cache_identity != original_identity
    assert module.cache_launched_at > prior_solve.date
    assert module.solves(
        user=Users.query.get(prior_user_id),
        ignore_visibility=True,
        ignore_admins=False,
    ).count() == 1
    refresh = DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=module.cache_identity,
    ).one()
    payload = {{
        "dojo_id": module.dojo_id,
        "module_id": module.id,
        "cache_identity": module.cache_identity,
        "generation": refresh.generation,
    }}
    db.session.rollback()
    assert cache_refresh.handle_module_cache_refresh(payload)
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    for duration in module_cache.SCOREBOARD_DURATIONS:
        assert scoreboard_handler.calculate_scoreboard(module, duration) == []
        assert get_cached_stat(
            module_cache.module_scoreboard_cache_key(module, duration)
        ) == []
    assert scoreboard_handler.calculate_challenge_solves(module) == {{}}
    assert scores_handler.calculate_module_scores(module) == {{
        "ranks": [],
        "solves": {{}},
    }}

    post_user = Users(
        name={f'recreated-post-{suffix}'!r},
        email={f'recreated-post-{suffix}@example.com'!r},
        password="password",
    )
    db.session.add(post_user)
    db.session.flush()
    post_user_id = post_user.id
    db.session.add(Solves(
        user_id=post_user_id,
        challenge_id=challenge_id,
        ip="127.0.0.1",
        provided="post",
    ))
    db.session.commit()
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert scoreboard_handler.populate_module_scoreboard_caches(
        module_cache.module_cache_target(module)
    )
    assert scores_handler.handle_scores_update({{
        "dojo_id": module.dojo_id,
    }})
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert [
        entry["user_id"]
        for entry in get_cached_stat(
            module_cache.module_scoreboard_cache_key(module, 0)
        )
    ] == [post_user_id]
    assert get_cached_stat(
        module_cache.module_challenge_solves_cache_key(module)
    ) == {{str(challenge_id): 1}}
    assert get_cached_stat(
        module_cache.module_scores_cache_key(module)
    ) == {{
        "ranks": [post_user_id],
        "solves": {{str(post_user_id): 1}},
    }}
    db.session.rollback()
    print("OK")
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    assert "OK" in result.stdout


def test_same_id_module_content_rotates_and_repopulates_caches(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-content-{suffix}",
        "name": "Cache Content",
        "type": "public",
        "modules": [cache_identity_module("stable", "one")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    initial = get_module_cache_states(dojo)[0]
    retired_keys = prime_module_cache_state(initial)

    spec["modules"] = [cache_identity_module("stable", "two")]
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=spec,
    )
    assert response.status_code == 200
    current = get_module_cache_states(dojo)[0]
    assert current["id"] == initial["id"]
    assert current["index"] == initial["index"]
    assert current["identity"] != initial["identity"]
    assert current["launched_at"] == initial["launched_at"]
    assert redis_cli("EXISTS", *sorted(retired_keys)) == "0"

    wait_for_background_worker(timeout=30)
    assert_module_cache_state_populated(current)
    assert redis_cli("EXISTS", *sorted(retired_keys)) == "0"


def test_imported_module_content_rotates_consumer_caches(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_spec = {
        "id": f"cache-source-{suffix}",
        "name": "Cache Source",
        "type": "public",
        "modules": [cache_identity_module("source", "one")],
    }
    source = create_dojo_yml(yaml.safe_dump(source_spec), session=admin_session)
    make_dojo_official(source, admin_session)
    consumer_spec = {
        "id": f"cache-consumer-{suffix}",
        "name": "Cache Consumer",
        "type": "public",
        "modules": [{
            "id": "stable",
            "name": "Stable",
            "import": {
                "dojo": source_spec["id"],
                "module": "source",
            },
        }],
    }
    consumer = create_dojo_yml(
        yaml.safe_dump(consumer_spec), session=admin_session
    )
    initial = get_module_cache_states(consumer)[0]
    retired_keys = prime_module_cache_state(initial)

    source_spec["modules"] = [cache_identity_module("source", "two")]
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{source}/update",
        json=source_spec,
    )
    assert response.status_code == 200
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{consumer}/update",
        json=consumer_spec,
    )
    assert response.status_code == 200

    current = get_module_cache_states(consumer)[0]
    assert current["id"] == initial["id"]
    assert current["identity"] != initial["identity"]
    assert current["launched_at"] == initial["launched_at"]
    assert redis_cli("EXISTS", *sorted(retired_keys)) == "0"

    wait_for_background_worker(timeout=30)
    assert_module_cache_state_populated(current)
    assert redis_cli("EXISTS", *sorted(retired_keys)) == "0"


def test_module_caches_refresh_when_dojo_access_eligibility_changes(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    public_spec = {
        "id": f"cache-access-{suffix}",
        "name": "Cache Access",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(
        yaml.safe_dump(public_spec),
        session=admin_session,
    )
    private_spec = {**public_spec, "type": "private"}
    result = dojo_flask_run(f"""
import json
from unittest.mock import patch

from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.api.v1.scoreboard import get_crews_for, get_scoreboard_for
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh
import CTFd.plugins.dojo_plugin.worker.handlers.scoreboard as scoreboard_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scores as scores_handler

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    dojo_model = Dojos.from_id({dojo!r}).one()
    module = DojoModules.from_id({dojo!r}, "module").one()
    identity = module.cache_identity
    launched_at = module.cache_launched_at
    user = Users(
        name={f'access-user-{suffix}'!r},
        email={f'access-user-{suffix}@example.com'!r},
        password="password",
    )
    db.session.add(user)
    db.session.flush()
    user_id = user.id
    db.session.add(Solves(
        user_id=user_id,
        challenge_id=module.challenges[0].challenge_id,
        ip="127.0.0.1",
        provided="access",
    ))
    db.session.commit()
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert cache_refresh._write_module_caches(module)
    db.session.commit()
    assert [
        entry["user_id"]
        for entry in get_cached_stat(
            module_cache.module_scoreboard_cache_key(module, 0)
        )
    ] == [user_id]

    dojo_model = Dojos.from_id({dojo!r}).one()
    dojo_from_spec({private_spec!r}, dojo=dojo_model)
    db.session.commit()
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert module.cache_identity == identity
    assert module.cache_launched_at == launched_at
    refresh = DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=identity,
    ).one()
    private_payload = {{
        "dojo_id": module.dojo_id,
        "module_id": module.id,
        "cache_identity": identity,
        "generation": refresh.generation,
    }}
    db.session.rollback()
    assert get_scoreboard_for(module, 0) == []
    assert get_crews_for(module, 0) == []
    with patch.object(
        cache_refresh,
        "_write_module_caches",
        return_value=False,
    ):
        assert not cache_refresh.handle_module_cache_refresh(private_payload)
    assert DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=identity,
    ).count() == 1
    assert get_scoreboard_for(module, 0) == []
    db.session.rollback()
    assert cache_refresh.handle_module_cache_refresh(private_payload)
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    for duration in module_cache.SCOREBOARD_DURATIONS:
        assert scoreboard_handler.calculate_scoreboard(module, duration) == []
        assert get_cached_stat(
            module_cache.module_scoreboard_cache_key(module, duration)
        ) == []
        assert get_cached_stat(
            module_cache.module_scoreboard_cache_key(
                module,
                duration,
                "crews",
            )
        ) == []
    assert scoreboard_handler.calculate_challenge_solves(module) == {{}}
    assert scores_handler.calculate_module_scores(module) == {{
        "ranks": [],
        "solves": {{}},
    }}

    dojo_model = Dojos.from_id({dojo!r}).one()
    dojo_from_spec({public_spec!r}, dojo=dojo_model)
    db.session.commit()
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()
    assert module.cache_identity == identity
    assert module.cache_launched_at == launched_at
    refresh = DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=identity,
    ).one()
    public_payload = {{
        "dojo_id": module.dojo_id,
        "module_id": module.id,
        "cache_identity": identity,
        "generation": refresh.generation,
    }}
    db.session.rollback()
    assert get_scoreboard_for(module, 0) == []
    assert cache_refresh.handle_module_cache_refresh(public_payload)
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "module").one()

    def json_value(value):
        return json.loads(json.dumps(value))

    for duration in module_cache.SCOREBOARD_DURATIONS:
        scoreboard = scoreboard_handler.calculate_scoreboard(module, duration)
        assert [entry["user_id"] for entry in scoreboard] == [user_id]
        assert get_cached_stat(
            module_cache.module_scoreboard_cache_key(module, duration)
        ) == json_value(scoreboard)
    assert get_cached_stat(
        module_cache.module_challenge_solves_cache_key(module)
    ) == json_value(scoreboard_handler.calculate_challenge_solves(module))
    assert get_cached_stat(
        module_cache.module_scores_cache_key(module)
    ) == json_value(scores_handler.calculate_module_scores(module))
    db.session.rollback()
    print("OK")
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    assert "OK" in result.stdout


def test_membership_admin_and_hidden_transitions_refresh_caches(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"eligibility-transitions-{suffix}",
        "name": "Eligibility Transitions",
        "type": "private",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    wait_for_background_worker(timeout=30)
    result = dojo_flask_run(f"""
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.api.v1.scoreboard import get_scoreboard_for
from CTFd.plugins.dojo_plugin.models import (
    DojoCacheRefreshes,
    DojoMembers,
    DojoModules,
    DojoUsers,
    Dojos,
)
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, set_cached_stat
from CTFd.plugins.dojo_plugin.utils.scores import get_dojo_scores, get_module_scores
from CTFd.plugins.dojo_plugin.utils.stats import get_dojo_stats
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh

dojo_reference = {dojo!r}
dojo = Dojos.from_id(dojo_reference).one()
module = DojoModules.from_id(dojo_reference, "module").one()
user = Users(
    name={f'eligibility-{suffix} [Transitions]'!r},
    email={f'eligibility-{suffix}@example.com'!r},
    password="password",
)
db.session.add(user)
db.session.flush()
user_id = user.id
challenge_id = module.challenges[0].challenge_id
db.session.add(Solves(
    user_id=user_id,
    challenge_id=challenge_id,
    ip="127.0.0.1",
    provided="eligibility",
))
db.session.commit()

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    dojo = Dojos.from_id(dojo_reference).one()
    module = DojoModules.from_id(dojo_reference, "module").one()
    assert cache_refresh._write_module_caches(module)
    assert cache_refresh._write_dojo_caches(dojo)
    db.session.commit()

    def assert_cached(expected):
        db.session.expire_all()
        current_dojo = Dojos.from_id(dojo_reference).one()
        current_module = DojoModules.from_id(
            dojo_reference,
            "module",
        ).one()
        expected_ids = [user_id] if expected else []
        assert [
            entry["user_id"]
            for entry in get_scoreboard_for(current_module, 0)
        ] == expected_ids
        assert [
            entry["user_id"]
            for entry in get_scoreboard_for(current_dojo, 0)
        ] == expected_ids
        assert get_module_scores(current_module)["ranks"] == expected_ids
        assert get_dojo_scores(current_dojo.dojo_id)["ranks"] == expected_ids
        assert get_dojo_stats(current_dojo)["solves"] == int(expected)
        challenge_solves = get_cached_stat(
            module_cache.module_challenge_solves_cache_key(current_module)
        )
        assert challenge_solves == (
            {{str(challenge_id): 1}} if expected else {{}}
        )
        db.session.rollback()

    def refresh_pending(expected):
        db.session.expire_all()
        current_dojo = Dojos.from_id(dojo_reference).one()
        current_module = DojoModules.from_id(
            dojo_reference,
            "module",
        ).one()
        module_refresh = DojoCacheRefreshes.query.filter_by(
            kind="module",
            dojo_id=current_dojo.dojo_id,
            module_id=current_module.id,
            cache_identity=current_module.cache_identity,
        ).one()
        dojo_refresh = DojoCacheRefreshes.query.filter_by(
            kind="dojo",
            dojo_id=current_dojo.dojo_id,
            module_id="",
            cache_identity="",
        ).one()
        assert module_refresh.published_at is not None
        assert dojo_refresh.published_at is not None
        sentinel = [{{
            "rank": 1,
            "solves": 999,
            "user_id": 987654321,
            "name": "sentinel",
            "email": "sentinel@example.com",
        }}]
        assert set_cached_stat(
            module_cache.module_scoreboard_cache_key(current_module, 0),
            sentinel,
        )
        assert set_cached_stat(
            module_cache.dojo_scoreboard_cache_key(current_dojo.dojo_id, 0),
            sentinel,
        )
        assert get_scoreboard_for(current_module, 0) == []
        assert get_scoreboard_for(current_dojo, 0) == []
        module_payload = {{
            "dojo_id": current_module.dojo_id,
            "module_id": current_module.id,
            "cache_identity": current_module.cache_identity,
            "generation": module_refresh.generation,
        }}
        dojo_payload = {{
            "dojo_id": current_dojo.dojo_id,
            "generation": dojo_refresh.generation,
        }}
        db.session.rollback()
        assert cache_refresh.handle_module_cache_refresh(module_payload)
        assert cache_refresh.handle_dojo_cache_refresh(dojo_payload)
        assert_cached(expected)

    assert_cached(False)
    assert not DojoCacheRefreshes.query.filter_by(
        dojo_id=dojo.dojo_id,
    ).count()

    dojo = Dojos.from_id(dojo_reference).one()
    user = Users.query.get(user_id)
    db.session.add(DojoMembers(dojo=dojo, user=user))
    db.session.flush()
    assert DojoCacheRefreshes.query.filter_by(
        dojo_id=dojo.dojo_id,
    ).count() == 2
    db.session.rollback()
    assert not DojoCacheRefreshes.query.filter_by(
        dojo_id=dojo.dojo_id,
    ).count()
    assert_cached(False)

    dojo = Dojos.from_id(dojo_reference).one()
    user = Users.query.get(user_id)
    db.session.add(DojoMembers(dojo=dojo, user=user))
    db.session.commit()
    refresh_pending(True)

    membership = DojoUsers.query.filter_by(
        dojo_id=dojo.dojo_id,
        user_id=user_id,
    ).one()
    membership.type = "admin"
    db.session.commit()
    refresh_pending(False)

    membership = DojoUsers.query.filter_by(
        dojo_id=dojo.dojo_id,
        user_id=user_id,
    ).one()
    membership.type = "member"
    db.session.commit()
    refresh_pending(True)

    membership = DojoUsers.query.filter_by(
        dojo_id=dojo.dojo_id,
        user_id=user_id,
    ).one()
    db.session.delete(membership)
    db.session.commit()
    refresh_pending(False)

    dojo = Dojos.from_id(dojo_reference).one()
    user = Users.query.get(user_id)
    db.session.add(DojoMembers(dojo=dojo, user=user))
    db.session.commit()
    refresh_pending(True)

    user = Users.query.get(user_id)
    user.hidden = True
    db.session.commit()
    refresh_pending(False)

    user = Users.query.get(user_id)
    user.hidden = False
    db.session.commit()
    refresh_pending(True)
    print("OK")
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    assert "OK" in result.stdout


def test_dojo_aggregate_caches_fail_closed_until_durable_refresh(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"aggregate-refresh-{suffix}",
        "name": "Aggregate Refresh",
        "type": "public",
        "modules": [cache_identity_module("stable", "one")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    updated_spec = {
        **spec,
        "modules": [cache_identity_module("stable", "two")],
    }
    wait_for_background_worker(timeout=30)

    result = dojo_flask_run(f"""
from unittest.mock import patch

from CTFd.models import db
from CTFd.plugins.dojo_plugin.api.v1.scoreboard import get_crews_for, get_scoreboard_for
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModuleCacheInvalidations, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_redis_client, set_cached_stat
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
from CTFd.plugins.dojo_plugin.utils.scores import get_dojo_scores
from CTFd.plugins.dojo_plugin.utils.stats import get_dojo_stats
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
dojo = Dojos.from_id({dojo!r}).one()
sentinels = {{
    module_cache.dojo_stats_cache_key(dojo): {{"sentinel": "stats", "solves": 999}},
    module_cache.dojo_scores_cache_key(dojo.dojo_id): {{
        "ranks": [999999],
        "solves": {{"999999": 999}},
    }},
}}
for duration in module_cache.SCOREBOARD_DURATIONS:
    sentinels[module_cache.dojo_scoreboard_cache_key(
        dojo.dojo_id,
        duration,
    )] = [{{"sentinel": "scoreboard"}}]
    sentinels[module_cache.dojo_scoreboard_cache_key(
        dojo.dojo_id,
        duration,
        "crews",
    )] = [{{"sentinel": "crews"}}]
for cache_key, sentinel in sentinels.items():
    assert set_cached_stat(cache_key, sentinel)

dojo_from_spec({updated_spec!r}, dojo=dojo)
db.session.commit()
db.session.expire_all()
dojo = Dojos.from_id({dojo!r}).one()
refresh = DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo.dojo_id,
    module_id="",
    cache_identity="",
).one()
aggregate_keys = module_cache.dojo_aggregate_cache_keys(dojo)
assert DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(aggregate_keys)
).count() == len(aggregate_keys)
db.session.rollback()

refresh_key = {{("dojo", dojo.dojo_id, "", "")}}
with patch.object(
    module_cache,
    "publish_stat_event",
    return_value=None,
) as publish:
    assert not module_cache.publish_pending_cache_refreshes(
        refresh_keys=refresh_key,
    )
    assert publish.called

with patch.object(
    module_cache,
    "publish_stat_event",
    return_value="1097-0",
):
    assert module_cache.publish_pending_cache_refreshes(
        refresh_keys=refresh_key,
    )
db.session.expire_all()
refresh = DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo.dojo_id,
    module_id="",
    cache_identity="",
).one()
assert refresh.published_at is not None
assert get_scoreboard_for(dojo, 0) == []
assert get_dojo_stats(dojo)["solves"] == 0
db.session.rollback()

r = get_redis_client()
with patch.object(
    module_cache,
    "invalidate_module_cache_keys",
    return_value=False,
):
    assert not module_cache.drain_module_cache_invalidations(aggregate_keys)
    assert DojoModuleCacheInvalidations.query.filter(
        DojoModuleCacheInvalidations.cache_key.in_(aggregate_keys)
    ).count() == len(aggregate_keys)
    for cache_key, sentinel in sentinels.items():
        assert get_cached_stat(cache_key) == sentinel
    for duration in module_cache.SCOREBOARD_DURATIONS:
        assert get_scoreboard_for(dojo, duration) == []
        assert get_crews_for(dojo, duration) == []
    assert get_dojo_stats(dojo)["solves"] == 0
    assert get_dojo_scores(dojo.dojo_id) == {{"ranks": [], "solves": {{}}}}

payload = {{
    "dojo_id": dojo.dojo_id,
    "generation": refresh.generation,
}}

def partial_write(current_dojo, event_timestamp=None):
    partial_key = module_cache.dojo_scoreboard_cache_key(
        current_dojo.dojo_id,
        0,
    )
    assert set_cached_stat(partial_key, [{{"partial": True}}])
    assert get_cached_stat(partial_key) == [{{"partial": True}}]
    assert get_scoreboard_for(current_dojo, 0) == []
    return False

with patch.object(
    cache_refresh,
    "_write_dojo_caches",
    side_effect=partial_write,
):
    assert not cache_refresh.handle_dojo_cache_refresh(payload)
assert DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo.dojo_id,
).count() == 1
assert get_scoreboard_for(dojo, 0) == []
db.session.rollback()
assert cache_refresh.handle_dojo_cache_refresh(payload)
assert not DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo.dojo_id,
).count()
db.session.expire_all()
dojo = Dojos.from_id({dojo!r}).one()
for duration in module_cache.SCOREBOARD_DURATIONS:
    assert get_scoreboard_for(dojo, duration) == []
    assert get_crews_for(dojo, duration) == []
assert "sentinel" not in get_dojo_stats(dojo)
assert get_dojo_stats(dojo)["challenges"] == 1
assert get_dojo_scores(dojo.dojo_id) == {{"ranks": [], "solves": {{}}}}
for cache_key in sentinels:
    assert r.get(cache_key) is not None
    assert get_cached_stat(cache_key) != sentinels[cache_key]
db.session.rollback()
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


def test_dojo_promotion_retires_old_reference_stats(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"promotion-cleanup-{suffix}",
        "name": "Promotion Cleanup",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    assert dojo != spec["id"]
    wait_for_background_worker(timeout=30)
    old_cache_key = f"stats:dojo:{dojo}"
    old_cache_keys = {
        old_cache_key,
        f"{old_cache_key}:updated",
        f"{old_cache_key}:version",
    }
    redis_cli(
        "MSET",
        old_cache_key,
        json.dumps({"sentinel": True}),
        f"{old_cache_key}:updated",
        "123",
        f"{old_cache_key}:version",
        "456",
    )
    assert redis_cli("EXISTS", *sorted(old_cache_keys)) == "3"

    make_dojo_official(dojo, admin_session)

    assert redis_cli("EXISTS", *sorted(old_cache_keys)) == "0"
    result = dojo_flask_run(f"""
from CTFd.plugins.dojo_plugin.models import Dojos

dojo = Dojos.query.filter_by(id={spec["id"]!r}).one()
assert dojo.official
assert dojo.reference_id == {spec["id"]!r}
print("OK")
""")
    assert "OK" in result.stdout


def test_challenge_name_only_update_refreshes_recent_solves(
    admin_session,
    random_user,
):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"recent-rename-{suffix}",
        "name": "Recent Rename",
        "type": "public",
        "modules": [{
            "id": "module",
            "name": "Module",
            "challenges": [{
                "id": "challenge",
                "name": "Old Challenge Name",
                "image": "pwncollege/challenge-simple",
            }],
        }],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    random_user_name, random_user_session = random_user
    user_id = get_user_id(random_user_name)
    renamed_spec = {
        **spec,
        "modules": [{
            **spec["modules"][0],
            "challenges": [{
                **spec["modules"][0]["challenges"][0],
                "name": "New Challenge Name",
            }],
        }],
    }
    wait_for_background_worker(timeout=30)

    result = dojo_flask_run(f"""
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModuleCacheInvalidations, DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
dojo = Dojos.from_id({dojo!r}).one()
module = DojoModules.from_id({dojo!r}, "module").one()
old_identity = module.cache_identity
old_launch = module.cache_launched_at
user = Users.query.get({user_id})
db.session.add(Solves(
    user_id=user.id,
    challenge_id=module.challenges[0].challenge_id,
    ip="127.0.0.1",
    provided="rename",
))
db.session.commit()
db.session.expire_all()
dojo = Dojos.from_id({dojo!r}).one()
assert cache_refresh._write_dojo_caches(dojo)
db.session.commit()
assert get_cached_stat(
    module_cache.dojo_stats_cache_key(dojo)
)["recent_solves"][0]["challenge_name"] == "Old Challenge Name"

dojo_from_spec({renamed_spec!r}, dojo=dojo)
db.session.commit()
db.session.expire_all()
dojo = Dojos.from_id({dojo!r}).one()
module = DojoModules.from_id({dojo!r}, "module").one()
assert module.cache_identity != old_identity
assert module.cache_launched_at == old_launch
refresh = DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo.dojo_id,
    module_id="",
    cache_identity="",
).one()
aggregate_keys = module_cache.dojo_aggregate_cache_keys(dojo)
assert DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(aggregate_keys)
).count() == len(aggregate_keys)
generation = refresh.generation
module_refresh = DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=dojo.dojo_id,
    module_id=module.id,
    cache_identity=module.cache_identity,
).one()
module_payload = {{
    "dojo_id": module.dojo_id,
    "module_id": module.id,
    "cache_identity": module.cache_identity,
    "generation": module_refresh.generation,
}}
db.session.rollback()

assert cache_refresh.handle_module_cache_refresh(module_payload)
assert cache_refresh.handle_dojo_cache_refresh({{
    "dojo_id": dojo.dojo_id,
    "generation": generation,
}})
db.session.expire_all()
dojo = Dojos.from_id({dojo!r}).one()
module = DojoModules.from_id({dojo!r}, "module").one()
user = Users.query.get({user_id})
assert module.solves(
    user=user,
    ignore_visibility=True,
    ignore_admins=False,
).count() == 1
assert [
    entry["user_id"]
    for entry in get_cached_stat(
        module_cache.module_scoreboard_cache_key(module, 0)
    )
] == [{user_id}]
recent_solves = get_cached_stat(
    module_cache.dojo_stats_cache_key(dojo)
)["recent_solves"]
assert recent_solves[0]["challenge_name"] == "New Challenge Name"
assert not DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo.dojo_id,
).count()
db.session.rollback()
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout
    module_page = random_user_session.get(f"{DOJO_URL}/{dojo}/module")
    assert module_page.status_code == 200
    assert "challenge-solved" in module_page.text
    solve_response = random_user_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/module/challenge/solve",
        json={"submission": "already solved"},
    )
    assert solve_response.status_code == 200
    assert solve_response.json()["status"] == "already_solved"


def test_dojo_deletion_retires_all_module_caches(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-delete-{suffix}",
        "name": "Cache Delete",
        "type": "public",
        "modules": [
            cache_identity_module("first", "one"),
            cache_identity_module("second", "two"),
        ],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    states = get_module_cache_states(dojo)
    dojo_id = states[0]["dojo_id"]
    identity_keys = set().union(*(
        identity_module_cache_keys(dojo_id, state["identity"])
        for state in states
    ))
    legacy_keys = legacy_module_cache_keys(
        dojo_id, {state["index"] for state in states}
    )
    retired_keys = identity_keys | legacy_keys
    redis_cli("MSET", *[
        item
        for key in sorted(retired_keys)
        for item in (key, "stale")
    ])

    result = dojo_flask_run(f"""
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoModuleCacheInvalidations, Dojos
from CTFd.plugins.dojo_plugin.utils.module_cache import queue_dojo_module_cache_retirement

dojo = Dojos.from_id({dojo!r}).one()
cache_keys = queue_dojo_module_cache_retirement(dojo)
assert DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
).count() == len(cache_keys)
db.session.rollback()
assert not DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
).count()
db.session.rollback()
print("OK")
""")
    assert "OK" in result.stdout
    assert redis_cli("EXISTS", *sorted(retired_keys)) == str(len(retired_keys))

    response = admin_session.post(
        f"{DOJO_URL}/dojo/{dojo}/delete/",
        json={"dojo": dojo},
    )
    assert response.status_code == 200
    assert redis_cli("EXISTS", *sorted(retired_keys)) == "0"
    assert admin_session.get(f"{DOJO_URL}/{dojo}/").status_code == 404


@pytest.mark.timeout(180)
def test_deletion_outboxes_recover_beyond_drain_bound(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-large-delete-{suffix}",
        "name": "Cache Large Delete",
        "type": "public",
        "modules": [
            {"id": f"module-{index:02d}", "name": f"Module {index:02d}"}
            for index in range(63)
        ],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    wait_for_background_worker(timeout=30)
    result = dojo_flask_run(f"""
import time
import redis
from unittest.mock import patch

from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import (
    DojoCacheRefreshes,
    DojoModuleCacheInvalidations,
    DojoUsers,
    Dojos,
)
import CTFd.plugins.dojo_plugin.utils.background_stats as background_stats
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
from CTFd.plugins.dojo_plugin.worker.handlers import handle_stat_event

dojo_model = Dojos.from_id({dojo!r}).one()
target = module_cache.module_cache_target(dojo_model.modules[0])
maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
assert module_cache.drain_module_cache_invalidations()
module_cache.queue_cache_refreshes(module_targets=(target,))
cache_keys = module_cache.queue_dojo_module_cache_retirement(dojo_model)
assert len(cache_keys) > (
    module_cache.INVALIDATION_BATCH_SIZE
    * module_cache.INVALIDATION_MAX_BATCHES
)
r = background_stats.get_redis_client()
r.mset({{cache_key: "stale" for cache_key in cache_keys}})
DojoUsers.query.filter(DojoUsers.dojo_id == dojo_model.dojo_id).delete()
Dojos.query.filter(Dojos.dojo_id == dojo_model.dojo_id).delete()
db.session.commit()

with patch.object(
    module_cache,
    "get_redis_client",
    side_effect=redis.ConnectionError("unavailable"),
) as get_client:
    assert not module_cache.maintain_module_cache_outboxes()
    assert get_client.call_count == 3
assert r.exists(*cache_keys) == len(cache_keys)
assert DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
).count() == len(cache_keys)
assert DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).count() == 0
db.session.rollback()

class PollRedis:
    def __init__(self):
        self.messages = []
        self.message_index = 0
        self.empty_reads = 0

    def xgroup_create(self, *args, **kwargs):
        return True

    def xadd(self, stream_name, fields):
        self.message_index += 1
        message_id = f"{{int(time.time() * 1000) + self.message_index}}-0"
        self.messages.append((message_id, fields))
        return message_id

    def xreadgroup(self, group, consumer, streams, count, block):
        if self.messages:
            messages = list(self.messages)
            self.messages.clear()
            return [(next(iter(streams)), messages)]
        self.empty_reads += 1
        if self.empty_reads > 1:
            raise KeyboardInterrupt
        return []

    def xackdel(self, *args):
        return 1

    def time(self):
        now = time.time()
        return int(now), int((now % 1) * 1_000_000)

poll_redis = PollRedis()
progress = []

def maintenance_poll():
    result = module_cache.maintain_module_cache_outboxes(refresh_keys={{(
        "module",
        target.dojo_id,
        target.module_id,
        target.cache_identity,
    )}})
    db.session.expire_all()
    progress.append((
        DojoModuleCacheInvalidations.query.filter(
            DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
        ).count(),
        DojoCacheRefreshes.query.filter_by(
            kind="module",
            dojo_id=target.dojo_id,
            module_id=target.module_id,
            cache_identity=target.cache_identity,
        ).count(),
        result,
    ))
    db.session.rollback()

with patch.object(
    background_stats,
    "get_redis_client",
    return_value=poll_redis,
):
    background_stats.consume_stat_events(
        handler=handle_stat_event,
        batch_size=10,
        block_ms=0,
        maintenance_handler=maintenance_poll,
        maintenance_interval=0,
    )

assert progress[0] == (
    len(cache_keys)
    - module_cache.INVALIDATION_BATCH_SIZE
    * module_cache.INVALIDATION_MAX_BATCHES,
    0,
    False,
)
assert progress[-1] == (0, 0, True)
assert not r.exists(*cache_keys)
assert not DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
).count()
assert not DojoCacheRefreshes.query.filter_by(dojo_id=target.dojo_id).count()
assert not Dojos.query.filter_by(dojo_id=target.dojo_id).count()
db.session.rollback()
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


def test_module_cache_event_routing(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-routing-{suffix}",
        "name": "Cache Routing",
        "type": "public",
        "modules": [cache_identity_module("retired", "one")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    retired = get_module_cache_states(dojo)[0]
    spec["modules"] = [cache_identity_module("fresh", "two")]
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=spec,
    )
    assert response.status_code == 200
    current = get_module_cache_states(dojo)[0]
    assert current["index"] == retired["index"]
    assert current["identity"] != retired["identity"]

    result = dojo_flask_run(f"""
import json
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules
from CTFd.plugins.dojo_plugin.utils.background_stats import get_message_timestamp, get_redis_client, set_cached_stat
from CTFd.plugins.dojo_plugin.utils.module_cache import module_challenge_solves_cache_key, module_scoreboard_cache_key, module_scores_cache_key
from CTFd.plugins.dojo_plugin.worker.handlers.scoreboard import handle_scoreboard_update
from CTFd.plugins.dojo_plugin.worker.handlers.scores import handle_scores_update
from CTFd.plugins.dojo_plugin.worker.handlers.solve import handle_challenge_solve

module = DojoModules.from_id({dojo!r}, "fresh").one()
old_identity = {retired["identity"]!r}
old_keys = [
    f"stats:scoreboard:module:{{module.dojo_id}}:{{old_identity}}:0",
    f"stats:crews:module:{{module.dojo_id}}:{{old_identity}}:0",
    f"stats:challenge_solves:module:{{module.dojo_id}}:{{old_identity}}",
    f"stats:scores:module:{{module.dojo_id}}:{{old_identity}}",
]
r = get_redis_client()
for key in old_keys:
    r.set(key, '"old-instance"')
handle_scoreboard_update({{
    "model_type": "module",
    "model_id": {{"dojo_id": module.dojo_id, "module_index": module.module_index}},
}})
handle_scores_update({{"dojo_id": module.dojo_id}})
db.session.expire_all()
module = DojoModules.from_id({dojo!r}, "fresh").one()
assert r.get(module_scoreboard_cache_key(module, 0)) is not None
assert r.get(module_scoreboard_cache_key(module, 0, "crews")) is not None
assert r.get(module_challenge_solves_cache_key(module)) is not None
assert r.get(module_scores_cache_key(module)) is not None
assert [r.get(key) for key in old_keys] == ['"old-instance"'] * 4

user = Users(
    name={f'event-routing-{suffix}'!r},
    email={f'event-routing-{suffix}@example.com'!r},
    password="password",
)
db.session.add(user)
db.session.flush()
challenge_id = module.challenges[0].challenge_id
set_cached_stat(module_challenge_solves_cache_key(module), {{"999999": 1}})
db.session.add(Solves(
    user_id=user.id,
    challenge_id=challenge_id,
    ip="127.0.0.1",
    provided="event-routing",
))
db.session.commit()
event_timestamp = get_message_timestamp(
    r.xadd("stat:test-timestamps", {{"event": "routing"}})
)
handle_challenge_solve({{
    "user_id": user.id,
    "challenge_id": challenge_id,
}}, event_timestamp)
db.session.expire_all()
module = DojoModules.from_id({dojo!r}, "fresh").one()
scoreboard = json.loads(r.get(module_scoreboard_cache_key(module, 0)))
challenge_solves = json.loads(r.get(module_challenge_solves_cache_key(module)))
scores = json.loads(r.get(module_scores_cache_key(module)))
assert any(entry["user_id"] == user.id for entry in scoreboard)
assert challenge_solves[str(challenge_id)] == 1
assert user.id in scores["ranks"]
assert [r.get(key) for key in old_keys] == ['"old-instance"'] * 4
print("OK")
""")
    assert "OK" in result.stdout


def test_solve_updates_duplicate_import_association_multiplicity(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_spec = {
        "id": f"score-source-{suffix}",
        "name": "Score Source",
        "type": "public",
        "modules": [cache_identity_module("source", "shared")],
    }
    source = create_dojo_yml(yaml.safe_dump(source_spec), session=admin_session)
    make_dojo_official(source, admin_session)

    def imported_challenge(challenge_id, name, required=True):
        return {
            "id": challenge_id,
            "name": name,
            "required": required,
            "import": {
                "dojo": source_spec["id"],
                "module": "source",
                "challenge": "shared",
            },
        }

    consumer_spec = {
        "id": f"score-consumer-{suffix}",
        "name": "Score Consumer",
        "type": "public",
        "modules": [
            {
                "id": "double-required",
                "name": "Double Required",
                "challenges": [
                    imported_challenge("required-a", "Required A"),
                    imported_challenge("required-b", "Required B"),
                ],
            },
            {
                "id": "mixed",
                "name": "Mixed",
                "challenges": [
                    imported_challenge("mixed-required", "Mixed Required"),
                    imported_challenge(
                        "mixed-optional",
                        "Mixed Optional",
                        required=False,
                    ),
                ],
            },
        ],
    }
    consumer = create_dojo_yml(
        yaml.safe_dump(consumer_spec),
        session=admin_session,
    )
    wait_for_background_worker(timeout=30)

    result = dojo_flask_run(f"""
import json

from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_message_timestamp, get_redis_client, set_cached_stat
from CTFd.plugins.dojo_plugin.utils.crews import aggregate_crews
from CTFd.plugins.dojo_plugin.utils.module_cache import drain_module_cache_invalidations, module_challenge_solves_cache_key, module_scoreboard_cache_key, module_scores_cache_key
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.dojo_stats as dojo_stats_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scoreboard as scoreboard_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scores as scores_handler
import CTFd.plugins.dojo_plugin.worker.handlers.solve as solve_handler

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    assert drain_module_cache_invalidations()
    dojo_references = {[source, consumer]!r}

    def load_dojos():
        return {{
            reference: Dojos.from_id(reference).one()
            for reference in dojo_references
        }}

    dojos = load_dojos()
    dojo = dojos[{consumer!r}]
    modules = {{module.id: module for module in dojo.modules}}
    double_required = modules["double-required"]
    mixed = modules["mixed"]
    challenge_ids = {{
        challenge.challenge_id
        for module in modules.values()
        for challenge in module.challenges
    }}
    assert len(challenge_ids) == 1
    challenge_id = challenge_ids.pop()
    assert [challenge.required for challenge in double_required.challenges] == [True, True]
    assert [challenge.required for challenge in mixed.challenges] == [True, False]

    user = Users(
        name={f'duplicate-{suffix} [Multiplicity]'!r},
        email={f'duplicate-{suffix}@example.com'!r},
        password="password",
    )
    db.session.add(user)
    db.session.commit()
    user_id = user.id
    db.session.expire_all()
    dojos = load_dojos()

    for current_dojo in dojos.values():
        for duration in scoreboard_handler.COMMON_DURATIONS:
            dojo_scoreboard = scoreboard_handler.calculate_scoreboard(
                current_dojo,
                duration,
            )
            assert scoreboard_handler.set_scoreboard_cache(
                f"stats:scoreboard:dojo:{{current_dojo.dojo_id}}:{{duration}}",
                dojo_scoreboard,
                scoreboard_handler.calculate_member_challenges(
                    current_dojo,
                    duration,
                    dojo_scoreboard,
                ),
            )
            for module in current_dojo.modules:
                module_scoreboard = scoreboard_handler.calculate_scoreboard(
                    module,
                    duration,
                )
                assert scoreboard_handler.set_scoreboard_cache(
                    module_scoreboard_cache_key(module, duration),
                    module_scoreboard,
                    scoreboard_handler.calculate_member_challenges(
                        module,
                        duration,
                        module_scoreboard,
                    ),
                )
        assert set_cached_stat(
            f"stats:dojo:{{current_dojo.reference_id}}",
            dojo_stats_handler.calculate_dojo_stats(current_dojo),
        )
        assert set_cached_stat(
            scores_handler.dojo_scores_cache_key(current_dojo.dojo_id),
            scores_handler.calculate_dojo_scores(current_dojo.dojo_id),
        )
        for module in current_dojo.modules:
            assert set_cached_stat(
                module_challenge_solves_cache_key(module),
                scoreboard_handler.calculate_challenge_solves(module),
            )
            assert set_cached_stat(
                module_scores_cache_key(module),
                scores_handler.calculate_module_scores(module),
            )

    solve = Solves(
        user_id=user_id,
        challenge_id=challenge_id,
        ip="127.0.0.1",
        provided="duplicate-import",
    )
    db.session.add(solve)
    db.session.commit()
    event_timestamp = get_message_timestamp(
        get_redis_client().xadd(
            "stat:test-timestamps",
            {{"event": "duplicate-association"}},
        )
    )
    solve_handler.handle_challenge_solve({{
        "user_id": user_id,
        "challenge_id": challenge_id,
        "solve_date": solve.date.isoformat(),
    }}, event_timestamp)

    db.session.expire_all()
    dojos = load_dojos()

    def json_value(value):
        return json.loads(json.dumps(value))

    for current_dojo in dojos.values():
        for duration in scoreboard_handler.COMMON_DURATIONS:
            expected_scoreboard = scoreboard_handler.calculate_scoreboard(
                current_dojo,
                duration,
            )
            expected_crews = aggregate_crews(
                expected_scoreboard,
                scoreboard_handler.calculate_member_challenges(
                    current_dojo,
                    duration,
                    expected_scoreboard,
                ),
            )
            assert get_cached_stat(
                f"stats:scoreboard:dojo:{{current_dojo.dojo_id}}:{{duration}}"
            ) == json_value(expected_scoreboard)
            assert get_cached_stat(
                f"stats:crews:dojo:{{current_dojo.dojo_id}}:{{duration}}"
            ) == json_value(expected_crews)
            for module in current_dojo.modules:
                expected_module_scoreboard = scoreboard_handler.calculate_scoreboard(
                    module,
                    duration,
                )
                expected_module_crews = aggregate_crews(
                    expected_module_scoreboard,
                    scoreboard_handler.calculate_member_challenges(
                        module,
                        duration,
                        expected_module_scoreboard,
                    ),
                )
                assert get_cached_stat(
                    module_scoreboard_cache_key(module, duration)
                ) == json_value(expected_module_scoreboard)
                assert get_cached_stat(
                    module_scoreboard_cache_key(module, duration, "crews")
                ) == json_value(expected_module_crews)

        expected_stats = dojo_stats_handler.calculate_dojo_stats(current_dojo)
        assert get_cached_stat(
            f"stats:dojo:{{current_dojo.reference_id}}"
        ) == json_value(expected_stats)
        assert get_cached_stat(
            scores_handler.dojo_scores_cache_key(current_dojo.dojo_id)
        ) == json_value(scores_handler.calculate_dojo_scores(
            current_dojo.dojo_id,
        ))
        for module in current_dojo.modules:
            assert get_cached_stat(
                module_challenge_solves_cache_key(module)
            ) == json_value(scoreboard_handler.calculate_challenge_solves(module))
            assert get_cached_stat(
                module_scores_cache_key(module)
            ) == json_value(scores_handler.calculate_module_scores(module))

    dojo = dojos[{consumer!r}]
    modules = {{module.id: module for module in dojo.modules}}
    expected_stats = dojo_stats_handler.calculate_dojo_stats(dojo)
    assert expected_stats["solves"] == 3
    assert [
        solve["challenge_name"] for solve in expected_stats["recent_solves"]
    ] == ["Required A", "Required B", "Mixed Required"]
    assert get_cached_stat(
        scores_handler.dojo_scores_cache_key(dojo.dojo_id)
    )["solves"][str(user_id)] == 4
    assert get_cached_stat(
        module_challenge_solves_cache_key(modules["double-required"])
    ) == {{str(challenge_id): 2}}
    assert get_cached_stat(
        module_challenge_solves_cache_key(modules["mixed"])
    ) == {{str(challenge_id): 1}}
    assert get_cached_stat(
        module_scores_cache_key(modules["double-required"])
    )["solves"][str(user_id)] == 2
    assert get_cached_stat(
        module_scores_cache_key(modules["mixed"])
    )["solves"][str(user_id)] == 2
    db.session.rollback()
    print("OK")
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    assert "OK" in result.stdout


def test_module_cache_writers_are_serialized(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-writers-{suffix}",
        "name": "Cache Writers",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    script = """
import threading
from unittest.mock import patch

from flask import current_app
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_message_timestamp, get_redis_client, set_cached_stat
from CTFd.plugins.dojo_plugin.utils.module_cache import module_challenge_solves_cache_key, module_scoreboard_cache_key, module_scores_cache_key
import CTFd.plugins.dojo_plugin.worker.handlers.solve as solve_handler

dojo_ref = __DOJO_REF__
suffix = __SUFFIX__
module = DojoModules.from_id(dojo_ref, "module").one()
challenge_id = module.challenges[0].challenge_id
user_a = Users(name=f"writer-a-{suffix} [Alpha]", email=f"writer-a-{suffix}@example.com", password="password")
user_b = Users(name=f"writer-b-{suffix} [Beta]", email=f"writer-b-{suffix}@example.com", password="password")
db.session.add_all([user_a, user_b])
db.session.flush()
user_ids = [user_a.id, user_b.id]
db.session.add_all([
    Solves(user_id=user_id, challenge_id=challenge_id, ip="127.0.0.1", provided="solve")
    for user_id in user_ids
])
db.session.commit()
db.session.expire_all()
module = DojoModules.from_id(dojo_ref, "module").one()

scoreboard_key = module_scoreboard_cache_key(module, 0)
crews_key = module_scoreboard_cache_key(module, 0, "crews")
challenge_solves_key = module_challenge_solves_cache_key(module)
scores_key = module_scores_cache_key(module)
set_cached_stat(scoreboard_key, [])
set_cached_stat(crews_key, [])
set_cached_stat(challenge_solves_key, {str(challenge_id): 0})
set_cached_stat(scores_key, {"ranks": [], "solves": {}})

app = current_app._get_current_object()
errors = []

def start_in_app(function):
    def run():
        with app.app_context():
            try:
                function()
            except Exception as error:
                errors.append(repr(error))
            finally:
                db.session.remove()
    thread = threading.Thread(target=run)
    thread.start()
    return thread

first_acquired = threading.Event()
second_acquired = threading.Event()
release_first = threading.Event()
acquisition_guard = threading.Lock()
acquisition_count = 0
real_lock = solve_handler.lock_module_cache_target

def delayed_lock(target):
    global acquisition_count
    locked_module = real_lock(target)
    if not locked_module:
        return None
    with acquisition_guard:
        acquisition_count += 1
        acquisition_order = acquisition_count
    if acquisition_order == 1:
        first_acquired.set()
        assert release_first.wait(10)
    else:
        second_acquired.set()
    return locked_module

r = get_redis_client()
event_timestamps = [
    get_message_timestamp(
        r.xadd("stat:test-timestamps", {"event": event})
    )
    for event in ("writer-a", "writer-b")
]
with patch.object(solve_handler, "lock_module_cache_target", delayed_lock):
    first_thread = start_in_app(lambda: solve_handler.handle_challenge_solve({
        "user_id": user_ids[0],
        "challenge_id": challenge_id,
    }, event_timestamps[0]))
    assert first_acquired.wait(10)
    second_thread = start_in_app(lambda: solve_handler.handle_challenge_solve({
        "user_id": user_ids[1],
        "challenge_id": challenge_id,
    }, event_timestamps[1]))
    assert not second_acquired.wait(0.2)
    release_first.set()
    first_thread.join(10)
    second_thread.join(10)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
assert not errors
assert second_acquired.is_set()

scoreboard = get_cached_stat(scoreboard_key)
crews = get_cached_stat(crews_key)
challenge_solves = get_cached_stat(challenge_solves_key)
scores = get_cached_stat(scores_key)
assert {entry["user_id"] for entry in scoreboard} == set(user_ids)
assert {
    member["user_id"] for crew in crews for member in crew["members"]
} == set(user_ids)
assert challenge_solves == {str(challenge_id): 2}
assert set(scores["ranks"]) == set(user_ids)
assert scores["solves"] == {str(user_id): 1 for user_id in user_ids}
print("OK")
"""
    result = dojo_flask_run(
        script.replace("__DOJO_REF__", repr(dojo)).replace(
            "__SUFFIX__",
            repr(suffix),
        ),
    )
    assert "OK" in result.stdout


def test_solve_target_removed_before_lock(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-target-removal-{suffix}",
        "name": "Cache Target Removal",
        "type": "public",
        "modules": [
            cache_identity_module("removed", "one"),
            cache_identity_module("remaining", "two"),
        ],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    script = """
import threading
from unittest.mock import patch

from flask import current_app
from CTFd.models import Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_message_timestamp, get_redis_client
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
from CTFd.plugins.dojo_plugin.utils.module_cache import drain_module_cache_invalidations, module_identity_cache_keys
import CTFd.plugins.dojo_plugin.worker.handlers.solve as solve_handler

dojo_ref = __DOJO_REF__
spec = __SPEC__
module = DojoModules.from_id(dojo_ref, "removed").one()
challenge_id = module.challenges[0].challenge_id
dojo_id = module.dojo_id
cache_identity = module.cache_identity
user_id = Users.query.order_by(Users.id).first().id
r = get_redis_client()
event_timestamp = get_message_timestamp(
    r.xadd("stat:test-timestamps", {"event": "target-removal"})
)
retired_keys = module_identity_cache_keys(dojo_id, cache_identity)
r.mset({key: "stale" for key in retired_keys})

app = current_app._get_current_object()
target_captured = threading.Event()
resume = threading.Event()
update_done = threading.Event()
errors = []
captured = []
real_lock = solve_handler.lock_module_cache_target

def delayed_lock(target):
    captured.append(target)
    target_captured.set()
    assert resume.wait(10)
    return real_lock(target)

def handle_solve():
    with app.app_context():
        try:
            solve_handler.handle_challenge_solve({
                "user_id": user_id,
                "challenge_id": challenge_id,
            }, event_timestamp)
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()

def remove_module():
    with app.app_context():
        try:
            dojo_model = Dojos.from_id(dojo_ref).one()
            dojo_from_spec(
                {**spec, "modules": [spec["modules"][1]]},
                dojo=dojo_model,
            )
            db.session.commit()
            drain_module_cache_invalidations()
            update_done.set()
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()

with patch.object(solve_handler, "lock_module_cache_target", delayed_lock):
    thread = threading.Thread(target=handle_solve)
    thread.start()
    assert target_captured.wait(10)
    update_thread = threading.Thread(target=remove_module)
    update_thread.start()
    assert not update_done.wait(0.2)
    resume.set()
    thread.join(10)
    update_thread.join(10)
    assert not thread.is_alive()
    assert not update_thread.is_alive()

assert not errors
assert update_done.is_set()
assert len(captured) == 1
assert captured[0].module_id == "removed"
assert captured[0].cache_identity == cache_identity
assert not r.exists(*retired_keys)
print("OK")
"""
    result = dojo_flask_run(
        script.replace("__DOJO_REF__", repr(dojo)).replace(
            "__SPEC__",
            repr(spec),
        ),
    )
    assert "OK" in result.stdout


def test_module_cache_reorder_interleaving(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-interleaving-{suffix}",
        "name": "Cache Interleaving",
        "type": "public",
        "modules": [
            cache_identity_module("first", "one"),
            cache_identity_module("second", "two"),
        ],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    script = """
import json
import threading
from unittest.mock import patch

from flask import current_app
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
from CTFd.plugins.dojo_plugin.utils.module_cache import drain_module_cache_invalidations, module_challenge_solves_cache_key, module_identity_cache_keys, module_scoreboard_cache_key, module_scores_cache_key, pending_module_cache_invalidations
import CTFd.plugins.dojo_plugin.worker.handlers.scoreboard as scoreboard_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scores as scores_handler

dojo_ref = __DOJO_REF__
spec = __SPEC__
suffix = dojo_ref.split("~", 1)[0][-8:]
user_a = Users(name=f"cache-a-{suffix} [Alpha]", email=f"cache-a-{suffix}@example.com", password="password")
user_b = Users(name=f"cache-b-{suffix} [Beta]", email=f"cache-b-{suffix}@example.com", password="password")
db.session.add_all([user_a, user_b])
db.session.flush()
user_a_id = user_a.id
user_b_id = user_b.id
module_a = DojoModules.from_id(dojo_ref, "first").one()
module_b = DojoModules.from_id(dojo_ref, "second").one()
challenge_a_id = module_a.challenges[0].challenge_id
challenge_b_id = module_b.challenges[0].challenge_id
db.session.add_all([
    Solves(user_id=user_a_id, challenge_id=challenge_a_id, ip="127.0.0.1", provided="a"),
    Solves(user_id=user_b_id, challenge_id=challenge_b_id, ip="127.0.0.1", provided="b"),
])
db.session.commit()
dojo_id = Dojos.from_id(dojo_ref).one().dojo_id
db.session.rollback()
app = current_app._get_current_object()
errors = []

def start_in_app(function):
    def run():
        with app.app_context():
            try:
                function()
            except Exception as error:
                errors.append(repr(error))
            finally:
                db.session.remove()
    thread = threading.Thread(target=run)
    thread.start()
    return thread

def apply_spec(updated_spec):
    dojo_model = Dojos.from_id(dojo_ref).one()
    dojo_from_spec(updated_spec, dojo=dojo_model)
    db.session.commit()
    drain_module_cache_invalidations()

loaded = threading.Event()
resume = threading.Event()
reorder_done = threading.Event()
real_scoreboard_lock = scoreboard_handler.lock_module_cache_target

def delayed_scoreboard_lock(target):
    loaded.set()
    assert resume.wait(10)
    return real_scoreboard_lock(target)

with patch.object(scoreboard_handler, "lock_module_cache_target", delayed_scoreboard_lock):
    thread = start_in_app(lambda: scoreboard_handler.handle_scoreboard_update({
        "model_type": "module",
        "model_id": {"dojo_id": dojo_id, "module_index": 0},
    }))
    assert loaded.wait(10)
    reordered_spec = {**spec, "modules": list(reversed(spec["modules"]))}
    reorder_thread = start_in_app(lambda: (
        apply_spec(reordered_spec),
        reorder_done.set(),
    ))
    assert not reorder_done.wait(0.2)
    resume.set()
    thread.join(10)
    reorder_thread.join(10)
    assert not thread.is_alive()
    assert not reorder_thread.is_alive()
assert not errors
assert reorder_done.is_set()

module_a = DojoModules.from_id(dojo_ref, "first").one()
module_b = DojoModules.from_id(dojo_ref, "second").one()
r = get_redis_client()
scoreboard = json.loads(r.get(module_scoreboard_cache_key(module_a, 0)))
crews = json.loads(r.get(module_scoreboard_cache_key(module_a, 0, "crews")))
challenge_solves = json.loads(r.get(module_challenge_solves_cache_key(module_a)))
assert {entry["user_id"] for entry in scoreboard} == {user_a_id}
assert {
    member["user_id"] for crew in crews for member in crew["members"]
} == {user_a_id}
assert challenge_solves == {str(challenge_a_id): 1}
assert str(challenge_b_id) not in challenge_solves
db.session.rollback()

loaded = threading.Event()
resume = threading.Event()
reorder_done = threading.Event()
real_scores_lock = scores_handler.lock_module_cache_target

def delayed_scores_lock(target):
    loaded.set()
    assert resume.wait(10)
    return real_scores_lock(target)

with patch.object(scores_handler, "lock_module_cache_target", delayed_scores_lock):
    thread = start_in_app(lambda: scores_handler.handle_scores_update({"dojo_id": dojo_id}))
    assert loaded.wait(10)
    reorder_thread = start_in_app(lambda: (
        apply_spec(spec),
        reorder_done.set(),
    ))
    assert not reorder_done.wait(0.2)
    resume.set()
    thread.join(10)
    reorder_thread.join(10)
    assert not thread.is_alive()
    assert not reorder_thread.is_alive()
assert not errors
assert reorder_done.is_set()

module_b = DojoModules.from_id(dojo_ref, "second").one()
scores = json.loads(r.get(module_scores_cache_key(module_b)))
assert scores["ranks"] == [user_b_id]
assert scores["solves"] == {str(user_b_id): 1}
db.session.rollback()

module_a = DojoModules.from_id(dojo_ref, "first").one()
retired_identity = module_a.cache_identity
calculation_started = threading.Event()
resume_calculation = threading.Event()
replacement_done = threading.Event()
replacement_started = threading.Event()
real_calculate_scoreboard = scoreboard_handler.calculate_scoreboard

def delayed_calculate_scoreboard(model, duration):
    if duration == 0 and not calculation_started.is_set():
        calculation_started.set()
        assert resume_calculation.wait(10)
    return real_calculate_scoreboard(model, duration)

replacement_spec = {
    **spec,
    "modules": [
        {
            "id": "fresh",
            "name": "Fresh",
            "challenges": [{
                "id": "three",
                "name": "Three",
                "image": "pwncollege/challenge-simple",
            }],
        },
        spec["modules"][1],
    ],
}

def replace_module():
    replacement_started.set()
    apply_spec(replacement_spec)
    replacement_done.set()

with patch.object(scoreboard_handler, "calculate_scoreboard", delayed_calculate_scoreboard):
    calculating_thread = start_in_app(lambda: scoreboard_handler.handle_scoreboard_update({
        "model_type": "module",
        "model_id": {"dojo_id": dojo_id, "module_index": 0},
    }))
    assert calculation_started.wait(10)
    replacement_thread = start_in_app(replace_module)
    assert replacement_started.wait(10)
    assert not replacement_done.wait(0.2)
    resume_calculation.set()
    calculating_thread.join(10)
    replacement_thread.join(10)
    assert not calculating_thread.is_alive()
    assert not replacement_thread.is_alive()
assert not errors
assert not r.exists(*module_identity_cache_keys(dojo_id, retired_identity))
pending_keys = {key for key, _ in pending_module_cache_invalidations()}
assert not module_identity_cache_keys(dojo_id, retired_identity) & pending_keys
print("OK")
"""
    result = dojo_flask_run(
        script.replace("__DOJO_REF__", repr(dojo)).replace(
            "__SPEC__",
            repr(spec),
        ),
    )
    assert "OK" in result.stdout


def test_stable_refresh_target_survives_pure_reorder(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-stable-refresh-{suffix}",
        "name": "Cache Stable Refresh",
        "type": "public",
        "modules": [
            cache_identity_module("first", "one"),
            cache_identity_module("second", "two"),
        ],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    reordered_spec = {**spec, "modules": list(reversed(spec["modules"]))}
    result = dojo_flask_run(f"""
import datetime

from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModules, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_redis_client
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
from CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh import handle_module_cache_refresh

dojo_ref = {dojo!r}
dojo_model = Dojos.from_id(dojo_ref).one()
first = DojoModules.from_id(dojo_ref, "first").one()
second = DojoModules.from_id(dojo_ref, "second").one()
first_identity = first.cache_identity
second_identity = second.cache_identity
first_challenge_id = first.challenges[0].challenge_id
second_challenge_id = second.challenges[0].challenge_id
first_user = Users(
    name="stable-first-{suffix}",
    email="stable-first-{suffix}@example.com",
    password="password",
)
second_user = Users(
    name="stable-second-{suffix}",
    email="stable-second-{suffix}@example.com",
    password="password",
)
db.session.add_all([first_user, second_user])
db.session.flush()
first_user_id = first_user.id
second_user_id = second_user.id
db.session.add_all([
    Solves(
        user_id=first_user_id,
        challenge_id=first_challenge_id,
        ip="127.0.0.1",
        provided="first",
    ),
    Solves(
        user_id=second_user_id,
        challenge_id=second_challenge_id,
        ip="127.0.0.1",
        provided="second",
    ),
])
target = module_cache.module_cache_target(first)
module_cache.queue_cache_refreshes(module_targets=(target,))
db.session.flush()
refresh = DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).one()
refresh.published_at = datetime.datetime.utcnow() + datetime.timedelta(days=1)
generation = refresh.generation
db.session.commit()

dojo_model = Dojos.from_id(dojo_ref).one()
dojo_from_spec({reordered_spec!r}, dojo=dojo_model)
db.session.commit()
assert module_cache.drain_module_cache_invalidations()
db.session.expire_all()
first = DojoModules.from_id(dojo_ref, "first").one()
second = DojoModules.from_id(dojo_ref, "second").one()
assert first.module_index == 1
assert second.module_index == 0
assert first.cache_identity == first_identity
assert second.cache_identity == second_identity

r = get_redis_client()
r.delete(*module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
))
assert handle_module_cache_refresh({{
    "dojo_id": target.dojo_id,
    "module_id": target.module_id,
    "cache_identity": target.cache_identity,
    "generation": generation,
}})
db.session.expire_all()
first = DojoModules.from_id(dojo_ref, "first").one()
first_scoreboard = get_cached_stat(
    module_cache.module_scoreboard_cache_key(first, 0)
)
first_challenge_solves = get_cached_stat(
    module_cache.module_challenge_solves_cache_key(first)
)
first_scores = get_cached_stat(module_cache.module_scores_cache_key(first))
assert [entry["user_id"] for entry in first_scoreboard] == [first_user_id]
assert first_challenge_solves == {{str(first_challenge_id): 1}}
assert first_scores["ranks"] == [first_user_id]
assert not DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).count()
db.session.rollback()

r.delete(*module_cache.module_identity_cache_keys(
    second.dojo_id,
    second.cache_identity,
))
assert handle_module_cache_refresh({{
    "dojo_id": second.dojo_id,
    "module_index": second.module_index,
}})
db.session.expire_all()
second = DojoModules.from_id(dojo_ref, "second").one()
second_scoreboard = get_cached_stat(
    module_cache.module_scoreboard_cache_key(second, 0)
)
second_challenge_solves = get_cached_stat(
    module_cache.module_challenge_solves_cache_key(second)
)
assert [entry["user_id"] for entry in second_scoreboard] == [second_user_id]
assert second_challenge_solves == {{str(second_challenge_id): 1}}
db.session.rollback()
print("OK")
""")
    assert "OK" in result.stdout


def test_legacy_module_identity_backfill(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    negative_dojo_id = -random.randint(1_000_000_000, 2_000_000_000)
    spec = {
        "id": f"legacy-cache-identity-{suffix}",
        "name": "Legacy Cache Identity",
        "modules": [{
            "id": "legacy",
            "name": "Legacy",
            "challenges": [{
                "id": "one",
                "name": "One",
                "image": "pwncollege/challenge-simple",
            }],
        }],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    dojo_flask_run(f"""
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoModules

module = DojoModules.from_id({dojo!r}, "legacy").one()
data = dict(module.data or {{}})
data.pop("cache_identity")
data.pop("cache_launched_at")
module.data = data
db.session.commit()
""")
    first = get_module_cache_states(dojo)[0]
    second = get_module_cache_states(dojo)[0]
    assert first["stored_identity"] is None
    assert first["stored_launched_at"] is None
    assert first["launched_at"] == "1970-01-01T00:00:00"
    assert first["identity"] == second["identity"]

    result = dojo_flask_run(f"""
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoCacheMigrations, DojoCacheRefreshes, DojoModuleCacheInvalidations, DojoModules
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
from CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh import handle_module_cache_refresh

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
try:
    negative_dojo = dojo_from_spec({{
        "id": {f'negative-live-{suffix}'!r},
        "name": "Negative Live",
        "modules": [{{
            "id": "negative",
            "name": "Negative",
            "challenges": [{{
                "id": "challenge",
                "name": "Challenge",
                "image": "pwncollege/challenge-simple",
            }}],
        }}],
    }})
    negative_dojo.dojo_id = {negative_dojo_id}
    db.session.add(negative_dojo)
    db.session.commit()
    negative_module = DojoModules.from_id(
        negative_dojo.reference_id,
        "negative",
    ).one()
    negative_legacy_keys = module_cache.legacy_module_cache_keys(
        negative_module.dojo_id,
        negative_module.module_index,
    )
    assert len(negative_legacy_keys) == 16
    DojoCacheMigrations.query.filter_by(
        name=module_cache.LEGACY_MODULE_CACHE_MIGRATION,
    ).delete()
    db.session.commit()
    module = DojoModules.from_id({dojo!r}, "legacy").one()
    identity = module.cache_identity
    legacy_keys = module_cache.legacy_module_cache_keys(
        module.dojo_id,
        module.module_index,
    )
    deleted_legacy_keys = module_cache.legacy_module_cache_keys(
        987654321,
        73,
    )
    all_legacy_keys = (
        legacy_keys | deleted_legacy_keys | negative_legacy_keys
    )
    r = get_redis_client()
    r.mset({{cache_key: "legacy-sentinel" for cache_key in all_legacy_keys}})

    assert module_cache.migrate_legacy_module_caches()
    assert DojoCacheMigrations.query.get(
        module_cache.LEGACY_MODULE_CACHE_MIGRATION
    ) is not None
    pending_negative_keys = {{
        cache_key
        for cache_key, _ in module_cache.pending_module_cache_invalidations(
            cache_keys=negative_legacy_keys
        )
    }}
    assert pending_negative_keys == negative_legacy_keys
    assert DojoModuleCacheInvalidations.query.filter(
        DojoModuleCacheInvalidations.cache_key.in_(negative_legacy_keys)
    ).count() == len(negative_legacy_keys)
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "legacy").one()
    assert module.cache_identity == identity
    assert (module.data or {{}}).get("cache_identity") == identity
    assert (module.data or {{}}).get(
        "cache_launched_at"
    ) == "1970-01-01T00:00:00"
    refresh = DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=identity,
    ).one()
    generation = refresh.generation
    db.session.rollback()

    assert module_cache.drain_module_cache_invalidations(all_legacy_keys)
    assert not r.exists(*all_legacy_keys)
    assert handle_module_cache_refresh({{
        "dojo_id": module.dojo_id,
        "module_id": module.id,
        "cache_identity": identity,
        "generation": generation,
    }})
    db.session.expire_all()
    module = DojoModules.from_id({dojo!r}, "legacy").one()
    identity_keys = module_cache.module_identity_cache_keys(
        module.dojo_id,
        identity,
    )
    assert r.exists(*identity_keys) == len(identity_keys)
    assert not DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=identity,
    ).count()
    assert module_cache.migrate_legacy_module_caches()
    assert not DojoCacheRefreshes.query.filter_by(
        kind="module",
        dojo_id=module.dojo_id,
        module_id=module.id,
        cache_identity=identity,
    ).count()
    db.session.rollback()
    print("OK")
finally:
    maintenance_lock.__exit__(None, None, None)
""")
    assert "OK" in result.stdout

    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=spec,
    )
    assert response.status_code == 200
    backfilled = get_module_cache_states(dojo)[0]
    assert backfilled["identity"] == first["identity"]
    assert backfilled["stored_identity"] == first["identity"]
    assert backfilled["launched_at"] == first["launched_at"]
    assert backfilled["stored_launched_at"] == first["launched_at"]
    assert_module_cache_state_populated(backfilled)


@pytest.mark.timeout(60)
def test_module_cache_xact_lock_releases_on_holder_death():
    result = dojo_flask_run("""
import multiprocessing
import os
import threading
import time
from unittest.mock import patch

import psycopg2
from flask import current_app

from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModuleCacheInvalidations
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh

database_url = os.environ["DATABASE_URL"].replace(
    "postgresql+psycopg2://",
    "postgresql://",
)
assert "@pgbouncer:" in database_url
app = current_app._get_current_object()
db.session.remove()

def hold_lock(pipe):
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        maintenance_lock = module_cache.module_cache_maintenance_lock(
            blocking=True
        )
        assert maintenance_lock.__enter__()
        pipe.send("locked")
        time.sleep(60)

def wait_for_lock(pipe):
    connection = psycopg2.connect(database_url)
    cursor = connection.cursor()
    pipe.send("waiting")
    cursor.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (module_cache.CACHE_MAINTENANCE_ADVISORY_LOCK,),
    )
    pipe.send("acquired")
    assert pipe.recv() == "release"
    connection.rollback()
    connection.close()

holder_parent, holder_child = multiprocessing.Pipe()
holder = multiprocessing.Process(target=hold_lock, args=(holder_child,))
holder.start()
assert holder_parent.poll(10)
assert holder_parent.recv() == "locked"

target = module_cache.ModuleCacheTarget(-1097, "dead", "d" * 32)
refresh_key = (
    "module",
    target.dojo_id,
    target.module_id,
    target.cache_identity,
)
cache_key = "stats:scoreboard:module:-1097:holder-death:0"
DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).delete(synchronize_session=False)
DojoModuleCacheInvalidations.query.filter_by(cache_key=cache_key).delete()
module_cache.queue_cache_refreshes(module_targets=(target,))
module_cache.queue_module_cache_invalidations({cache_key})
db.session.commit()
redis_client = get_redis_client()
redis_client.set(cache_key, "stale")

waiter_parent, waiter_child = multiprocessing.Pipe()
waiter = multiprocessing.Process(target=wait_for_lock, args=(waiter_child,))
waiter.start()
assert waiter_parent.poll(10)
assert waiter_parent.recv() == "waiting"
assert not waiter_parent.poll(0.2)

holder.terminate()
holder.join(10)
assert not holder.is_alive()
assert waiter_parent.poll(10)
assert waiter_parent.recv() == "acquired"

finisher_started = threading.Event()
finisher_finished = threading.Event()
published = []
errors = []

def finish_outboxes():
    with app.app_context():
        try:
            finisher_started.set()
            with module_cache.module_cache_maintenance_lock(blocking=True) as acquired:
                assert acquired
                with patch.object(
                    module_cache,
                    "publish_stat_event",
                    side_effect=lambda event_type, payload: published.append(
                        (event_type, payload)
                    ) or "published",
                ):
                    assert module_cache.maintain_module_cache_outboxes(
                        refresh_keys={refresh_key}
                    )
                assert len(published) == 1
                assert cache_refresh.handle_module_cache_refresh(
                    published[0][1]
                )
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()
            finisher_finished.set()

finisher = threading.Thread(target=finish_outboxes)
finisher.start()
assert finisher_started.wait(10)
time.sleep(0.2)
assert not finisher_finished.is_set()
waiter_parent.send("release")
waiter.join(10)
finisher.join(10)
assert not waiter.is_alive()
assert not finisher.is_alive()
assert not errors
assert finisher_finished.is_set()
assert not redis_client.exists(cache_key)
assert not DojoModuleCacheInvalidations.query.filter_by(
    cache_key=cache_key
).count()
assert not DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).count()
db.session.rollback()
print("OK")
""")
    assert "OK" in result.stdout


def test_module_cache_outbox_transactions_and_recovery():
    result = dojo_flask_run("""
import redis
from unittest.mock import patch

from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoModuleCacheInvalidations
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache

rollback_key = "stats:scoreboard:module:1097:rollback:0"
outer_rollback_key = "stats:scoreboard:module:1097:outer-rollback:0"
committed_key = "stats:scoreboard:module:1097:committed:0"
outage_key = "stats:scoreboard:module:1097:outage:0"
test_keys = {rollback_key, outer_rollback_key, committed_key, outage_key}
r = get_redis_client()
DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(test_keys)
).delete(synchronize_session=False)
db.session.commit()
maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()

outer = db.session.begin()
nested = db.session.begin_nested()
module_cache.queue_module_cache_invalidations({rollback_key})
nested.rollback()
outer.commit()
assert not DojoModuleCacheInvalidations.query.filter_by(cache_key=rollback_key).count()
db.session.rollback()

outer = db.session.begin()
nested = db.session.begin_nested()
module_cache.queue_module_cache_invalidations({outer_rollback_key})
nested.commit()
assert DojoModuleCacheInvalidations.query.filter_by(cache_key=outer_rollback_key).count() == 1
outer.rollback()
assert not DojoModuleCacheInvalidations.query.filter_by(cache_key=outer_rollback_key).count()
db.session.rollback()

outer = db.session.begin()
nested = db.session.begin_nested()
module_cache.queue_module_cache_invalidations({committed_key})
nested.commit()
outer.commit()
assert DojoModuleCacheInvalidations.query.filter_by(cache_key=committed_key).count() == 1
db.session.rollback()

module_cache.queue_module_cache_invalidations({outage_key})
db.session.commit()
r.mset({committed_key: "stale", outage_key: "stale"})

with patch.object(
    module_cache,
    "get_redis_client",
    side_effect=redis.ConnectionError("unavailable"),
) as get_client:
    assert not module_cache.drain_module_cache_invalidations()
    assert get_client.call_count == 3
assert r.get(outage_key) == "stale"
pending_keys = {key for key, _ in module_cache.pending_module_cache_invalidations()}
assert {committed_key, outage_key} <= pending_keys
assert module_cache.drain_module_cache_invalidations()
assert not r.exists(committed_key, outage_key)
pending_keys = {key for key, _ in module_cache.pending_module_cache_invalidations()}
assert not test_keys & pending_keys

rewrite_key = "stats:scoreboard:module:1097:rewrite:0"

class RewriteThenFail:
    def __init__(self):
        self.calls = 0

    def delete(self, *keys):
        self.calls += 1
        if self.calls == 1:
            return r.delete(*keys)
        r.set(rewrite_key, "rewritten")
        raise redis.ConnectionError("interrupted")

rewriting_client = RewriteThenFail()
r.set(rewrite_key, "stale")
with patch.object(
    module_cache,
    "get_redis_client",
    return_value=rewriting_client,
), patch.object(module_cache.logger, "warning") as warning:
    assert not module_cache.invalidate_module_cache_keys({rewrite_key})
assert rewriting_client.calls == 3
warning.assert_called_once()
assert r.get(rewrite_key) == "rewritten"
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


def test_cache_refresh_outbox_publish_and_recompute_retry(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-refresh-retry-{suffix}",
        "name": "Cache Refresh Retry",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    result = dojo_flask_run(f"""
from unittest.mock import patch

from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModules
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh

module = DojoModules.from_id({dojo!r}, "module").one()
target = module_cache.module_cache_target(module)
DojoCacheRefreshes.query.filter_by(dojo_id=target.dojo_id).delete(
    synchronize_session=False
)
db.session.commit()
maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
refresh_keys = {{
    ("dojo", target.dojo_id, "", ""),
    (
        "module",
        target.dojo_id,
        target.module_id,
        target.cache_identity,
    ),
}}

outer = db.session.begin()
nested = db.session.begin_nested()
module_cache.queue_cache_refreshes(
    module_targets=(target,),
    dojo_ids=(target.dojo_id,),
)
nested.rollback()
outer.commit()
assert not DojoCacheRefreshes.query.filter_by(dojo_id=target.dojo_id).count()
db.session.rollback()

module_cache.queue_cache_refreshes(
    module_targets=(target,),
    dojo_ids=(target.dojo_id,),
)
db.session.commit()
assert DojoCacheRefreshes.query.filter_by(dojo_id=target.dojo_id).count() == 2
db.session.rollback()

def partial_publish(event_type, payload):
    if event_type == "dojo_cache_refresh":
        return None
    return f"published-{{payload['generation']}}"

with patch.object(
    module_cache,
    "publish_stat_event",
    side_effect=partial_publish,
):
    assert not module_cache.publish_pending_cache_refreshes(
        retry_seconds=3600,
        refresh_keys=refresh_keys,
    )
db.session.expire_all()
dojo_refresh = DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=target.dojo_id,
).one()
module_refresh = DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).one()
assert dojo_refresh.published_at is None
assert module_refresh.published_at is not None
assert DojoCacheRefreshes.query.filter_by(dojo_id=target.dojo_id).count() == 2
stale_module_generation = module_refresh.generation
db.session.rollback()

module_cache.queue_cache_refreshes(module_targets=(target,))
db.session.commit()
replacement_refresh = DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).one()
assert replacement_refresh.generation > stale_module_generation
replacement_generation = replacement_refresh.generation
r = get_redis_client()
r.delete(*module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
))
assert cache_refresh.handle_module_cache_refresh({{
    "dojo_id": target.dojo_id,
    "module_id": target.module_id,
    "cache_identity": target.cache_identity,
    "generation": stale_module_generation,
}})
assert not r.exists(*module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
))
assert DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
    generation=replacement_generation,
).count() == 1
db.session.rollback()

with patch.object(
    module_cache,
    "publish_stat_event",
    return_value="retry-published",
):
    assert module_cache.publish_pending_cache_refreshes(
        retry_seconds=0,
        refresh_keys=refresh_keys,
    )
db.session.expire_all()
dojo_refresh = DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=target.dojo_id,
).one()
module_refresh = DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).one()
assert dojo_refresh.published_at is not None
assert module_refresh.published_at is not None
module_generation = module_refresh.generation
dojo_generation = dojo_refresh.generation
db.session.rollback()

r.delete(*module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
))
real_set_cached_stat = cache_refresh.set_cached_stat

def fail_module_scores(cache_key, data, **kwargs):
    if cache_key == module_cache.module_scores_cache_key(target):
        return False
    return real_set_cached_stat(cache_key, data, **kwargs)

module_payload = {{
    "dojo_id": target.dojo_id,
    "module_id": target.module_id,
    "cache_identity": target.cache_identity,
    "generation": module_generation,
}}
with patch.object(
    cache_refresh,
    "set_cached_stat",
    side_effect=fail_module_scores,
):
    assert not cache_refresh.handle_module_cache_refresh(module_payload)
assert DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
    generation=module_generation,
).count() == 1
db.session.rollback()

assert cache_refresh.handle_module_cache_refresh(module_payload)
assert not DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).count()
assert r.exists(*module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
)) == len(module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
))
db.session.rollback()

assert cache_refresh.handle_dojo_cache_refresh({{
    "dojo_id": target.dojo_id,
    "generation": dojo_generation,
}})
assert not DojoCacheRefreshes.query.filter_by(dojo_id=target.dojo_id).count()
db.session.rollback()
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


def test_versioned_cache_writes_use_monotonic_snapshot_versions():
    result = dojo_flask_run("""
import os
from unittest.mock import patch

import CTFd.plugins.dojo_plugin.utils.background_stats as background_stats

cache_key = f"stats:test:version-ordering:{os.urandom(8).hex()}"
redis_client = background_stats.get_redis_client()
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
assert background_stats.set_cached_stat(
    cache_key,
    {"value": "version-two"},
    updated_at=200,
    version=2,
)
assert background_stats.set_cached_stat(
    cache_key,
    {"value": "older-version-newer-event"},
    updated_at=300,
    version=1,
)
assert background_stats.get_cached_stat(cache_key) == {
    "value": "version-two"
}
assert background_stats.get_cache_updated_at(cache_key) == 200
assert background_stats.get_cache_version(cache_key) == 2

assert background_stats.set_cached_stat(
    cache_key,
    {"value": "version-three"},
    updated_at=100,
    version=3,
)
assert background_stats.get_cached_stat(cache_key) == {
    "value": "version-three"
}
assert background_stats.get_cache_updated_at(cache_key) == 100
assert background_stats.get_cache_version(cache_key) == 3

calculations = []
with patch.object(
    background_stats,
    "get_stats_revision",
    side_effect=(4, 5, 5, 5),
), patch.object(
    background_stats,
    "get_cache_watermark",
    side_effect=(100, 200),
):
    data, version, calculated_at = background_stats.calculate_authoritative_stat(
        lambda: calculations.append(len(calculations) + 1) or calculations[-1]
    )
assert calculations == [1, 2]
assert data == 2
assert version == 5
assert calculated_at == 200
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
print("OK")
""")
    assert "OK" in result.stdout


def test_cold_start_replaces_equal_revision_expired_window():
    result = dojo_flask_run("""
import os
from unittest.mock import patch

import CTFd.plugins.dojo_plugin.utils.background_stats as background_stats

cache_key = f"stats:test:expired-window:{os.urandom(8).hex()}"
redis_client = background_stats.get_redis_client()
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
assert background_stats.set_cached_stat(
    cache_key,
    [{"user_id": 1}],
    updated_at=100,
    version=7,
)
with patch.object(
    background_stats,
    "get_stats_revision",
    side_effect=(7, 7),
), patch.object(
    background_stats,
    "get_cache_watermark",
    return_value=200,
):
    data, version, calculated_at = (
        background_stats.calculate_authoritative_stat(lambda: [])
    )
assert background_stats.set_cached_stat(
    cache_key,
    data,
    updated_at=calculated_at,
    version=version,
)
assert background_stats.get_cached_stat(cache_key) == []
assert background_stats.get_cache_updated_at(cache_key) == 200
assert background_stats.get_cache_version(cache_key) == 7
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
print("OK")
""")
    assert "OK" in result.stdout


def test_solve_event_wins_race_with_authoritative_calculation():
    result = dojo_flask_run("""
import os
from unittest.mock import patch

import CTFd.plugins.dojo_plugin.utils.background_stats as background_stats

cache_key = f"stats:test:calculation-race:{os.urandom(8).hex()}"
redis_client = background_stats.get_redis_client()
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)

def calculate_while_solve_event_writes():
    assert background_stats.set_cached_stat(
        cache_key,
        {"source": "solve-event"},
        updated_at=301,
        version=9,
    )
    return {"source": "stale-calculation"}

with patch.object(
    background_stats,
    "get_stats_revision",
    side_effect=(8, 9),
), patch.object(
    background_stats,
    "get_cache_watermark",
    return_value=300,
):
    data, version, calculated_at = (
        background_stats.calculate_authoritative_stat(
            calculate_while_solve_event_writes,
            attempts=1,
        )
    )
assert background_stats.set_cached_stat(
    cache_key,
    data,
    updated_at=calculated_at,
    version=version,
)
assert background_stats.get_cached_stat(cache_key) == {
    "source": "solve-event"
}
assert background_stats.get_cache_updated_at(cache_key) == 301
assert background_stats.get_cache_version(cache_key) == 9
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
print("OK")
""")
    assert "OK" in result.stdout


def test_activity_cold_start_clears_users_aged_out_of_window():
    result = dojo_flask_run("""
from unittest.mock import MagicMock, patch

import CTFd.plugins.dojo_plugin.utils.background_stats as background_stats
import CTFd.plugins.dojo_plugin.worker.handlers.activity as activity_handler

user_id = 987654320
cache_key = f"stats:activity:{user_id}"
redis_client = background_stats.get_redis_client()
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
assert background_stats.set_cached_stat(
    cache_key,
    {
        "solve_timestamps": ["2020-01-01T00:00:00Z"],
        "total_solves": 1,
    },
    updated_at=100,
    version=11,
)
scan_client = MagicMock()
scan_client.scan_iter.return_value = (cache_key,)
with patch.object(
    activity_handler,
    "calculate_authoritative_stat",
    return_value=({}, 11, 200),
), patch.object(
    activity_handler,
    "get_redis_client",
    return_value=scan_client,
):
    activity_handler.initialize_all_activity()
assert background_stats.get_cached_stat(cache_key) == {
    "solve_timestamps": [],
    "total_solves": 0,
}
assert background_stats.get_cache_updated_at(cache_key) == 200
assert background_stats.get_cache_version(cache_key) == 11
redis_client.delete(
    cache_key,
    f"{cache_key}:updated",
    f"{cache_key}:version",
)
print("OK")
""")
    assert "OK" in result.stdout


def test_solve_events_include_transactional_snapshot_versions(example_dojo):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    result = dojo_flask_run(f"""
from unittest.mock import patch

from flask import g
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoModules, DojoStatsRevisions
import CTFd.plugins.dojo_plugin.utils.listeners as listeners

module = DojoModules.from_id({example_dojo!r}, "hello").one()
user = Users(
    name={f'versioned-event-{suffix}'!r},
    email={f'versioned-event-{suffix}@example.com'!r},
    password="password",
)
db.session.add(user)
db.session.flush()
revision_before = (
    db.session.query(DojoStatsRevisions.version)
    .filter_by(id=1)
    .scalar()
    or 0
)
solve = Solves(
    user_id=user.id,
    challenge_id=module.challenges[0].challenge_id,
    ip="127.0.0.1",
    provided="versioned-event",
)
with patch.object(
    listeners,
    "publish_challenge_solve_event",
) as publish:
    db.session.add(solve)
    db.session.commit()
    revision_after = DojoStatsRevisions.query.filter_by(id=1).one().version
    assert revision_after == revision_before + 1
    assert len(g._pending_stat_events) == 1
    g._pending_stat_events.pop()()
    publish.assert_called_once_with(
        user.id,
        solve.challenge_id,
        solve.date,
        solve_id=solve.id,
        version=revision_after,
    )
print("OK")
""")
    assert "OK" in result.stdout


def test_dojo_refresh_serializes_paused_authoritative_writer(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"dojo-refresh-race-{suffix}",
        "name": "Dojo Refresh Race",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    result = dojo_flask_run(f"""
import datetime
import json
import threading
from unittest.mock import patch

from flask import current_app
from CTFd.models import Solves, Users, db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModules, DojoStatsRevisions, Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cache_version, get_cached_stat, get_message_timestamp, get_redis_client, set_cached_stat
from CTFd.plugins.dojo_plugin.utils.crews import aggregate_crews
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh
import CTFd.plugins.dojo_plugin.worker.handlers.dojo_stats as dojo_stats_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scoreboard as scoreboard_handler
import CTFd.plugins.dojo_plugin.worker.handlers.scores as scores_handler
import CTFd.plugins.dojo_plugin.worker.handlers.solve as solve_handler

dojo_model = Dojos.from_id({dojo!r}).one()
module = DojoModules.from_id({dojo!r}, "module").one()
dojo_id = dojo_model.dojo_id
dojo_reference_id = dojo_model.reference_id
challenge_id = module.challenges[0].challenge_id
user = Users(
    name="refresh-race-{suffix} [Crew]",
    email="refresh-race-{suffix}@example.com",
    password="password",
)
db.session.add(user)
db.session.flush()
user_id = user.id
db.session.add(Solves(
    user_id=user_id,
    challenge_id=challenge_id,
    ip="127.0.0.1",
    provided="race",
))
maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
module_cache.queue_cache_refreshes(dojo_ids=(dojo_id,))
db.session.flush()
refresh = DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo_id,
    module_id="",
    cache_identity="",
).one()
refresh.published_at = datetime.datetime.utcnow() + datetime.timedelta(days=1)
refresh_generation = refresh.generation
db.session.commit()
first_revision = DojoStatsRevisions.query.filter_by(id=1).one().version

retired_user_id = 987654321
retired_scoreboard = [{{
    "rank": 1,
    "solves": 99,
    "user_id": retired_user_id,
    "name": "retired",
    "email": "retired@example.com",
}}]
for duration in scoreboard_handler.COMMON_DURATIONS:
    scoreboard_handler.set_scoreboard_cache(
        f"stats:scoreboard:dojo:{{dojo_model.dojo_id}}:{{duration}}",
        retired_scoreboard,
        {{}},
    )
set_cached_stat(f"stats:dojo:{{dojo_reference_id}}", {{
    "users": 99,
    "challenges": 1,
    "visible_challenges": 1,
    "solves": 99,
    "recent_solves": [],
    "trends": {{
        "solves": 0,
        "users": 0,
        "active": 0,
        "challenges": 0,
    }},
    "chart_data": {{
        "labels": ["Today", "1w ago", "1mo ago", "2mo ago"],
        "solves": [99, 0, 0, 0],
        "users": [99, 0, 0, 0],
    }},
}})
set_cached_stat(scores_handler.dojo_scores_cache_key(dojo_id), {{
    "ranks": [retired_user_id],
    "solves": {{retired_user_id: 99}},
}})
r = get_redis_client()
event_timestamp = get_message_timestamp(
    r.xadd("stat:test-timestamps", {{"event": "first"}})
)
db.session.rollback()
maintenance_lock.__exit__(None, None, None)

app = current_app._get_current_object()
solve_writer_paused = threading.Event()
resume_solve_writer = threading.Event()
solve_writer_finished = threading.Event()
refresh_lock_attempted = threading.Event()
refresh_finished = threading.Event()
errors = []
real_write_dojo_caches = cache_refresh._write_dojo_caches
real_refresh_lock = cache_refresh.lock_dojo_cache_target

def pause_before_solve_dojo_write(dojo_to_write, timestamp=None):
    if threading.current_thread().name == "solve-writer":
        solve_writer_paused.set()
        assert resume_solve_writer.wait(10)
    return real_write_dojo_caches(dojo_to_write, timestamp)

def observe_refresh_lock(dojo_id_to_lock):
    refresh_lock_attempted.set()
    return real_refresh_lock(dojo_id_to_lock)

def run_solve_writer():
    with app.app_context():
        try:
            solve_handler.handle_challenge_solve({{
                "user_id": user_id,
                "challenge_id": challenge_id,
            }}, event_timestamp)
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()
            solve_writer_finished.set()

def run_refresh():
    with app.app_context():
        try:
            assert cache_refresh.handle_dojo_cache_refresh({{
                "dojo_id": dojo_id,
                "generation": refresh_generation,
            }})
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()
            refresh_finished.set()

with patch.object(
    cache_refresh,
    "_write_dojo_caches",
    side_effect=pause_before_solve_dojo_write,
), patch.object(
    cache_refresh,
    "lock_dojo_cache_target",
    side_effect=observe_refresh_lock,
):
    solve_writer_thread = threading.Thread(
        target=run_solve_writer,
        name="solve-writer",
    )
    solve_writer_thread.start()
    assert solve_writer_paused.wait(10)
    later_user = Users(
        name="refresh-race-later-{suffix} [Crew]",
        email="refresh-race-later-{suffix}@example.com",
        password="password",
    )
    db.session.add(later_user)
    db.session.flush()
    later_user_id = later_user.id
    db.session.add(Solves(
        user_id=later_user_id,
        challenge_id=challenge_id,
        ip="127.0.0.1",
        provided="later-race",
    ))
    db.session.commit()
    later_revision = DojoStatsRevisions.query.filter_by(id=1).one().version
    assert later_revision > first_revision
    later_event_timestamp = get_message_timestamp(
        r.xadd("stat:test-timestamps", {{"event": "later"}})
    )
    assert later_event_timestamp > event_timestamp
    refresh_thread = threading.Thread(target=run_refresh)
    refresh_thread.start()
    assert refresh_lock_attempted.wait(10)
    assert not refresh_finished.wait(0.2)
    assert DojoCacheRefreshes.query.filter_by(
        kind="dojo",
        dojo_id=dojo_id,
        generation=refresh_generation,
    ).count() == 1
    db.session.rollback()
    resume_solve_writer.set()
    solve_writer_thread.join(10)
    refresh_thread.join(10)
    assert not solve_writer_thread.is_alive()
    assert not refresh_thread.is_alive()

assert solve_handler.handle_challenge_solve({{
    "user_id": later_user_id,
    "challenge_id": challenge_id,
}}, later_event_timestamp)

assert not errors
assert solve_writer_finished.is_set()
assert refresh_finished.is_set()
db.session.expire_all()
dojo_model = Dojos.from_id({dojo!r}).one()

def json_value(value):
    return json.loads(json.dumps(value))

for duration in scoreboard_handler.COMMON_DURATIONS:
    expected_scoreboard = scoreboard_handler.calculate_scoreboard(
        dojo_model,
        duration,
    )
    expected_member_challenges = scoreboard_handler.calculate_member_challenges(
        dojo_model,
        duration,
        expected_scoreboard,
    )
    expected_crews = aggregate_crews(
        expected_scoreboard,
        expected_member_challenges,
    )
    assert get_cached_stat(
        f"stats:scoreboard:dojo:{{dojo_model.dojo_id}}:{{duration}}"
    ) == json_value(expected_scoreboard)
    assert get_cached_stat(
        f"stats:crews:dojo:{{dojo_model.dojo_id}}:{{duration}}"
    ) == json_value(expected_crews)
expected_stats = dojo_stats_handler.calculate_dojo_stats(dojo_model)
expected_scores = scores_handler.calculate_dojo_scores(dojo_model.dojo_id)
assert get_cached_stat(
    f"stats:dojo:{{dojo_model.reference_id}}"
) == json_value(expected_stats)
assert get_cached_stat(
    scores_handler.dojo_scores_cache_key(dojo_model.dojo_id)
) == json_value(expected_scores)
assert retired_user_id not in {{
    entry["user_id"]
    for entry in get_cached_stat(
        f"stats:scoreboard:dojo:{{dojo_model.dojo_id}}:0"
    )
}}
module = DojoModules.from_id({dojo!r}, "module").one()
assert {{
    entry["user_id"]
    for entry in get_cached_stat(
        module_cache.module_scoreboard_cache_key(module, 0)
    )
}} == {{user_id, later_user_id}}
assert get_cached_stat(
    module_cache.module_challenge_solves_cache_key(module)
) == {{str(challenge_id): 2}}
assert set(get_cached_stat(
    module_cache.module_scores_cache_key(module)
)["ranks"]) == {{user_id, later_user_id}}
assert get_cache_version(
    module_cache.module_scoreboard_cache_key(module, 0)
) == later_revision
assert get_cache_version(
    module_cache.dojo_scoreboard_cache_key(dojo_model.dojo_id, 0)
) == later_revision
assert not DojoCacheRefreshes.query.filter_by(
    kind="dojo",
    dojo_id=dojo_model.dojo_id,
).count()
db.session.rollback()
print("OK")
""")
    assert "OK" in result.stdout


def test_module_cache_outbox_preserves_concurrent_generation():
    result = dojo_flask_run("""
from unittest.mock import patch

from sqlalchemy.dialects.postgresql import insert
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DOJO_MODULE_CACHE_INVALIDATION_GENERATION, DojoModuleCacheInvalidations
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache

cache_key = "stats:scoreboard:module:1097:concurrent:0"
DojoModuleCacheInvalidations.query.filter_by(cache_key=cache_key).delete()
db.session.commit()
maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
module_cache.queue_module_cache_invalidations({cache_key})
db.session.commit()
initial_generation = DojoModuleCacheInvalidations.query.filter_by(
    cache_key=cache_key
).one().generation
db.session.rollback()
r = get_redis_client()
r.set(cache_key, "stale")

def invalidate_with_concurrent_event(keys):
    r.delete(*keys)
    table = DojoModuleCacheInvalidations.__table__
    next_generation = DOJO_MODULE_CACHE_INVALIDATION_GENERATION.next_value()
    statement = insert(table).values(
        cache_key=cache_key,
        generation=next_generation,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.cache_key],
        set_={"generation": statement.excluded.generation},
    )
    with db.engine.begin() as connection:
        connection.execute(statement)
    r.set(cache_key, "rewritten")
    return True

with patch.object(
    module_cache,
    "invalidate_module_cache_keys",
    side_effect=invalidate_with_concurrent_event,
), patch.object(module_cache, "INVALIDATION_MAX_BATCHES", 1):
    assert not module_cache.drain_module_cache_invalidations()
remaining = DojoModuleCacheInvalidations.query.filter_by(cache_key=cache_key).one()
assert remaining.generation > initial_generation
assert r.get(cache_key) == "rewritten"
db.session.rollback()
assert module_cache.drain_module_cache_invalidations()
assert not r.exists(cache_key)
assert not DojoModuleCacheInvalidations.query.filter_by(cache_key=cache_key).count()
db.session.rollback()
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


@pytest.mark.timeout(60)
def test_invalidation_drain_serializes_with_module_refresh(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"cache-drain-barrier-{suffix}",
        "name": "Cache Drain Barrier",
        "type": "public",
        "modules": [cache_identity_module("module", "challenge")],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    result = dojo_flask_run(f"""
import datetime
import threading
import time
from unittest.mock import patch

from flask import current_app
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoCacheRefreshes, DojoModuleCacheInvalidations, DojoModules
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache
import CTFd.plugins.dojo_plugin.worker.handlers.cache_refresh as cache_refresh

module = DojoModules.from_id({dojo!r}, "module").one()
target = module_cache.module_cache_target(module)
cache_keys = module_cache.module_identity_cache_keys(
    target.dojo_id,
    target.cache_identity,
)
maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).delete(synchronize_session=False)
DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
).delete(synchronize_session=False)
module_cache.queue_cache_refreshes(module_targets=(target,))
db.session.flush()
refresh = DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).one()
refresh.published_at = datetime.datetime.utcnow() + datetime.timedelta(days=1)
generation = refresh.generation
db.session.commit()
redis_client = get_redis_client()
redis_client.mset({{cache_key: "stale" for cache_key in cache_keys}})

app = current_app._get_current_object()
reader_selected = threading.Event()
resume_reader = threading.Event()
reader_finished = threading.Event()
refresh_started = threading.Event()
refresh_finished = threading.Event()
errors = []
real_pending = module_cache.pending_module_cache_invalidations
reader_paused = False

def delayed_pending(*args, **kwargs):
    global reader_paused
    pending = real_pending(*args, **kwargs)
    if threading.current_thread().name == "delayed-cache-reader" and not reader_paused:
        reader_paused = True
        assert pending
        reader_selected.set()
        assert resume_reader.wait(10)
    return pending

def run_reader():
    with app.app_context():
        try:
            assert module_cache.drain_module_cache_invalidations(cache_keys)
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()
            reader_finished.set()

def run_refresh():
    with app.app_context():
        try:
            refresh_started.set()
            assert cache_refresh.handle_module_cache_refresh({{
                "dojo_id": target.dojo_id,
                "module_id": target.module_id,
                "cache_identity": target.cache_identity,
                "generation": generation,
            }})
        except Exception as error:
            errors.append(repr(error))
        finally:
            db.session.remove()
            refresh_finished.set()

with patch.object(
    module_cache,
    "pending_module_cache_invalidations",
    side_effect=delayed_pending,
):
    reader = threading.Thread(target=run_reader, name="delayed-cache-reader")
    reader.start()
    assert not reader_selected.wait(0.2)
    maintenance_lock.__exit__(None, None, None)
    assert reader_selected.wait(10)
    refresher = threading.Thread(target=run_refresh, name="cache-refresher")
    refresher.start()
    assert refresh_started.wait(10)
    time.sleep(0.2)
    assert not refresh_finished.is_set()
    resume_reader.set()
    reader.join(10)
    refresher.join(10)
    assert not reader.is_alive()
    assert not refresher.is_alive()

assert not errors
assert reader_finished.is_set()
assert refresh_finished.is_set()
assert redis_client.exists(*cache_keys) == len(cache_keys)
assert get_cached_stat(
    module_cache.module_scoreboard_cache_key(target, 0)
) == []
assert not DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(cache_keys)
).count()
assert not DojoCacheRefreshes.query.filter_by(
    kind="module",
    dojo_id=target.dojo_id,
    module_id=target.module_id,
    cache_identity=target.cache_identity,
).count()
db.session.rollback()
print("OK")
""")
    assert "OK" in result.stdout


def test_module_cache_outbox_batch_bound_and_progress():
    result = dojo_flask_run("""
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoModuleCacheInvalidations
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
assert module_cache.drain_module_cache_invalidations()
prefix = "stats:scoreboard:module:1097:batch:"
keys = {
    f"{prefix}{index:05d}"
    for index in range(
        module_cache.INVALIDATION_BATCH_SIZE * module_cache.INVALIDATION_MAX_BATCHES + 3
    )
}
same_key = f"{prefix}same"
module_cache.queue_module_cache_invalidations(keys)
module_cache.queue_module_cache_invalidations({same_key})
initial_generation = DojoModuleCacheInvalidations.query.filter_by(
    cache_key=same_key
).one().generation
for _ in range(19):
    module_cache.queue_module_cache_invalidations({same_key})
db.session.commit()
keys.add(same_key)
assert DojoModuleCacheInvalidations.query.filter_by(cache_key=same_key).count() == 1
final_generation = DojoModuleCacheInvalidations.query.filter_by(
    cache_key=same_key
).one().generation
assert final_generation > initial_generation
assert len(module_cache.pending_module_cache_invalidations()) == module_cache.INVALIDATION_BATCH_SIZE
db.session.rollback()
r = get_redis_client()
r.mset({key: "stale" for key in keys})
assert not module_cache.drain_module_cache_invalidations()
remaining = DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.like(f"{prefix}%")
).count()
assert remaining == 4
db.session.rollback()
assert module_cache.drain_module_cache_invalidations()
assert not DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.like(f"{prefix}%")
).count()
db.session.rollback()
assert not r.exists(*keys)
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


def test_module_cache_late_pending_key_fails_closed():
    result = dojo_flask_run("""
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoModuleCacheInvalidations
from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
import CTFd.plugins.dojo_plugin.utils.module_cache as module_cache

maintenance_lock = module_cache.module_cache_maintenance_lock(blocking=True)
assert maintenance_lock.__enter__()
assert module_cache.drain_module_cache_invalidations()
prefix = "stats:scoreboard:module:1097:late-read:"
backlog = {
    f"{prefix}{index:04d}"
    for index in range(module_cache.INVALIDATION_BATCH_SIZE + 3)
}
requested_key = f"{prefix}zzzz"
requested_updated_key = f"{requested_key}:updated"
module_cache.queue_module_cache_invalidations(
    backlog | {requested_key, requested_updated_key}
)
db.session.commit()
r = get_redis_client()
r.mset({key: "stale" for key in backlog})
r.mset({requested_key: '"stale"', requested_updated_key: "1"})

target = module_cache.ModuleCacheTarget(1097, "late-read", "late-read")
assert module_cache.get_module_cached_stat(target, requested_key) is None
assert not r.exists(requested_key, requested_updated_key)
assert not DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_([requested_key, requested_updated_key])
).count()
assert DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.in_(backlog)
).count() == len(backlog)
db.session.rollback()

assert module_cache.drain_module_cache_invalidations()
assert not r.exists(*backlog)
assert not DojoModuleCacheInvalidations.query.filter(
    DojoModuleCacheInvalidations.cache_key.like(f"{prefix}%")
).count()
db.session.rollback()
maintenance_lock.__exit__(None, None, None)
print("OK")
""")
    assert "OK" in result.stdout


def test_folder_awards(admin_session, event_dojo, random_user, example_dojo):
    grant_award = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"
    random_user_name, random_user_session = random_user
    uid = get_user_id(random_user_name)
    assert admin_session.post(grant_award, json={"user_id": uid, "emoji": "🥈", "description": "Test emoji 1"}).status_code == 200
    assert admin_session.post(grant_award, json={"user_id": uid, "emoji": "🥈", "description": "Test emoji 2"}).status_code == 200

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    result = workspace_run("/challenge/apple", user=random_user_name)
    flag = result.stdout.strip()
    solve_challenge(example_dojo, "hello", "apple", session=random_user_session, flag=flag)

    wait_for_background_worker()

    scoreboard = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{example_dojo}/hello/0/1").json()
    assert scoreboard.get("me",None), f"Unable to find entry for {random_user_name}."
    for emoji in scoreboard["me"]["badges"]:
        if emoji["emoji"] == "🥈" and emoji["count"] == 2:
            return
    assert False, f"Failed to find second place award with count 2. Emojis: {scoreboard["me"]["badges"]}"
