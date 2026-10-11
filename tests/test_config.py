import os

import pytest

from edgar_ratios import config


def test_env_var_wins(monkeypatch):
    config.save_user_agent("Saved Person saved@example.com")
    monkeypatch.setenv("EDGAR_RATIOS_USER_AGENT", "Env Person env@example.com")
    assert config.user_agent(interactive=False) == "Env Person env@example.com"


def test_saved_value_is_used():
    config.save_user_agent("Saved Person saved@example.com")
    assert config.user_agent(interactive=False) == "Saved Person saved@example.com"


def test_first_run_asks_once_and_saves(capsys):
    answers = iter(["Jane Doe jane@example.com"])
    assert config.user_agent(ask=lambda prompt: next(answers), interactive=True) == "Jane Doe jane@example.com"
    assert "sec.gov" in capsys.readouterr().out
    assert config.user_agent(interactive=False) == "Jane Doe jane@example.com"


def test_first_run_rejects_an_answer_without_email():
    with pytest.raises(config.ConfigError):
        config.user_agent(ask=lambda prompt: "nobody", interactive=True)


def test_non_interactive_without_user_agent_explains():
    with pytest.raises(config.ConfigError, match="--set-user-agent"):
        config.user_agent(interactive=False)


@pytest.mark.parametrize("value,ok", [
    ("Jane Doe jane@example.com", True), ("Acme Research ops@acme.io", True),
    ("jane@example.com", False), ("Jane Doe", False), ("", False),
])
def test_valid_user_agent(value, ok):
    assert config.valid_user_agent(value) is ok


def test_corrupt_config_is_ignored():
    config.home().mkdir(parents=True)
    (config.home() / "config.json").write_text("{oops")
    with pytest.raises(config.ConfigError):
        config.user_agent(interactive=False)


def test_load_env_does_not_override_existing(monkeypatch):
    config.home().mkdir(parents=True)
    (config.home() / ".env").write_text("# key\nANTHROPIC_API_KEY='from-file'\nOTHER=1\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.delenv("OTHER", raising=False)
    config.load_env()
    assert os.environ["ANTHROPIC_API_KEY"] == "from-env" and os.environ["OTHER"] == "1"


def test_cache_lives_under_home():
    assert config.cache_dir() == config.home() / "cache"
