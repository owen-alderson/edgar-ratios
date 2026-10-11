"""Where edgar-ratios keeps its settings, and the User-Agent the SEC asks every tool to send."""

import json
import os
import re
import sys
from pathlib import Path

USER_AGENT_ENV = "EDGAR_RATIOS_USER_AGENT"
SEC_POLICY = "https://www.sec.gov/os/accessing-edgar-data"


class ConfigError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("EDGAR_RATIOS_HOME") or Path.home() / ".edgar-ratios")


def cache_dir() -> Path:
    return home() / "cache"


def _config_path() -> Path:
    return home() / "config.json"


def _read() -> dict:
    try:
        return json.loads(_config_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def valid_user_agent(value: str) -> bool:
    """The SEC wants a name and a contact email, e.g. 'Jane Doe jane@example.com'."""
    return bool(re.search(r"\S+@\S+\.\S+", value)) and len(value.split()) >= 2


def save_user_agent(value: str) -> None:
    value = value.strip()
    if not valid_user_agent(value):
        raise ConfigError(f"Use a name and an email, e.g. 'Jane Doe jane@example.com' (got {value!r}).")
    data = _read()
    data["user_agent"] = value
    _config_path().parent.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(data, indent=2) + "\n")


def user_agent(ask=input, interactive: bool | None = None) -> str:
    """The env var wins, then the saved config; otherwise ask once on a terminal and save the answer."""
    value = os.environ.get(USER_AGENT_ENV) or _read().get("user_agent")
    if value:
        return value
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise ConfigError(
            "The SEC asks every tool to identify itself with a name and email "
            f"({SEC_POLICY}). Run: edgar-ratios --set-user-agent \"Your Name you@example.com\" "
            f"(or set {USER_AGENT_ENV})."
        )
    print("The SEC asks every tool that reads EDGAR to send a name and contact email.")
    print(f"It is only sent to sec.gov ({SEC_POLICY}).")
    value = ask("Your name and email (e.g. Jane Doe jane@example.com): ")
    save_user_agent(value)
    return value.strip()


def load_env() -> None:
    """Load ANTHROPIC_API_KEY (and anything else) from ~/.edgar-ratios/.env without overriding the environment."""
    path = home() / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
