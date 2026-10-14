# Stage 76 / 100 — Style Checker (ANF-REQ-053)

## Source of truth

Official 100-step roadmap: **76 — Style Checker: 문체·시점 일관성 검사**. `docs/requirements.md` defines `ANF-REQ-053` with the completion criterion **금지 규칙 위반 시 경고를 출력한다**. Baseline: `AI_Novel_Factory_stage75_local.zip` (448 files). This implementation does **not** perform full NLP literary style interpretation or approve publication.

## New source and tests

- `src/ai_novel_factory/style_checker.py`: `check_style`, `check_episode_style`, `ViewpointClaim`, `StyleReport`, `StyleFinding`, `StyleCheckerError`.
- `tests/test_stage76_style_checker.py`: exact matching, precedence, offsets, limits, revision, provenance, integrity and no-write tests.

## Deterministic supported rules

The current Style Bible can contain arbitrary author-written directives. Only these **explicit, machine-readable** rule keys are executed:

| Key | Example directive value | Exact interpretation |
| --- | --- | --- |
| `forbidden_phrase_<id>` | `피식 웃었다` | Literal, case-sensitive, non-overlapping substring; reports offsets and SHA-256 but not the phrase itself |
| `max_sentence_chars` | `90` | Unicode codepoint length of punctuation/newline-segmented sentence, including ending punctuation, excluding surrounding whitespace |
| `max_paragraph_chars` | `400` | Unicode codepoint length of paragraph separated by blank lines, excluding surrounding whitespace |
| `viewpoint` | `third_person_limited` | Compares **reviewer-labelled** `ViewpointClaim` spans, not automatically inferred narration |

Recognized viewpoint tags: `first_person`, `third_person_limited`, `third_person_omniscient`.
A plain-language label like `3인칭 제한` is **not parsed** into a tag; it remains `unexamined_rules`. Missing viewpoint labels also remain explicitly unexamined, not a stylistic pass. Values for executable numeric rules must be positive decimal integers up to 1,000,000; malformed executable rules fail closed.

Novel Bible's matching keys override Style Bible keys. Other freeform author directives are reported under `unexamined_rules`, not misrepresented as verified. The checker requires both Novel Bible and Style Bible to be populated. Results are read-only, bounded (max 1 million characters, 1,000 findings, 500 viewpoint labels), with manuscript/violation SHA-256 and redacted error messages. Check episode previews only if the unapproved stage-65 scene offsets and hashes are consistent. No similarity check, automated rewriting, database write, publication approval or network access.

## Limitations

- Simple punctuation/newline sentence splitting is not a Korean grammatical sentence detector; quotation, abbreviation, punctuation and dialogue require manual verification.
- Unicode length means code points, not display columns, UTF-8 bytes or grapheme clusters.
- The reader must explicitly label viewpoint evidence; free-text viewpoint changes cannot be detected automatically.
- Findings only cover the explicitly applied rules. `passed_checked_rules` does not certify general quality, continuity or originality.
- Tested on local Linux Python. Windows GUI/EXE, real local model inference and Redis/Celery were not exercised. Existing unrelated SQLite ResourceWarning remains.

## Local verification

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage76*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -q
```

See `docs/stage76_test_results.json` and `docs/stage76_verification_log.txt` for measured totals and extraction/retest details. No GitHub, remote services, cloud APIs or remote repository were used.
