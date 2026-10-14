# Stage 77 / 100 — Repetition and similar-sentence frequency (ANF-REQ-054)

## Provenance and acceptance criterion

The user-provided 100-stage roadmap defines stage 77 as **반복 표현과 유사 문장 사용 빈도 검사**. The shipped `docs/requirements.md` specifies `ANF-REQ-054`: **반복 문구 테스트에서 지정 횟수 초과를 탐지한다**. Source baseline is `AI_Novel_Factory_stage76_local.zip` (459 entries). The original proposal attachment was **not accessible** in this run; the supplied roadmap summary and the baseline ZIP's requirements are the available specification. Do not infer that the original attachment was independently inspected.

## Implementation

`src/ai_novel_factory/repetition_checker.py` exports `check_repetition`, `check_episode_repetition`, `WatchedPhrase`, `RepetitionPolicy`, `RepetitionReport`, `RepetitionFinding`, and `RepetitionCheckerError`. The input is a locally held, unapproved manuscript. The checker is deterministic, has no DB writes or network calls, and does not grant publication approval.

- **WATCHED_PHRASE_OVERUSED**: an explicitly configured literal phrase exceeds its individual `allowed_occurrences`. Literal non-overlapping matches, with optional case-insensitive comparison (rejected when Unicode casefold changes offsets).
- **REPEATED_PHRASE**: word n-grams (default 2–3 words, at least 5 codepoints including separators) appear more than `max_auto_phrase_occurrences` (default 3). Tokens do not cross punctuation/newline sentence boundaries.
- **REPEATED_SENTENCE**: at least two punctuation/newline-separated sentences of normalized length >= 10 are identical after NFKC, casefold and punctuation/whitespace removal.
- **SIMILAR_SENTENCE**: two distinct normalized sentence strings meet the default `SequenceMatcher` ratio >= 0.88; candidates must share at least one character trigram. These are **surface similarities**, not semantic similarity, plagiarism or originality judgments.

`RepetitionFinding` contains offsets, SHA-256 digests, count, configured limit and optional rounded similarity. No prose excerpt or watched phrase text appears in the report. `watched_key` must be a non-sensitive lowercase identifier. `RepetitionReport.passed_checked_scope` is false if any finding or incomplete-scope marker exists; even true does **not** certify literary quality or originality. For an existing stage-65 episode draft, `check_episode_repetition` verifies the unapproved status, whole-draft hash, scene spans/hashes and separators before checking.

## Explicit limits and interpretation

- Manuscript maximum 1,000,000 Python Unicode codepoints; 100 watched phrases; 1,000 findings; first 1,000 occurrence offsets per finding.
- Automatic n-gram scan: first 60,000 word tokens; fuzzy scan: first 3,000 unique normalized sentences, at most 5,000 candidate comparisons; normalized sentences > 500 characters skipped for fuzzy matching.
- When a budget is reached, report includes a named `unexamined` marker (`automatic_phrase_token_budget_exceeded`, `fuzzy_sentence_count_budget_exceeded`, `fuzzy_pair_budget_exceeded`, `fuzzy_sentence_length_budget_exceeded`, `finding_count_budget_exceeded`, or `occurrence_offsets_truncated`). The remaining scope is **not claimed to have passed**.
- Sentence boundaries are punctuation/newline heuristics, not a Korean linguistic parser. Word n-grams are simple Unicode alphanumeric tokens, so Korean spacing and inflection changes may affect detection. Short sentences are deliberately excluded from near-duplicate checks to reduce false positives. NFKC/casefold can conflate visually or semantically distinct writing; reviewers must inspect offsets.
- Trigram candidate filtering may miss similar sentences with no shared trigrams; fuzzy scans are limited and can produce false positives. No reference-book comparisons, reference-novel text ingestion, rewriting, memory updates, AI model calls or publication actions are included. Reference Similarity Checker is the **next** roadmap stage (78).
- No Windows EXE/GUI, actual local model inference or live Redis/Celery connection was tested. The pre-existing SQLite ResourceWarning is unrelated and may persist.

## Reproduce

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage77*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -q
```

See `docs/stage77_test_results.json` and `docs/stage77_verification_log.txt` for measured results. GitHub, external servers, cloud AI APIs and remote repositories were not used.
