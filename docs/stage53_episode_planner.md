# Stage 53 — Episode Planner (회차별 목표·사건 계획)

`src/ai_novel_factory/episode_planner.py` adds `plan_episodes` and `validate_episode_plans`.

- Derives one editable episode plan for each episode in a validated stage-52 Story Arc plan.
- Associates each episode with exactly one Arc, rejects missing/duplicate/misassigned plans.
- Includes slots for goals, required events, characters, emotional flow, foreshadowing and ending hook.
- Does not fabricate events, generate AI prose, read reference novels, save to DB or publish.
- All results are unapproved drafts; Novel Bible remains authoritative.
- Windows EXE and real model-based episode planning remain unimplemented.
