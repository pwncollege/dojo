import pytest

from utils import DOJO_URL, start_challenge
from test_challenges import solve_challenge


@pytest.mark.dependency(depends=["test_dojo_completion"])
def test_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in belt_dojos.items():
        start_challenge(dojo, "test", "test", session=session)
        solve_challenge(dojo, "test", "test", session=session, user=user_name)
        scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert color in us["belt"]


@pytest.mark.dependency(depends=["test_belts"])
def test_cumulative_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in reversed(belt_dojos.items()):
        start_challenge(dojo, "test", "test", session=session)
        solve_challenge(dojo, "test", "test", session=session, user=user_name)
        scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        if color == "orange":
            # orange is last, so we should get all belts including blue
            assert "blue" in us["belt"]
        else:
            # until orange, we should be stuck in white
            assert "white" in us["belt"]