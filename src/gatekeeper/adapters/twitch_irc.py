"""Twitch IRC stub, stdlib only (T076-T077). Read-only: flags, never bans.
Usage: TWITCH_TOKEN=... TWITCH_NICK=... TWITCH_CHAN=#x python -m gatekeeper.adapters.twitch_irc
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import os
import socket
import sys


def redact(s: str) -> str:  # T077
    tok = os.environ.get("TWITCH_TOKEN", "")
    return s.replace(tok, "***") if tok else s


def _parse_privmsg(line: str) -> tuple | None:
    """T299: split an IRC line into (user, text); None for non-chat lines."""
    if "PRIVMSG" not in line:
        return None
    try:
        user = line[1:].split("!", 1)[0]
        text = line.split("PRIVMSG", 1)[1].split(":", 1)[1]
    except IndexError:
        return None
    return user, text


def _watch_once(sock, rules) -> None:
    from gatekeeper import moderate
    buf = ""
    while True:
        buf += sock.recv(4096).decode("utf-8", "replace")
        while "\r\n" in buf:
            line, buf = buf.split("\r\n", 1)
            if line.startswith("PING"):
                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                continue
            parsed = _parse_privmsg(line)
            if parsed is None:
                continue
            user, text = parsed
            try:
                res = moderate(text, rules)
            except Exception as e:  # noqa: BLE001
                print("mod error", redact(str(e)), file=sys.stderr)
                continue
            if res["action"] in ("delete", "flag", "escalate"):
                print(f"[{res['action']}] <{user}> {text[:120]} ({res['rule']}@{res['confidence']:.2f})",
                      flush=True)


def run(retries: int = 3):
    from gatekeeper import get_preset
    rules = get_preset("stream")
    host, port = "irc.chat.twitch.tv", 6667
    nick, chan = os.environ["TWITCH_NICK"], os.environ["TWITCH_CHAN"]
    for attempt in range(max(1, retries)):  # T299: reconnect with backoff
        try:
            sock = socket.create_connection((host, port), timeout=15)
            sock.sendall(f"PASS {os.environ['TWITCH_TOKEN']}\r\nNICK {nick}\r\nJOIN {chan}\r\n".encode())
            print(f"watching {chan} (flag-only)", flush=True)
            _watch_once(sock, rules)
            return
        except OSError as e:
            print(f"irc error (attempt {attempt + 1}): {redact(str(e))}", file=sys.stderr,
                  flush=True)
            if attempt + 1 >= max(1, retries):
                raise SystemExit(1) from e
            __import__("time").sleep(5 * (attempt + 1))


if __name__ == "__main__":
    run()
