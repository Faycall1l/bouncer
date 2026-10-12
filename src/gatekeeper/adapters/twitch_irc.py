"""Twitch IRC stub, stdlib only (T076-T077). Read-only: flags, never bans.
Usage: TWITCH_TOKEN=... TWITCH_NICK=... TWITCH_CHAN=#x python -m gatekeeper.adapters.twitch_irc
"""
from __future__ import annotations

import os
import socket
import sys


def redact(s: str) -> str:  # T077
    tok = os.environ.get("TWITCH_TOKEN", "")
    return s.replace(tok, "***") if tok else s


def run():
    from gatekeeper import moderate, get_preset
    rules = get_preset("stream")
    host, port = "irc.chat.twitch.tv", 6667
    nick, chan = os.environ["TWITCH_NICK"], os.environ["TWITCH_CHAN"]
    sock = socket.create_connection((host, port), timeout=15)
    sock.sendall(f"PASS {os.environ['TWITCH_TOKEN']}\r\nNICK {nick}\r\nJOIN {chan}\r\n".encode())
    print(f"watching {chan} (flag-only)", flush=True)
    buf = ""
    while True:
        buf += sock.recv(4096).decode("utf-8", "replace")
        while "\r\n" in buf:
            line, buf = buf.split("\r\n", 1)
            if line.startswith("PING"):
                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                continue
            if "PRIVMSG" in line:
                user = line[1:].split("!", 1)[0]
                text = line.split("PRIVMSG", 1)[1].split(":", 1)[1]
                try:
                    res = moderate(text, rules)
                except Exception as e:  # noqa: BLE001
                    print("mod error", redact(str(e)), file=sys.stderr)
                    continue
                if res["action"] in ("delete", "flag", "escalate"):
                    print(f"[{res['action']}] <{user}> {text[:120]} ({res['rule']}@{res['confidence']:.2f})",
                          flush=True)


if __name__ == "__main__":
    run()
