from pathlib import Path


def action_block(source, action):
    return source.split(f'    "{action}")', 1)[1].split("        ;;", 1)[0]


def test_cache_processes_stop_before_hot_update():
    source = (Path(__file__).parents[1] / "dojo" / "dojo").read_text()
    stop = "dojo compose stop ctfd stats-worker"

    up = action_block(source, "up")
    assert up.index(stop) < up.index("dojo sync")

    update = action_block(source, "update")
    assert update.index(stop) < update.index("git pull")
