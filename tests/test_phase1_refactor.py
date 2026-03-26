import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.core import ctf_case_state
from scripts.core import ctf_lane_select
from scripts.ctfd import ctfd_pipeline
from scripts.index import ctf_index_build
from scripts.index import ctf_index_query
from scripts.learn import ctf_learn
from scripts.learn import ctf_meta
from scripts.ops import ctf_health_report
from scripts.ops import ctf_path_sanity
from scripts.submit import ctf_pipeline_submit_gate
from scripts.submit import ctf_submit_candidates


class Phase1RefactorTests(unittest.TestCase):
    def test_normalize_project_key(self):
        self.assertEqual(
            ctf_meta.normalize_project_key("demo-project_20260308_181804"),
            "demo-project",
        )

    def test_map_category_hardware(self):
        category, sub_category = ctf_meta.map_category("hardware")
        self.assertEqual(category, "forensics")
        self.assertEqual(sub_category, "hardware")

    def test_load_category_meta_from_challenge_txt(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / "challenge.txt").write_text("类别: Hardware\n", encoding="utf-8")
            category, raw, sub, source = ctf_meta.load_category_meta(project, ctf_learn.read_text)
            self.assertEqual(category, "forensics")
            self.assertEqual(raw, "hardware")
            self.assertEqual(sub, "hardware")
            self.assertEqual(source, "challenge.txt")

    def test_retry_after_seconds_parse(self):
        payload = {
            "response": {
                "data": {
                    "status": "ratelimited",
                    "message": "Try again in 13 seconds.",
                }
            }
        }
        self.assertEqual(ctf_pipeline_submit_gate.parse_retry_after_seconds(payload), 13)

    def test_recent_submission_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "submissions.jsonl"
            rec = {
                "ts": time.time(),
                "challenge_id": 37,
                "flag": "demo{x}",
                "http_status": 200,
                "response": {"data": {"status": "incorrect"}},
            }
            log_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
            self.assertTrue(
                ctf_pipeline_submit_gate.was_recently_submitted(
                    str(log_path), 37, "demo{x}", 300
                )
            )

    def test_parse_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "candidates.json"
            p.write_text(
                json.dumps(
                    [{"flag": "demo{a}", "score": 0.9}, "demo{b}"],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rows = ctf_submit_candidates.parse_candidates(p)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["flag"], "demo{a}")

    def test_leet_hint_penalty(self):
        penalty, leet_text = ctf_submit_candidates.leet_hint_penalty(
            "demo{dr4w_m3_just_d3c0d3_th3_k3y}"
        )
        self.assertGreaterEqual(penalty, 0.2)
        self.assertIn("draw", leet_text)

    def test_submit_candidates_strategy_defaults(self):
        strat = ctf_submit_candidates.resolve_strategy("balanced", None, None, None)
        self.assertEqual(strat["max_submissions"], 5)
        self.assertAlmostEqual(strat["high_threshold"], 0.78, places=2)
        self.assertAlmostEqual(strat["mid_threshold"], 0.62, places=2)

    def test_ctfd_remote_readiness_two_hit_rule(self):
        ch = {
            "needs_container": True,
            "instance_url": "",
            "connection_info": "",
            "attachments": [],
            "provider_probes": [{"start_http": 404, "poll_http": 404}],
        }
        ready, gate_status, reason, has_target, probe_ok = ctfd_pipeline.evaluate_remote_readiness(ch)
        self.assertFalse(ready)
        self.assertEqual(gate_status, "no_target")
        self.assertFalse(has_target)
        self.assertFalse(probe_ok)
        self.assertIn("no remote target", reason)

    def test_health_report_resolve_submissions_path(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            event_dir = td_path / "event"
            event_dir.mkdir()
            out = ctf_health_report.resolve_submissions_path(None, str(event_dir))
            self.assertEqual(out, (event_dir / "submissions.jsonl").resolve())

    def test_path_sanity_flags_control_chars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "Usage: dirname [OPTION] NAME...\nfoo"
            bad.mkdir(parents=True)
            problems = ctf_path_sanity.scan_tree(root, max_depth=2)
            self.assertTrue(problems)

    def test_case_state_classify_attempt_failure(self):
        row = {"status": "failed", "note": ["timeout while probing"]}
        self.assertEqual(ctf_case_state.classify_attempt_failure(row), "timeout")

    def test_lane_select_fast_for_small_project(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / "challenge.txt").write_text("simple note\n", encoding="utf-8")
            rec = ctf_lane_select.classify_lane(project)
            self.assertEqual(rec["lane"], "fast")

    def test_index_modules_import(self):
        self.assertTrue(hasattr(ctf_index_build, "main"))
        self.assertTrue(hasattr(ctf_index_query, "main"))


if __name__ == "__main__":
    unittest.main()
