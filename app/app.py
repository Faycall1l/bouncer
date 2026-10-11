"""Gradio Space: edit rules live, see distribution + action. HF Space = gradio SDK."""
import gradio as gr
from gatekeeper import moderate

DEFAULT_RULES = "no-spam: no ads, links, self-promo\nbe-kind: no insults or hate\nno-spoiler: no spoilers without tag"

def parse_rules(t):
    d = {}
    for line in t.splitlines():
        if ":" in line:
            k, v = line.split(":", 1); d[k.strip()] = v.strip()
    return d or {"be-kind": "no insults"}

def run(msg, rules_t, thr):
    r = moderate(msg, parse_rules(rules_t), threshold=thr)
    dist = "\n".join(f"{k}: {v:.2f}" for k, v in (r.get("harm_dist") or {}).items()) if isinstance(r.get("harm_dist"), dict) else str(r.get("harm_dist"))
    return r["action"], f"{r['rule']} @ {r['confidence']:.2f}", f"harm={r['harm']} jail={r['jailbreak_p']:.2f} esc={r['escalate_p']:.2f}\n{dist}"

gr.Interface(fn=run,
    inputs=[gr.Textbox(label="chat message"), gr.Textbox(label="server rules (id: text per line)", value=DEFAULT_RULES), gr.Slider(0.5, 0.99, 0.85, label="gate threshold")],
    outputs=[gr.Label("action"), gr.Label("rule"), gr.Textbox("details")],
    title="Gatekeeper-1 — programmable mod, 30ms").launch()
