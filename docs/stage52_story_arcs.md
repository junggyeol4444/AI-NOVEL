# Stage 52 — ANF-REQ-042: Story Arc structure

`src/ai_novel_factory/story_arcs.py` provides `plan_story_arcs` and `validate_arc_coverage`.

- Splits 1–10,000 episodes into contiguous non-overlapping Story Arc ranges, covering every episode exactly once.
- Supports explicit Arc count or deterministic approximately 30-episode groups.
- Rejects invalid counts and detects gaps, overlaps, wrong numbering, or missing final episodes.
- No network, reference novel prose, model inference, database writes, or automatic publishing.
- Objectives are unfilled review placeholders, **not** an AI-generated narrative plot. Novel Bible is authoritative; user approval is required.
- Actual local LLM-driven story design and Windows EXE are not implemented by this stage.
