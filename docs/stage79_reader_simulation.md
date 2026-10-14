# 79/100 — Reader Simulation: annotated reference indicators (ANF-REQ-055)

## Provenance and scope

The user's official 100-step roadmap identifies stage 79 as **Reader Simulation — 몰입도·전개·캐릭터 평가**. Packaged `docs/requirements.md` maps `ANF-REQ-055` to stage 79: provide **virtual reader perspective engagement, pacing, and hook evaluation**, store the result as **reference-only indicators**, and never label it an objective quality guarantee. The roadmap also requires **character**. Baseline is `AI_Novel_Factory_stage78_local.zip` (555 ZIP members). The **original planning attachment was not present among the conversation's accessible files** in this run; the user's directly supplied roadmap and the packaged requirements were used instead.

## Implemented (strictly offline, deterministic, explicitly annotated)

- `reader_simulation.py`: `simulate_reader_profiles(project_id, episode_number, draft, scenes=...)` returns a read-only report. A human reviewer must provide each scene's Python character offsets, SHA-256 digest of that scene, and **yes/no/unknown** annotations for six *reviewer-judged* features: `goal_visible`, `tension_present`, `development`, `character_choice`, `consequence`, `closing_hook`. These are **not** extracted from prose, and the checker cannot verify that a reviewer's subjective judgment is correct. No AI model is called.
- The checker requires 1–100 sequential, nonoverlapping scenes, covering all non-whitespace manuscript text; scene hashes must match exactly. Drafts over 1,000,000 characters, malformed Unicode, incorrect identifiers, incorrect offsets and wrong annotation types fail with redacted errors. Stage-65 unapproved `EpisodeDraftPreview` scenes can be adapted using `annotations_from_episode_preview`, with draft and per-scene hashes and exact separators verified.
- Four **transparent feature-presence proxies** are calculated on a 0–100 scale. These numbers represent the **percentage of annotated yes-markers under fixed weights**, not an empirical prediction of how many readers will like a work:

  | Dimension | Formula (weighted scene mean, percent) |
  |---|---|
  | engagement | goal visible 35%, tension 40%, development 25% |
  | pacing | tension 30%, development 50%, consequence 20% |
  | character | character choice 60%, consequence 40% |
  | hook | **final scene only**: closing hook 70%, tension 30% |

- Three hypothetical preference profiles weight these four proxies: `momentum` (25/40/10/25%), `character` (20/10/55/15%), `cliffhanger` (15/15/10/60%). These are named **hypothetical weighting schemes**, not simulated human readers or validated preference distributions.
- Any unknown marker required by a dimension produces `score=None` for that dimension; **all** profile scores then become `None`, and status is `INCOMPLETE_ANNOTATIONS`. Unknown never means negative. A fully annotated report has status `ANNOTATED_PROXY_ONLY`, **not** `passed`, `clear`, `approved`, or `high quality`.
- `reader_simulation_records.py`: opt-in `ReaderSimulationStore` stores only identifiers, draft/annotation SHA-256 hashes, numeric scores/coverage, methodology, status and UTC time in local SQLite. It **recomputes** reports against the supplied current draft/annotations before writing, rejects forged status/approval/scores, and only retrieves receipts matching current hashes and recomputed indicators. There is no manuscript text, scene prose, reference text, user commentary or file path in a receipt. Duplicate writes update one row.
- The report and receipt always carry `manuscript_approved=False`, `publication_approved=False`. Saving a reader indicator **never** finalizes or publishes an episode. Novel Bible and Reference Profile are not changed; no reference work text is read or copied.

## Limitations and follow-up

This is a *structured manual rubric*, not actual reader simulation or automatic literary criticism. An annotation can be mistaken or biased; 100/100 is not an objective quality score. Scores are not calibrated against real readers. No real readers, model inference, GUI, Windows EXE, Redis/Celery, pgvector, publication adapter, or end-to-end finalization were tested. The existing stage-78 reference-similarity review requirement and stage-89 approval remain separate. This is a local opt-in indicator database, not an approval gate. Future automated NLP or real reader testing would require independent evidence and consent. The previously reported SQLite `ResourceWarning` may recur in older tests.

## Reproduction

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage79*.py' -q
# Run all 92 test_*.py modules in 8 disjoint groups:
PYTHONPATH=src:tests python scripts/stage79_verify.py
```

See `docs/stage79_test_results.json`, `docs/stage79_verification_log.txt`, and the `stage79_*_groups.json` and stderr logs. No GitHub, remote repository, external server, or cloud AI API was accessed.
