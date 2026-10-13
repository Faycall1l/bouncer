---
title: bouncer — programmable live-chat mod
emoji: 🛡️
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "4.44.0"
app_file: app.py
pinned: false
---

"""HF Space entry (T093). Full UI lives in gatekeeper.demo_app."""
from gatekeeper.demo_app import launch

if __name__ == "__main__":  # T212: import-safe
    launch()
