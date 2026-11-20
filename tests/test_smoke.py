import pytest

import terkini
from terkini.cli import main


def test_version_is_set():
    assert terkini.__version__


def test_cli_without_arguments_exits_cleanly():
    assert main([]) == 0


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "terkini" in capsys.readouterr().out
