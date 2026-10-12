# Stage 25 — Cliffhanger type **signals** / 클리프행어 유형 후보 분석

## Purpose / Scope

This component analyzes **only the ending portion of each episode** and returns
fixed-category signals. The seven candidate types are `revelation`, `danger`,
`interruption`, `decision`, `question`, `ellipsis`, and `exclamation`.

The first four are literal **lexical indicators**, not evidence that the
corresponding plot event actually happened. The last three are ending
punctuation patterns; an exclamation mark alone is **not a verified
cliffhanger**. `primary_type` is chosen by a documented fixed priority; multiple
signals may coexist in `candidate_types`.

## Method and limitations

- Only the last **ceil(25% of the episode's paragraphs)**, capped at **three
  whole paragraphs**, are scanned for lexical signals. For a single very long
  paragraph, the entire paragraph is scanned; this is a known precision limit.
- Ending punctuation is checked on the last paragraph, ignoring closing quotes.
- Paragraphs outside this scope do not generate lexical indicators.
- Stage-17 episode boundaries and Stage-22 body and ending-hook consistency
  checks are reused; headings, code blocks, and preface are excluded.
- Returned objects contain **only fixed labels, counts, and numeric statistics**.
  No matched original words, source excerpts, file paths, or source prose are
  stored. The analysis is entirely offline and requires no AI key/API.
- Text mentions can be figurative, negative, quoted, or unrelated to the plot.
  Full plot-aware hook classification and narrative interpretation are **not
  implemented**. Do not equate these proxies with reader retention metrics.
- Original works must not be reproduced; Novel Bible remains higher priority
  in any future text generation. No publication occurs here.

## API

```python
from ai_novel_factory.references import analyze_cliffhanger_text, analyze_reference_cliffhangers
result = analyze_cliffhanger_text("그는 돌아올까?")
assert result.primary_type == "question"
```

`analyze_reference_cliffhangers(parsed_reference, split=optional_cached_split)`
returns per-episode results and frequency counts. Invalid/stale split boundaries
are rejected with `ReferenceParseError`.

## Verification

```bash
PYTHONPATH=src python -m unittest tests.test_cliffhanger_analysis -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

The Windows GUI/EXE and semantic local-model analysis are outside this stage.
