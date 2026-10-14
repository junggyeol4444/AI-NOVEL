# Stage 54 — Scene Planner (ANF-REQ-044)

`src/ai_novel_factory/scene_planner.py` creates editable, numbered scene slots for a validated episode plan. Each scene has location, characters, goal, conflict, emotional direction, draft status and deterministic origin. `validate_scene_plans` checks contiguous scene numbering, episode ownership, field types, and optional completion of essential details. No AI text generation, automatic DB persistence, reference text reuse, publication, or user approval is performed. Novel Bible remains authoritative. Windows EXE remains untested.
