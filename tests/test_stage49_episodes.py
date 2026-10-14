"""Stage 49 acceptance: all episode artifacts survive close/reopen offline."""
from __future__ import annotations

import contextlib
from io import StringIO
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database.episodes import (
    EpisodeError, EpisodeStore, MAX_EPISODES, MAX_SCENES, MAX_CHECKS,
)
from ai_novel_factory.database.episode_cli import main as cli_main


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "novel.db"
        self.store = EpisodeStore(self.db)
        self.addCleanup(self.store.close)
        self.pid = self.store.create_project("내 작품").project_id
        self.ep = self.store.create_episode(self.pid, 1, plot="원본 플롯")

    def test_create_episode_defaults(self):
        self.assertEqual(self.ep.episode, 1)
        self.assertEqual(self.ep.revision, 1)
        self.assertEqual(self.ep.plot, "원본 플롯")
        self.assertEqual(self.ep.draft, "")
        self.assertEqual(self.ep.final_text, "")
        self.assertEqual(self.ep.summary, "")

    def test_all_fields_persist_across_reopen(self):
        record = self.store.update_episode(self.pid, 1, expected_revision=1,
            plot="새 플롯", draft="초고 원고", final_text="확정본", summary="회차 요약")
        self.assertEqual(record.revision, 2)
        with EpisodeStore(self.db) as reopened:
            loaded = reopened.get_episode(self.pid, 1)
            self.assertEqual((loaded.plot, loaded.draft, loaded.final_text, loaded.summary),
                             ("새 플롯", "초고 원고", "확정본", "회차 요약"))

    def test_unicode_and_multiline(self):
        text = "第一章\n안녕하세요\t🚀\r\n다음 줄"
        self.store.update_episode(self.pid, 1, expected_revision=1, draft=text)
        with EpisodeStore(self.db) as reopened:
            self.assertEqual(reopened.get_episode(self.pid, 1).draft, text)

    def test_clearing_field(self):
        self.store.update_episode(self.pid, 1, expected_revision=1, plot="")
        self.assertEqual(self.store.get_episode(self.pid, 1).plot, "")

    def test_stale_update_fails_and_rolls_back(self):
        self.store.update_episode(self.pid, 1, expected_revision=1, draft="유효")
        before = self.store.get_project(self.pid).revision
        with self.assertRaises(EpisodeError):
            self.store.update_episode(self.pid, 1, expected_revision=1, draft="실패")
        self.assertEqual(self.store.get_episode(self.pid, 1).draft, "유효")
        self.assertEqual(self.store.get_project(self.pid).revision, before)

    def test_two_connections_stale_update(self):
        with EpisodeStore(self.db) as other:
            other.update_episode(self.pid, 1, expected_revision=1, draft="다른 창")
            with self.assertRaises(EpisodeError):
                self.store.update_episode(self.pid, 1, expected_revision=1, draft="내 창")

    def test_no_update_fields(self):
        with self.assertRaises(EpisodeError):
            self.store.update_episode(self.pid, 1, expected_revision=1)

    def test_duplicate_episode(self):
        with self.assertRaises(EpisodeError):
            self.store.create_episode(self.pid, 1)

    def test_episode_order(self):
        self.store.create_episode(self.pid, 10)
        self.store.create_episode(self.pid, 2)
        self.assertEqual([ep.episode for ep in self.store.list_episodes(self.pid)], [1, 2, 10])

    def test_missing_episode(self):
        with self.assertRaises(EpisodeError):
            self.store.get_episode(self.pid, 2)

    def test_project_isolation(self):
        other = self.store.create_project("두 번째").project_id
        self.assertEqual(self.store.list_episodes(other), ())
        with self.assertRaises(EpisodeError):
            self.store.get_episode(other, 1)
        self.store.create_episode(other, 1, plot="별도 플롯")
        self.assertEqual(self.store.get_episode(self.pid, 1).plot, "원본 플롯")

    def test_missing_project(self):
        with self.assertRaises(Exception):
            self.store.create_episode("a" * 32, 2)

    def test_project_revision_increases(self):
        before = self.store.get_project(self.pid).revision
        self.store.update_episode(self.pid, 1, expected_revision=1, summary="요약")
        self.assertEqual(self.store.get_project(self.pid).revision, before + 1)

    def test_invalid_episode_numbers(self):
        for number in (0, -1, 1_000_001, 1.0, True, "1", None):
            with self.subTest(number=number), self.assertRaises(EpisodeError):
                self.store.create_episode(self.pid, number)

    def test_invalid_field_types(self):
        for value in (42, None, b"bytes", [], {}):
            with self.subTest(value=value), self.assertRaises(EpisodeError):
                self.store.create_episode(self.pid, 2, plot=value)

    def test_invalid_text_controls(self):
        for value in ("nul\x00", "bad\x01", "bad\x7f", "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(EpisodeError):
                self.store.update_episode(self.pid, 1, expected_revision=1, draft=value)

    def test_plot_size_limit(self):
        with self.assertRaises(EpisodeError):
            self.store.update_episode(self.pid, 1, expected_revision=1, plot="가" * 27_000)

    def test_draft_size_limit(self):
        with self.assertRaises(EpisodeError):
            self.store.update_episode(self.pid, 1, expected_revision=1, draft="x" * 500_001)

    def test_total_size_limit(self):
        self.store.update_episode(self.pid, 1, expected_revision=1,
            draft="x" * 500_000, final_text="y" * 500_000)
        with self.assertRaises(EpisodeError):
            self.store.update_episode(self.pid, 1, expected_revision=2,
                plot="z" * 80_000, summary="w" * 80_000, draft="x" * 500_000)
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 2)

    def test_max_episode_count(self):
        # No large fixture: simulate the count returned by SQLite.
        for number in range(2, MAX_EPISODES + 1):
            self.store._db.execute("""INSERT INTO bible_episodes
                (project_id, episode, revision, created_at, updated_at)
                VALUES (?, ?, 1, '2026-10-12T00:00:00+00:00', '2026-10-12T00:00:00+00:00')""",
                (self.pid, number))
        self.store._db.commit()
        with self.assertRaises(EpisodeError):
            self.store.create_episode(self.pid, MAX_EPISODES + 1)

    def test_scene_persists_and_is_ordered(self):
        a = self.store.add_scene(self.pid, 1, 3, "마지막 장면", expected_revision=1)
        b = self.store.add_scene(self.pid, 1, 1, "첫 장면", expected_revision=2)
        with EpisodeStore(self.db) as reopened:
            scenes = reopened.list_scenes(self.pid, 1)
            self.assertEqual([s.scene_id for s in scenes], [b.scene_id, a.scene_id])
            self.assertEqual([s.text for s in scenes], ["첫 장면", "마지막 장면"])

    def test_scene_update(self):
        scene = self.store.add_scene(self.pid, 1, 1, "원문", expected_revision=1)
        updated = self.store.update_scene(self.pid, 1, scene.scene_id,
            expected_revision=2, position=2, text="수정")
        self.assertEqual((updated.position, updated.text), (2, "수정"))
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 3)

    def test_scene_update_only_text(self):
        scene = self.store.add_scene(self.pid, 1, 1, "원문", expected_revision=1)
        self.assertEqual(self.store.update_scene(self.pid, 1, scene.scene_id,
            expected_revision=2, text="수정").position, 1)

    def test_scene_update_only_position(self):
        scene = self.store.add_scene(self.pid, 1, 1, "원문", expected_revision=1)
        self.assertEqual(self.store.update_scene(self.pid, 1, scene.scene_id,
            expected_revision=2, position=2).text, "원문")

    def test_scene_no_changes(self):
        scene = self.store.add_scene(self.pid, 1, 1, "원문", expected_revision=1)
        with self.assertRaises(EpisodeError):
            self.store.update_scene(self.pid, 1, scene.scene_id, expected_revision=2)

    def test_scene_duplicate_position_rollback(self):
        self.store.add_scene(self.pid, 1, 1, "원본", expected_revision=1)
        before = self.store.get_project(self.pid).revision
        with self.assertRaises(EpisodeError):
            self.store.add_scene(self.pid, 1, 1, "중복", expected_revision=2)
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 2)
        self.assertEqual(self.store.get_project(self.pid).revision, before)

    def test_scene_update_duplicate_position_rollback(self):
        a = self.store.add_scene(self.pid, 1, 1, "a", expected_revision=1)
        b = self.store.add_scene(self.pid, 1, 2, "b", expected_revision=2)
        with self.assertRaises(EpisodeError):
            self.store.update_scene(self.pid, 1, b.scene_id, expected_revision=3, position=1)
        self.assertEqual(self.store.get_scene(self.pid, 1, b.scene_id).position, 2)
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 3)

    def test_scene_stale_revision(self):
        self.store.add_scene(self.pid, 1, 1, "a", expected_revision=1)
        with self.assertRaises(EpisodeError):
            self.store.add_scene(self.pid, 1, 2, "b", expected_revision=1)

    def test_scene_delete(self):
        scene = self.store.add_scene(self.pid, 1, 1, "a", expected_revision=1)
        self.store.delete_scene(self.pid, 1, scene.scene_id, expected_revision=2)
        self.assertEqual(self.store.list_scenes(self.pid, 1), ())
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 3)

    def test_scene_delete_stale(self):
        scene = self.store.add_scene(self.pid, 1, 1, "a", expected_revision=1)
        with self.assertRaises(EpisodeError):
            self.store.delete_scene(self.pid, 1, scene.scene_id, expected_revision=1)
        self.assertEqual(len(self.store.list_scenes(self.pid, 1)), 1)

    def test_scene_wrong_project(self):
        scene = self.store.add_scene(self.pid, 1, 1, "a", expected_revision=1)
        other = self.store.create_project("기타").project_id
        self.store.create_episode(other, 1)
        with self.assertRaises(EpisodeError):
            self.store.get_scene(other, 1, scene.scene_id)

    def test_scene_invalid_positions(self):
        for position in (0, -1, MAX_SCENES + 1, True, 2.5, "1"):
            with self.subTest(position=position), self.assertRaises(EpisodeError):
                self.store.add_scene(self.pid, 1, position, "장면", expected_revision=1)

    def test_scene_text_size_limit(self):
        with self.assertRaises(EpisodeError):
            self.store.add_scene(self.pid, 1, 1, "x" * 80_001, expected_revision=1)

    def test_check_persists(self):
        check = self.store.add_check(self.pid, 1, "continuity", "WARN", "확인 필요", expected_revision=1)
        with EpisodeStore(self.db) as reopened:
            self.assertEqual(reopened.get_check(self.pid, 1, check.check_id).note, "확인 필요")
            self.assertEqual(reopened.list_checks(self.pid, 1)[0].outcome, "WARN")

    def test_checks_do_not_change_episode_content_revision(self):
        self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=1)
        self.store.add_check(self.pid, 1, "manual", "NOT_RUN", expected_revision=1)
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 1)
        self.assertEqual(len(self.store.list_checks(self.pid, 1)), 2)

    def test_check_stale_after_edit(self):
        self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=1)
        self.store.update_episode(self.pid, 1, expected_revision=1, draft="새 초고")
        snapshot = self.store.snapshot(self.pid, 1)
        self.assertTrue(json.loads(snapshot.to_json())["checks"][0]["stale"])

    def test_check_not_stale_without_edit(self):
        self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=1)
        self.assertFalse(json.loads(self.store.snapshot(self.pid, 1).to_json())["checks"][0]["stale"])

    def test_check_bad_status(self):
        for status in ("UNKNOWN", "passed", "", None, 1):
            with self.subTest(status=status), self.assertRaises(EpisodeError):
                self.store.add_check(self.pid, 1, "manual", status, expected_revision=1)

    def test_check_bad_category(self):
        for category in ("", "Invalid Key", "reference original", None):
            with self.subTest(category=category), self.assertRaises(EpisodeError):
                self.store.add_check(self.pid, 1, category, "PASS", expected_revision=1)

    def test_check_stale_revision_rejected(self):
        self.store.update_episode(self.pid, 1, expected_revision=1, draft="v2")
        with self.assertRaises(EpisodeError):
            self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=1)
        self.assertEqual(self.store.list_checks(self.pid, 1), ())

    def test_check_note_size(self):
        with self.assertRaises(EpisodeError):
            self.store.add_check(self.pid, 1, "manual", "PASS", "a" * 8193, expected_revision=1)

    def test_snapshot_contains_all_six_artifact_types(self):
        self.store.update_episode(self.pid, 1, expected_revision=1,
            draft="초고", final_text="확정본", summary="요약")
        self.store.add_scene(self.pid, 1, 1, "장면", expected_revision=2)
        self.store.add_check(self.pid, 1, "manual", "PASS", "메모", expected_revision=3)
        snap = self.store.snapshot(self.pid, 1)
        self.assertEqual((snap.episode.plot, snap.episode.draft, snap.episode.final_text,
                          snap.episode.summary, snap.scenes[0].text, snap.checks[0].note),
                         ("원본 플롯", "초고", "확정본", "요약", "장면", "메모"))

    def test_snapshot_reopen(self):
        self.store.update_episode(self.pid, 1, expected_revision=1,
            draft="초고", final_text="확정본", summary="요약")
        self.store.add_scene(self.pid, 1, 1, "장면", expected_revision=2)
        self.store.add_check(self.pid, 1, "manual", "PASS", "메모", expected_revision=3)
        with EpisodeStore(self.db) as reopened:
            snap = reopened.snapshot(self.pid, 1)
            self.assertEqual(snap.scenes[0].text, "장면")
            self.assertEqual(snap.checks[0].note, "메모")
            self.assertEqual(snap.episode.final_text, "확정본")

    def test_snapshot_redacts_by_default(self):
        self.store.update_episode(self.pid, 1, expected_revision=1, draft="매우비밀원고")
        snap = self.store.snapshot(self.pid, 1)
        self.assertNotIn("매우비밀원고", snap.to_json())
        self.assertNotIn("원본 플롯", snap.to_json())
        self.assertIn("매우비밀원고", snap.to_json(reveal=True))

    def test_snapshot_no_publication_approval(self):
        self.store.update_episode(self.pid, 1, expected_revision=1, final_text="확정본")
        data = json.loads(self.store.snapshot(self.pid, 1).to_json(reveal=True))
        self.assertFalse(data["publication_approved"])

    def test_scene_and_check_redacted(self):
        self.store.add_scene(self.pid, 1, 1, "비밀 장면", expected_revision=1)
        self.store.add_check(self.pid, 1, "manual", "PASS", "비밀 검사", expected_revision=2)
        data = self.store.snapshot(self.pid, 1).to_json()
        self.assertNotIn("비밀 장면", data)
        self.assertNotIn("비밀 검사", data)

    def test_episode_delete_cascades(self):
        scene = self.store.add_scene(self.pid, 1, 1, "장면", expected_revision=1)
        check = self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=2)
        self.store.delete_episode(self.pid, 1, expected_revision=2)
        for table in ("bible_episode_scenes", "bible_episode_checks"):
            self.assertEqual(self.store._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        with self.assertRaises(EpisodeError):
            self.store.get_episode(self.pid, 1)

    def test_episode_delete_stale(self):
        self.store.update_episode(self.pid, 1, expected_revision=1, draft="v2")
        with self.assertRaises(EpisodeError):
            self.store.delete_episode(self.pid, 1, expected_revision=1)
        self.assertEqual(self.store.get_episode(self.pid, 1).revision, 2)

    def test_project_delete_cascades(self):
        self.store.add_scene(self.pid, 1, 1, "장면", expected_revision=1)
        self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=2)
        self.store.delete_project(self.pid)
        for table in ("bible_episodes", "bible_episode_scenes", "bible_episode_checks"):
            self.assertEqual(self.store._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_corrupt_episode_rejected(self):
        self.store._db.execute("UPDATE bible_episodes SET plot=?", ("\x00",))
        with self.assertRaises(EpisodeError):
            self.store.get_episode(self.pid, 1)

    def test_corrupt_scene_rejected(self):
        scene = self.store.add_scene(self.pid, 1, 1, "장면", expected_revision=1)
        self.store._db.execute("UPDATE bible_episode_scenes SET text=?", ("\x00",))
        with self.assertRaises(EpisodeError):
            self.store.get_scene(self.pid, 1, scene.scene_id)

    def test_corrupt_check_rejected(self):
        check = self.store.add_check(self.pid, 1, "manual", "PASS", expected_revision=1)
        self.store._db.execute("UPDATE bible_episode_checks SET note=?", ("\x00",))
        with self.assertRaises(EpisodeError):
            self.store.get_check(self.pid, 1, check.check_id)

    def test_corrupt_timestamps_rejected(self):
        self.store._db.execute("UPDATE bible_episodes SET created_at='yesterday'")
        with self.assertRaises(EpisodeError):
            self.store.get_episode(self.pid, 1)

    def test_version_limit(self):
        self.store._db.execute("UPDATE bible_episodes SET revision=2147483647")
        self.store._db.commit()
        with self.assertRaises(EpisodeError):
            self.store.update_episode(self.pid, 1, expected_revision=2147483647, draft="x")

    def test_reference_novel_not_ingested(self):
        # Only explicit text inputs are persisted; the store never reads reference catalogs.
        self.assertFalse(any("reference" in table[0] for table in self.store._db.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'bible_episode%'")))
        self.assertEqual(self.store.get_episode(self.pid, 1).plot, "원본 플롯")

    def test_existing_novel_bible_rules_preserved(self):
        rule = self.store.save_rule(self.pid, "canon", "주인공은 불멸이 아니다")
        self.store.update_episode(self.pid, 1, expected_revision=1, plot="별도 플롯")
        self.assertEqual(self.store.get_rule(self.pid, "canon").value, "주인공은 불멸이 아니다")


class EpisodeCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "episodes.db"
        with EpisodeStore(self.db) as store:
            self.pid = store.create_project("작품").project_id
        self.base = ["--database", str(self.db)]

    def run_cli(self, *args):
        output = StringIO()
        with contextlib.redirect_stdout(output):
            status = cli_main([*self.base, *args])
        return status, output.getvalue()

    def test_create_show_list(self):
        code, text = self.run_cli("episode-create", self.pid, "1")
        self.assertEqual(code, 0)
        self.assertIn("revision 1", text)
        self.assertIn("episode 1", self.run_cli("episode-list", self.pid)[1])
        self.assertIn("publication_approved", self.run_cli("episode-show", self.pid, "1")[1])

    def test_create_from_file(self):
        file = Path(self.tmp.name) / "plot.txt"
        file.write_text("비밀 플롯", encoding="utf-8")
        self.assertEqual(self.run_cli("episode-create", self.pid, "1", "--plot-file", str(file))[0], 0)
        self.assertNotIn("비밀 플롯", self.run_cli("episode-show", self.pid, "1")[1])
        self.assertIn("비밀 플롯", self.run_cli("episode-show", self.pid, "1", "--reveal")[1])

    def test_update_all_files(self):
        self.run_cli("episode-create", self.pid, "1")
        args = ["episode-set", self.pid, "1", "--revision", "1"]
        for field in ("plot", "draft", "final", "summary"):
            path = Path(self.tmp.name) / f"{field}.txt"
            path.write_text(f"{field} 비공개", encoding="utf-8")
            args.extend([f"--{field}-file", str(path)])
        self.assertEqual(self.run_cli(*args)[0], 0)
        self.assertIn("final 비공개", self.run_cli("episode-show", self.pid, "1", "--reveal")[1])

    def test_scene_add_and_list(self):
        self.run_cli("episode-create", self.pid, "1")
        path = Path(self.tmp.name) / "scene.txt"
        path.write_text("장면 원고", encoding="utf-8")
        code, output = self.run_cli("scene-add", self.pid, "1", "--revision", "1",
                                    "--position", "1", "--text-file", str(path))
        self.assertEqual(code, 0)
        self.assertIn("created scene", output)
        self.assertNotIn("장면 원고", self.run_cli("scene-list", self.pid, "1")[1])

    def test_check_add_and_list(self):
        self.run_cli("episode-create", self.pid, "1")
        code, output = self.run_cli("check-add", self.pid, "1", "--revision", "1",
                                    "--category", "manual", "--outcome", "WARN")
        self.assertEqual(code, 0)
        self.assertIn("manual check", self.run_cli("check-list", self.pid, "1")[1])

    def test_cli_invalid_revision(self):
        self.run_cli("episode-create", self.pid, "1")
        path = Path(self.tmp.name) / "draft.txt"
        path.write_text("원고", encoding="utf-8")
        code, output = self.run_cli("episode-set", self.pid, "1", "--revision", "2",
                                    "--draft-file", str(path))
        self.assertEqual(code, 1)
        self.assertNotIn("원고", output)

    def test_cli_symlink_rejected(self):
        self.run_cli("episode-create", self.pid, "1")
        source = Path(self.tmp.name) / "original.txt"
        source.write_text("비밀", encoding="utf-8")
        alias = Path(self.tmp.name) / "alias.txt"
        try:
            alias.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        code, _ = self.run_cli("episode-set", self.pid, "1", "--revision", "1",
                               "--draft-file", str(alias))
        self.assertEqual(code, 1)

    def test_cli_missing_file(self):
        self.run_cli("episode-create", self.pid, "1")
        code, _ = self.run_cli("episode-set", self.pid, "1", "--revision", "1",
                               "--draft-file", str(Path(self.tmp.name) / "missing.txt"))
        self.assertEqual(code, 1)

    def test_cli_delete(self):
        self.run_cli("episode-create", self.pid, "1")
        self.assertEqual(self.run_cli("episode-delete", self.pid, "1", "--revision", "1")[0], 0)
        self.assertEqual(self.run_cli("episode-list", self.pid)[1], "")

    def test_cli_subprocess_offline(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run([sys.executable, "-m", "ai_novel_factory.database.episode_cli",
            *self.base, "episode-create", self.pid, "1"], cwd=root,
            env={"PYTHONPATH": str(root / "src")}, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("created episode", completed.stdout)


if __name__ == "__main__":
    unittest.main()
