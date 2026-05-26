from telearchive.gui import should_launch_gui


def test_should_launch_gui() -> None:
    assert should_launch_gui([]) is True
    assert should_launch_gui(["--gui"]) is True
    assert should_launch_gui(["gui"]) is True
    assert should_launch_gui(["ingest", "./x"]) is False
    assert should_launch_gui(["--help"]) is False
