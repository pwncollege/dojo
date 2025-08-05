import pytest

from utils import DOJO_URL, start_challenge, solve_challenge


def test_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in belt_dojos.items():
        start_challenge(dojo, "test", "test", session=session)
        solve_challenge(dojo, "test", "test", session=session, user=user_name)
        for page in range(1, 1000):
            scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/{page}").json()
            assert scoreboard["standings"], f"exhausted {page-1} pages of scoreboard for dojo {dojo} without finding user {user_name}"
            try:
                us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
                assert color in us["belt"]
                break
            except StopIteration:
                continue


def test_cumulative_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in reversed(belt_dojos.items()):
        start_challenge(dojo, "test", "test", session=session)
        solve_challenge(dojo, "test", "test", session=session, user=user_name)
        for page in range(1, 1000):
            scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/{page}").json()
            assert scoreboard["standings"], f"exhausted {page-1} pages of scoreboard for dojo {dojo} without finding user {user_name}"

            try:
                us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
                if color == "orange":
                    # orange is last, so we should get all belts including blue
                    assert "blue" in us["belt"]
                else:
                    # until orange, we should be stuck in white
                    assert "white" in us["belt"]
                break
            except StopIteration:
                continue
