"""P37 tests (T691-T710): adapters. Weightless — env guards, static wiring,
stubbed transports; no platform SDK or network in sight."""
import subprocess
import sys
from pathlib import Path

ADAPTERS = Path("src/gatekeeper/adapters")


def _run_py(*args, env_extra=None):
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, *args], check=False, capture_output=True,
                          text=True, timeout=60, env=env)


def test_require_env_names_the_missing_variable(monkeypatch):  # T691
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import AdapterError, require_env
    monkeypatch.delenv("BOUNCER_TEST_TOKEN_XYZ", raising=False)
    try:
        require_env("BOUNCER_TEST_TOKEN_XYZ")
    except AdapterError as e:
        assert e.code == "E_ADAPTER"  # operator-fixable, not a crash
        assert "BOUNCER_TEST_TOKEN_XYZ" in str(e)  # the variable is named
        assert "KeyError" not in str(e)
    else:
        raise AssertionError("require_env must raise on a missing var")
    # set and non-empty -> returned as-is
    monkeypatch.setenv("BOUNCER_TEST_TOKEN_XYZ", "sekrit")
    assert require_env("BOUNCER_TEST_TOKEN_XYZ") == "sekrit"
    # exported-but-blank is also a misconfiguration, not a value
    monkeypatch.setenv("BOUNCER_TEST_TOKEN_XYZ", "")
    try:
        require_env("BOUNCER_TEST_TOKEN_XYZ")
    except AdapterError as e:
        assert e.code == "E_ADAPTER"
    else:
        raise AssertionError("blank env var must count as missing")


def test_adapters_use_require_env_not_raw_indexing():  # T691: wired for real
    discord = (ADAPTERS / "discord_bot.py").read_text()
    twitch = (ADAPTERS / "twitch_irc.py").read_text()
    assert 'require_env("DISCORD_TOKEN")' in discord
    assert "environ[" not in discord  # no raw KeyError path left
    for var in ("TWITCH_NICK", "TWITCH_CHAN", "TWITCH_TOKEN"):
        assert f'require_env("{var}")' in twitch, var
    assert 'environ["TWITCH_' not in twitch  # tokens read via the guard


def test_twitch_missing_env_fails_with_e_adapter_not_keyerror():  # T691 e2e
    r = _run_py("-m", "gatekeeper.adapters.twitch_irc")
    assert r.returncode != 0  # no env -> must fail, loudly
    assert "E_ADAPTER" in r.stderr and "TWITCH_NICK" in r.stderr
    assert "KeyError" not in r.stderr  # the whole point: no raw traceback
    # only the first missing var is named (fail-fast order)
    assert "TWITCH_TOKEN" not in r.stderr


def test_discord_module_still_importable_without_dep():  # T691: guard is lazy
    # the require_env import lives inside run(), so importing the module
    # (docs tooling, tests) never needs discord or env vars
    r = _run_py("-c", "import gatekeeper.adapters.discord_bot as m; "
                      "print(m.run.__name__)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "run"


def test_adapters_readme_mentions_shared_guard():  # T691: docs stay honest
    text = (ADAPTERS / "README.md").read_text()
    assert "require_env" in text and "E_ADAPTER" in text


def _tg_message(text, chat_id=1, message_id=7):
    return {"message": {"text": text, "chat": {"id": chat_id},
                        "message_id": message_id}}


def test_telegram_commands_answer_in_place():  # T692: / commands, no model
    sys.path.insert(0, "src")
    from gatekeeper import get_preset
    from gatekeeper.adapters.telegram_bot import handle_update
    rules = get_preset("gaming")
    for cmd, expect in (("/rules", "active:"), ("/stats", "decisions:"),
                        ("/help", "BOUNCER_TG_DELETE")):
        res = handle_update(_tg_message(cmd), rules)
        assert res["action"] == "command" and res["command"] == cmd.lstrip("/")
        assert expect in res["reply"]
    # unknown commands are ignored, not moderated as content
    res = handle_update(_tg_message("/definitely-not-a-command"), rules)
    assert res == {"action": "ignored", "reason": "unknown-command"}
    # with a token, replies go through the (injectable) api, not print
    calls = []
    res = handle_update(_tg_message("/rules"), rules, token="t",
                        api_fn=lambda *a, **k: calls.append((a, k)))
    assert calls and calls[0][0][1:] == ("sendMessage",)
    assert calls[0][1]["chat_id"] == 1


def test_telegram_flag_only_by_default(monkeypatch):  # T692: delete is opt-in
    sys.path.insert(0, "src")
    import gatekeeper
    from gatekeeper.adapters import telegram_bot as tg
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda text, rules: {"action": "delete",
                                             "rule": "sin-spam",
                                             "confidence": 0.99})
    rules = {"sin-spam": "t"}
    calls = []
    # default: the delete decision is printed, never executed
    res = tg.handle_update(_tg_message("buy followers now"), rules)
    assert res["action"] == "delete" and res["deleted"] is False
    assert calls == []  # no api call happened
    # opt-in with a token: exactly one deleteMessage call
    res = tg.handle_update(_tg_message("buy followers now"), rules,
                           token="t", can_delete=True,
                           api_fn=lambda *a, **k: calls.append((a, k)))
    assert res["deleted"] is True
    assert calls[0][0][1:] == ("deleteMessage",)
    assert calls[0][1] == {"chat_id": 1, "message_id": 7}
    # without a token even can_delete=True cannot fire (nothing to auth with)
    res = tg.handle_update(_tg_message("buy followers now"), rules,
                           can_delete=True)
    assert res["deleted"] is False


def test_telegram_ignores_non_text_updates():  # T692: stickers carry no text
    sys.path.insert(0, "src")
    from gatekeeper import get_preset
    from gatekeeper.adapters.telegram_bot import handle_update
    rules = get_preset("gaming")
    res = handle_update({"message": {"sticker": {}}}, rules)
    assert res == {"action": "ignored", "reason": "no-text"}
    res = handle_update({}, rules)
    assert res["action"] == "ignored"


def test_telegram_adapter_is_stdlib_only():  # T692: no pip extra to run it
    src = (ADAPTERS / "telegram_bot.py").read_text()
    for banned in ("import telegram", "import aiogram", "import aiohttp",
                   "import httpx", "import requests"):
        assert banned not in src
    # every top-level import is stdlib
    top = [l.strip() for l in src.splitlines()
           if l.startswith(("import ", "from ")) and "future" not in l]
    allowed = {"json", "os", "sys", "urllib.request"}
    for line in top:
        mod = line.split()[1]
        assert mod in allowed, line


def test_telegram_missing_token_fails_e_adapter():  # T692: T691 guard applies
    r = _run_py("-m", "gatekeeper.adapters.telegram_bot")
    assert r.returncode != 0
    assert "E_ADAPTER" in r.stderr and "TELEGRAM_TOKEN" in r.stderr
    assert "KeyError" not in r.stderr
