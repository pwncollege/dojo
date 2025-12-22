import pytest

from utils import DOJO_HOST, start_challenge, solve_challenge


def test_belts(belt_dojos, random_user_name, random_user_session):
    for color,dojo in belt_dojos.items():
        start_challenge(dojo, "test", "test", session=random_user_session)
        solve_challenge(dojo, "test", "test", session=random_user_session, user=random_user_name)
        for page in range(1, 1000):
            scoreboard = random_user_session.get(f"http://{DOJO_HOST}/pwncollege_api/v1/scoreboard/{dojo}/_/0/{page}").json()
            assert scoreboard["standings"], f"exhausted {page-1} pages of scoreboard for dojo {dojo} without finding user {random_user_name}"
            try:
                us = next(u for u in scoreboard["standings"] if u["name"] == random_user_name)
                assert color in us["belt"]
                break
            except StopIteration:
                continue


def test_cumulative_belts(belt_dojos, random_user_name, random_user_session):
    for color,dojo in reversed(belt_dojos.items()):
        start_challenge(dojo, "test", "test", session=random_user_session)
        solve_challenge(dojo, "test", "test", session=random_user_session, user=random_user_name)
        for page in range(1, 1000):
            scoreboard = random_user_session.get(f"http://{DOJO_HOST}/pwncollege_api/v1/scoreboard/{dojo}/_/0/{page}").json()
            assert scoreboard["standings"], f"exhausted {page-1} pages of scoreboard for dojo {dojo} without finding user {random_user_name}"

            try:
                us = next(u for u in scoreboard["standings"] if u["name"] == random_user_name)
                if color == "orange":
                    # orange is last, so we should get all belts including blue
                    assert "blue" in us["belt"]
                else:
                    # until orange, we should be stuck in white
                    assert "white" in us["belt"]
                break
            except StopIteration:
                continue
