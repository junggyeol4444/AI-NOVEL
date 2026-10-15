"""Stage 87 / ANF-REQ-060: 120-episode offline MOCK long-memory stress trial.

This is an isolated test harness, not automated canonical memory extraction.
It creates synthetic Bible/character/world fixtures, draft summaries and
versioned mock manuscripts in temporary local SQLite. It never FINAL-izes,
authenticates an approval, calls a network service, or applies Memory Deltas.
Conflict detection checks only explicit key/value assertions against Bible
rules; it does not infer semantic contradictions from natural-language prose.
"""
from __future__ import annotations
from contextlib import closing

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3

from .database.characters import CharacterStore
from .database.world_canon import WorldCanonStore
from .episode_context import ContextFact, select_episode_context
from .episode_integration import run_one_episode
from .episode_planner import plan_episodes
from .episode_retrieval import search_episode_history
from .local_models import MockSceneProvider
from .local_task_queue import LocalTaskQueue
from .manuscript_versions import ManuscriptVersionStore
from .orchestrator import OfflineLiteralChecker
from .scene_planner import ScenePlan
from .story_arcs import StoryArc, StoryArcPlan, validate_arc_coverage

EPISODES = 120
ANCHOR = 'ANF_TEST_ANCHOR_001'
CANON_KEY = 'travel_rule'
CANON_VALUE = 'ground_only'


class LongMemoryTrialError(ValueError):
    """No manuscript, secret or local file path in validation messages."""


def _conflicting_explicit_assertions(rules: dict[str, str], assertions: dict[str, str]) -> tuple[str, ...]:
    """Only exact, structured canon-key conflicts; no NLP interpretation."""
    return tuple(sorted(key for key, value in assertions.items()
                        if key in rules and rules[key] != value))


def run_120_episode_memory_trial(*, conflict_episode: int | None = None) -> dict:
    """Report a bounded 120-episode MOCK draft/memory stress test.

    `conflict_episode` injects a conflicting *synthetic candidate* assertion.
    The candidate is never written to canon, and that episode's draft is
    blocked. No user manuscript or reference novel is read.
    """
    if conflict_episode is not None and (type(conflict_episode) is not int
                                         or not 1 <= conflict_episode <= EPISODES):
        raise LongMemoryTrialError('invalid synthetic conflict episode')
    arc = StoryArcPlan(EPISODES, (
        StoryArc(1, 1, 40, 'ARC 1', '모의 시험'),
        StoryArc(2, 41, 80, 'ARC 2', '모의 시험'),
        StoryArc(3, 81, 120, 'ARC 3', '모의 시험'),
    ))
    if not validate_arc_coverage(arc):
        raise LongMemoryTrialError('invalid long-run arc fixture')
    plans = plan_episodes(arc)
    entries: list[dict] = []
    retrieval_checks = 0
    retrieval_failures = 0
    canon_checks = 0
    canon_mismatches = 0
    conflict_count = 0
    with TemporaryDirectory(prefix='anf87_mock_') as directory:
        base = Path(directory)
        db = base / 'bible.sqlite'
        store = ManuscriptVersionStore(db)
        queue = LocalTaskQueue(base / 'tasks.sqlite')
        characters = CharacterStore(db)
        world = WorldCanonStore(db)
        try:
            project_id = store.create_project('120화 모의 장기 기억 시험').project_id
            store.save_rule(project_id, CANON_KEY, CANON_VALUE)
            hero = characters.create_character(project_id, name='TEST_HERO',
                personality='테스트용 성격', goal='테스트용 목표', speech_style='테스트용 화법')
            region = world.create_entry(project_id, category='region', name='TEST_REGION',
                                        description='테스트용 세계 설정')
            provider = MockSceneProvider()
            for number, template in enumerate(plans, 1):
                plan = replace(template, goal='장기 기억 모의 시험',
                               required_events=('검증',), characters=('fixture-hero',))
                scenes = (ScenePlan(number, 1, '모의 시험 장소', ('fixture-hero',),
                                    f'{number}화 모의 장면', '모의 충돌', '모의 결과'),)
                # The canon comes from the real local Bible DB, not reference patterns.
                rules = {rule.key: rule.value for rule in store.list_rules(project_id)}
                current_character = characters.get_character(project_id, hero.character_id)
                current_world = world.get_entry(project_id, region.entry_id)
                canon_checks += 1
                if (rules.get(CANON_KEY) != CANON_VALUE
                        or current_character != hero or current_world != region):
                    canon_mismatches += 1
                candidate = {CANON_KEY: ('flight_enabled' if number == conflict_episode
                                         else CANON_VALUE)}
                conflicts = _conflicting_explicit_assertions(rules, candidate)
                conflict_count += len(conflicts)
                entry = {'episode': number, 'status': 'FAILED', 'error_code': None,
                         'draft_sha256': None, 'summary_sha256': None,
                         'canon_conflicts': len(conflicts), 'saved': False,
                         'approved': False, 'published': False}
                store.create_episode(project_id, number)
                if conflicts:
                    entry.update(status='BLOCKED_EXPLICIT_CANON_CONFLICT',
                                 error_code='EXPLICIT_CANON_CONFLICT')
                    entries.append(entry)
                    continue
                facts = [ContextFact(project_id, 'novel_bible', CANON_KEY,
                                     rules[CANON_KEY]),
                         ContextFact(project_id, 'character', hero.character_id,
                                     current_character.personality),
                         ContextFact(project_id, 'world', region.entry_id,
                                     current_world.description)]
                # Persisted episode summaries provide long-range, local retrieval.
                if number > 1:
                    first = store.get_episode(project_id, 1)
                    if first.summary:
                        facts.append(ContextFact(project_id, 'episode_summary', 'ep1',
                                                 first.summary))
                    previous = store.get_episode(project_id, number - 1)
                    if previous.summary and number - 1 != 1:
                        facts.append(ContextFact(project_id, 'episode_summary',
                                                 f'ep{number-1}', previous.summary))
                    hits = search_episode_history(store, project_id, number, ANCHOR)
                    retrieval_checks += 1
                    if (len(hits) != 1 or hits[0].episode != 1
                            or hits[0].field != 'summary'):
                        retrieval_failures += 1
                context = select_episode_context(project_id, plan, tuple(facts))
                if (not context.facts or context.facts[0].source != 'novel_bible'
                        or any(f.project_id != project_id for f in context.facts)):
                    entry['error_code'] = 'CONTEXT_CANON_PRIORITY_FAILED'
                    entries.append(entry)
                    continue
                task_id = f'anf87-episode-{number:03d}'
                queue.enqueue(project_id, number, task_id=task_id)
                try:
                    run = run_one_episode(queue, task_id, project_id, plan, scenes,
                                          context, provider, OfflineLiteralChecker(()))
                except Exception:
                    # Test-only provider faults are sanitized, never returned verbatim.
                    entry['error_code'] = 'MOCK_PROVIDER_EXCEPTION'
                    entries.append(entry)
                    continue
                if (run is None or run.task.status != 'COMPLETED'
                        or run.workflow is None or run.status != 'AWAITING_HUMAN_REVIEW'
                        or run.workflow.preliminary_check is None
                        or not run.workflow.preliminary_check.passed
                        or run.workflow.preview is None):
                    entry['error_code'] = 'MOCK_WORKFLOW_FAILED'
                    entries.append(entry)
                    continue
                preview = run.workflow.preview
                if (preview.project_id != project_id or preview.episode_number != number
                        or preview.provider != 'offline-mock-v1'
                        or len(preview.scenes) != 1
                        or sha256(preview.draft.encode('utf-8')).hexdigest()
                           != preview.draft_sha256):
                    entry['error_code'] = 'DRAFT_INTEGRITY_FAILED'
                    entries.append(entry)
                    continue
                # Store the synthetic summary *before* versioning so version
                # history stays in sync with episode revisions.
                summary = (f'ANF_TEST_SUMMARY_E{number:03d} '
                           + (ANCHOR if number == 1 else 'MOCK_MEMORY_ONLY'))
                updated = store.update_episode(project_id, number,
                                               expected_revision=1, summary=summary)
                version = store.save_version(project_id, number, preview.draft,
                                             kind='DRAFT', expected_revision=updated.revision)
                saved = store.get_episode(project_id, number)
                if (saved.draft != preview.draft or saved.summary != summary
                        or saved.final_text or version.kind != 'DRAFT'
                        or queue.get(task_id).attempts != 1):
                    entry['error_code'] = 'DRAFT_PERSISTENCE_MISMATCH'
                else:
                    entry.update(status='DRAFT_REQUIRES_USER_APPROVAL', saved=True,
                                 draft_sha256=preview.draft_sha256,
                                 summary_sha256=sha256(summary.encode('utf-8')).hexdigest())
                entries.append(entry)
            # Check all 120 records, even if an injected conflict blocked a draft.
            stored = store.list_episodes(project_id)
            contiguous = [e.episode for e in stored] == list(range(1, EPISODES+1))
            final_count = sum(bool(e.final_text) for e in stored)
            draft_count = sum(bool(e.draft) for e in stored)
            summary_count = sum(bool(e.summary) for e in stored)
            version_count = sum(len(store.list_versions(project_id, n))
                                for n in range(1, EPISODES+1))
            rules_unchanged = store.get_rule(project_id, CANON_KEY).value == CANON_VALUE
        finally:
            store.close()
            characters.close()
            world.close()
        # Reopen the same file to verify persistence beyond an in-memory cache.
        reopened = ManuscriptVersionStore(db)
        try:
            reopened_episodes = reopened.list_episodes(project_id)
            reopen_count = len(reopened_episodes)
            reopen_version_count = sum(len(reopened.list_versions(project_id, n))
                                       for n in range(1, EPISODES+1))
            reopen_anchor = search_episode_history(reopened, project_id,
                                                    EPISODES+1, ANCHOR)
            reopen_anchor_ok = (len(reopen_anchor) == 1 and reopen_anchor[0].episode == 1)
            with closing(sqlite3.connect(db)) as connection, connection:
                integrity_ok = connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                foreign_key_errors = len(connection.execute('PRAGMA foreign_key_check').fetchall())
        finally:
            reopened.close()
    errors = sum(bool(e['error_code']) for e in entries)
    saved_count = sum(e['saved'] for e in entries)
    return {
        'stage': 87, 'requirement_id': 'ANF-REQ-060',
        'kind': 'DETERMINISTIC_OFFLINE_MOCK_LONG_MEMORY_STRESS_NOT_REAL_AI',
        'expected_episodes': EPISODES, 'attempted_episodes': len(entries),
        'episode_numbers_contiguous': contiguous,
        'successful_drafts': saved_count, 'stored_draft_count': draft_count,
        'stored_summary_count': summary_count, 'version_count': version_count,
        'reopened_episode_count': reopen_count, 'reopened_version_count': reopen_version_count,
        'anchor_retrieved_after_reopen': reopen_anchor_ok,
        'memory_retrieval_checks': retrieval_checks,
        'memory_retrieval_failures': retrieval_failures,
        'canon_consistency_checks': canon_checks,
        'canon_mismatch_count': canon_mismatches,
        'explicit_canon_conflict_count': conflict_count,
        'conflict_blocked_episode_count': sum(e['status'] == 'BLOCKED_EXPLICIT_CANON_CONFLICT'
                                              for e in entries),
        'error_count': errors, 'bible_rule_unchanged': rules_unchanged,
        'sqlite_integrity_ok': integrity_ok, 'sqlite_foreign_key_errors': foreign_key_errors,
        'final_version_count': final_count,
        'human_approval_authenticated': False, 'publication_approved': False,
        'reference_text_used': False, 'memory_delta_applied': False,
        'passed': (len(entries) == EPISODES and contiguous and errors == 0
                   and saved_count == draft_count == summary_count == version_count == EPISODES
                   and reopen_count == reopen_version_count == EPISODES
                   and reopen_anchor_ok and retrieval_checks == EPISODES-1
                   and retrieval_failures == 0 and canon_checks == EPISODES
                   and canon_mismatches == 0 and conflict_count == 0 and rules_unchanged
                   and integrity_ok and foreign_key_errors == 0 and final_count == 0),
        'episodes': entries,
        'limitations': [
            'Synthetic, structured canon fixtures; no prose-semantic contradiction detection',
            '120 MOCK drafts and summaries, not 120 real AI-written novel chapters',
            'No automatic memory delta extraction/application or authenticated user approval',
            'Only stage-70 literal preliminary checker, not full stage-71..80 QC',
            'No Windows EXE/GUI, real local LLM, Redis/Celery/pgvector or external services',
        ],
    }
