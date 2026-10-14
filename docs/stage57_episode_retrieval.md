# Stage 57 — 회차 요약 및 과거 원고 검색

`episode_retrieval.search_episode_history` searches existing EpisodeStore data locally using literal Unicode case-insensitive substring matching. It restricts results to the selected project and strictly earlier episodes, returning episode number, field, bounded excerpt and revision. Summary only by default; draft/final manuscript retrieval requires `include_manuscript=True`. No source/reference novel corpus, network calls, embeddings, automatic publication, or Novel Bible override. This is not semantic search, and it scans up to the existing 1,000-episode cap in memory. Source text excerpts are returned only to the local caller; callers must protect them from logs.

Run: `PYTHONPATH=src python -m unittest discover -s tests -q`.
