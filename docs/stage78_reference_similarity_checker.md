# 78/100 — Reference Similarity Checker (ANF-REQ-030)

## Source and scope

The user's official 100-stage roadmap specifies stage 78 as **Reference Similarity Checker — 문장·장면·구조 유사성 검사**. Packaged `docs/requirements.md` maps **ANF-REQ-030** to stage 78: when a reference work is registered, similarity review must be part of manuscript review, and a referenced episode must not be finalized without a review record. `ANF-REQ-029` is the stage-39 baseline. The **original proposal attachment was not accessible** for independent inspection in this run; the user-supplied roadmap summary and packaged requirements are the source of truth. Baseline ZIP: `AI_Novel_Factory_stage77_local.zip` (502 files).

The existing stage-38 direct-overlap and stage-39 paragraph lexical comparison are **reused**, not duplicated. Stage 78 adds:

- **SENTENCE:** sentence candidates are compared using NFKC/casefold, punctuation/space-insensitive Unicode alphanumeric characters and 5-character shingle overlap. A Jaccard score ≥0.62 or containment ≥0.88 plus Jaccard ≥0.45 triggers **human review**. Sentences shorter than 16 normalized characters are outside this check; sentences over 500 are explicitly unexamined. Offsets refer to the original Python strings.
- **SCENE:** explicit scene start/end offsets must cover all non-whitespace text without overlap. Scene lexical shingle Jaccard ≥0.70, or containment ≥0.80 plus Jaccard ≥0.40, triggers review. Scenes shorter than 24 normalized characters are unexamined. A stage-65 `EpisodeDraftPreview` adapter checks draft/scene SHA-256 and separator integrity and rejects approved/persisted previews.
- **STRUCTURE:** only **user-supplied, abstract beat labels** from a closed vocabulary (`setup`, `inciting`, `escalation`, `setback`, `reversal`, `climax`, `resolution`, `hook`, `transition`) are compared. Four or more beats and `SequenceMatcher` ratio ≥0.90 trigger review. No reference-world/character names, prose, or plot details are stored as structure labels. Generic beat matches are **not** proof of copying.
- **Registration:** caller supplies the selected reference-ID set, an existing local `ReferenceCatalog` and transient extracted reference texts. Catalog checks that every selected ID exists, has `analyzed` status and matches the supplied **file** SHA-256 metadata. The checker does **not** prove that a caller-provided parsed text actually came from those original bytes, nor that the selected IDs are the complete project-specific reference association. This provenance and project-reference mapping must be verified by the later approval integration.
- **Review records:** `ReferenceSimilarityReviewStore` explicitly writes a small local SQLite audit receipt containing project/episode IDs, draft hash, a hash of reference-ID/text-hash pairs, status and timestamp. It stores **no manuscript or reference text, excerpts, names or paths**. `require_current_clear_review` **re-runs** all comparisons and requires a matching `clear` receipt for the current draft and reference text. It does not approve or finalize anything. Without an actual finalization endpoint (planned in stage 89), full end-to-end enforcement of the acceptance criterion is **not yet testable**.

## Status and failure behavior

| Status | Meaning |
| --- | --- |
| `blocked` | Stage-38 long verbatim overlap block, highest priority. |
| `review` | Stage-38/39 review or any sentence/scene/structure similarity trigger. Requires human review. |
| `inconclusive` | No flagged match but some comparison scope or reference registration evidence is missing. Never treated as clear. |
| `clear` | No flagged match **in the supplied and checked scope**; all required scene/beat annotations and catalog/selected-ID checks present. **Not a copyright or originality guarantee.** |

The report includes project/episode, hashes, numeric offsets/scores, channel, reference input number, unexamined markers, and explicit `manuscript_approved=False`, `publication_approved=False`, `persisted=False`. It never includes raw passages or paths. Missing scene/beat annotations, insufficient comparable sentences/scenes, oversized sentences, exceeded comparison budget, and evidence truncation prevent a false `clear`. Exceeding the stage-38/39 limits raises a fixed redacted error and **fails closed**.

## Important limits

The stage-38/39 existing raw-length/reference-count/paragraph/index limits still apply (up to 20 references). Sentence comparison examines up to 2,000 draft and 4,000 reference sentences and 300,000 shingle postings; at most 100 draft scenes, 300 scenes per reference and 40 numeric evidence entries are reported. No semantic embeddings, paraphrase detection, translation detection, actual copyright determination, reference provenance from raw bytes, or automatic plot-structure extraction. A reference text that is not supplied cannot be checked. High similarity in a generic beat sequence may be a false positive; the reviewer must inspect the local source. No reference text is sent to any AI model or external server.

**Novel Bible remains higher priority than Reference Profile.** Similarity review never modifies Novel Bible, writes or approves a manuscript, or publishes anything. The optional receipt database is an explicit local write, distinct from the read-only checker. The Windows EXE/GUI, actual local LLM inference and live Redis/Celery/pgvector integrations were not tested.

## Reproduce

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage78*.py' -q
# Full suite may need partitioning; see scripts/stage78_verify.py and
# docs/stage78_worktree_groups.json for the 8 disjoint module groups.
PYTHONPATH=src:tests python -m unittest <group modules> -q
```

Test evidence is in `docs/stage78_new_stderr.txt`, `docs/stage78_worktree_groups.json` and `docs/stage78_worktree_group1..8_stderr.txt`. GitHub, remote repositories, external servers and cloud AI APIs were not used.
