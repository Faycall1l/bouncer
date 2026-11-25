# SVG animation guidelines and templates

_(Last checked against v0.5.0.)_

See the [glossary](glossary.md). This page records the animation decisions
used by the repo. The rules are not decorative: they keep the SVGs readable in
browsers and avoid one-shot or jittery visuals.

A recommended motion is the WaterTian "Loop with hold phase": the same
position is held while the motion reverses, so the cycle feels timed rather
than running one pass.

## Templates/guidelines used

- MDN: [SVG animation with SMIL](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_animation_with_SMIL)
  - `<animate>` for numeric attributes, `<animateTransform>`, and `<animateMotion>` for path motion.
- W3C: [SMIL spec](https://www.w3.org/TR/SMIL/) for timing semantics such as `keyTimes` and `repeatCount`.
- WaterTian: [svg-motion-cookbook](https://github.com/WaterTian/svg-motion-cookbook)
  - Pattern 1, loop with hold phase: `values`, `keyTimes`, and a `repeatCount="indefinite"`.

## Local rules

1. Prefer SMIL for readable browser SVGs; no JavaScript and no CSS keyframes for this repo's animated assets.
2. Every loop must end with `repeatCount="indefinite"`; a literal `begin="0s" dur="... "` without a repeat policy is a one-shot demo, not a repo asset.
3. Use `keyTimes` with an explicit hold phase for rhythm: for example `values="0;360;360;0" keyTimes="0;0.45;0.85;1"`.
4. Keep `dur` short enough to read, usually 6-10 seconds for system diagrams.
5. Use `<animateMotion>` for a flow path; use `<animate>` for discrete counters/dots.
6. If the animation is decorative, keep the motion slow, monotone, and semantic: motion should imply the system flow, not draw attention away from the contents.

## Receipts

- `docs/assets/system-architecture.svg`: uses MDN `animateMotion` and indefinite repeat.
- `docs/assets/gate-precedence.svg`: uses WaterTian loop-with-hold pattern 1 with `keyTimes` and indefinite repeat.
