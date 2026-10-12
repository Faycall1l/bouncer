"""Gradio demo: preset dropdown, editable rules, threshold, action badge, dists, latency."""
from __future__ import annotations


def parse_rules(text: str) -> dict:
    d = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def launch():  # T069 target; polished by T081-T095
    import gradio as gr
    from gatekeeper import moderate, get_preset, list_presets
    from gatekeeper.explain import explain

    names = sorted(list_presets())
    preset_text = {n: "\n".join(f"{k}: {v}" for k, v in get_preset(n).items()) for n in names}

    def run(msg, preset, rules_t, thr):
        rules = parse_rules(rules_t) or get_preset(preset)
        from gatekeeper.rules import validate_rules, RuleError
        try:
            validate_rules(rules)
        except RuleError as e:  # T082: live validation errors
            return "⚠️ RULES ERROR", "-", str(e), "", "", ""
        from gatekeeper import GateConfig
        r = moderate(msg, rules, config=GateConfig(allow_threshold=thr, delete_threshold=thr))
        r["reason"] = explain(r, rules)
        badge = {"allow": "🟢 ALLOW", "flag": "🟡 FLAG", "delete": "🔴 DELETE",
                 "escalate": "⚪ ESCALATE"}[r["action"]]
        dist = r.get("rule_dist") or {}
        bars = "\n".join(f"{k}: {'█' * int(v * 20)} {v:.2f}" for k, v in
                         sorted(dist.items(), key=lambda kv: -kv[1])[:8])
        meters = (f"harm={r['harm']} jail={r['jailbreak_p']:.2f} "  # T086
                  f"esc={r['escalate_p']:.2f} abstained={r['abstained']}")
        return badge, f"{r['rule']} @ {r['confidence']:.2f}", r["reason"], bars, meters, f"{r.get('latency_ms', '?')} ms"

    with gr.Blocks(title="bouncer") as app:
        gr.Markdown("# 🛡️ bouncer — programmable mod, 30ms")
        preset = gr.Dropdown(names, value=names[0], label="preset")
        rules = gr.Textbox(value=preset_text[names[0]], lines=5, label="rules (id: text)")
        preset.change(lambda n: preset_text[n], preset, rules)
        msg = gr.Textbox(label="chat message")
        thr = gr.Slider(0.5, 0.99, 0.85, label="threshold")
        btn = gr.Button("Moderate")
        badge = gr.Label(label="action")
        rule = gr.Label(label="rule")
        reason = gr.Textbox(label="reason")
        dist = gr.Textbox(label="distribution")
        meters = gr.Textbox(label="meters")  # T086
        lat = gr.Label(label="latency")
        btn.click(run, [msg, preset, rules, thr], [badge, rule, reason, dist, meters, lat])
    app.queue().launch()
