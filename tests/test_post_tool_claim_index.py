import tempfile
import time
import unittest
from pathlib import Path

from scripts import governance_post_index as post_index
from scripts import governance_semantics as semantics
from scripts import governance_lifecycle as lifecycle
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class ClaimedPostIndexTests(unittest.TestCase):
    def test_exact_lookup_is_bounded_current_schema_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            index = post_index.ClaimedPostIndex(Path(directory) / "state-v8" / "claimed-post-tool-ids")
            record = {
                "index_format_version": post_index.INDEX_FORMAT_VERSION,
                "session_id": "index-session", "tool_use_id": "claimed-id",
                "task_id": "index-task", "attempt": 2, "task_ref": "0123456789ab",
                "operation_type": "business_resume", "claimed_at": 100,
                "expires_at": 100 + post_index.INDEX_TTL_SECONDS,
            }
            self.assertEqual(
                validate_instance(
                    record, semantics.MACHINE_SEMANTICS["$defs"]["claimed_post_index_record"],
                    root_schema=semantics.MACHINE_SEMANTICS,
                ), [],
            )
            index.record_claim(record, now=100)
            self.assertEqual(index.lookup("index-session", "claimed-id", now=101), record)
            self.assertIsNone(index.lookup("index-session", "other-id", now=101))
            stored = next(index.root.glob("*.json")).read_text(encoding="utf-8")
            self.assertLess(len(stored.encode("utf-8")), 4096)
            self.assertNotIn("message", stored)
            self.assertNotIn("response", stored)
            self.assertIsNone(index.lookup("index-session", "claimed-id", now=record["expires_at"] + 1))
            self.assertEqual(index.cleanup_expired(now=record["expires_at"] + 1), 1)
            self.assertEqual(list(index.root.glob("*.json")), [])

    def test_index_record_rejects_unknown_or_unsafe_fields(self):
        record = {
            "index_format_version": post_index.INDEX_FORMAT_VERSION,
            "session_id": "index-session", "tool_use_id": "claimed-id",
            "task_id": "index-task", "attempt": 2, "task_ref": "0123456789ab",
            "operation_type": "business_resume", "claimed_at": 100,
            "expires_at": 101,
        }
        for field, value in (("message", "secret"), ("expires_at", 99)):
            with self.subTest(field=field):
                invalid = {**record, field: value}
                schema_errors = validate_instance(
                    invalid, semantics.MACHINE_SEMANTICS["$defs"]["claimed_post_index_record"],
                    root_schema=semantics.MACHINE_SEMANTICS,
                )
                if field == "message":
                    self.assertTrue(schema_errors)
                else:
                    self.assertEqual(schema_errors, [])
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(ValueError):
                        post_index.ClaimedPostIndex(Path(directory) / "claimed").record_claim(invalid, now=100)

    def test_expired_canonical_claim_is_not_republished_by_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state-v8")
            session_id = "expired-rebuild"
            now = int(time.time())
            state = StateStore._empty_state(session_id)
            task_ref = "0123456789ab"
            state["tasks"]["index-task"] = {
                "managed": True,
                "work_item": {"current_attempt": 1, "lifecycle": "open"},
                "executions": {
                    "1": {
                        "task_ref": task_ref, "task_name": "sg_standard_index_task_t_0123456789ab",
                        "resolved_mode": "standard", "contract_summary": {"objective": "index", "model": None},
                        "contract_digest": "a" * 64, "spawn_retry_count": 0, "recovery_count": 0,
                        "updated_at": now, "dispatch_record": {"dispatch_state": "acknowledged", "tool_use_id": "spawn", "dispatch_target": "/root/index"},
                        "observation_record": {"source": None, "observed_state": "not_observed", "observed_at": None, "terminal_status": None},
                        "closure_record": {"reason": None, "closed_at": None, "parent_action": None},
                        "pending_action": {
                            "target": "/root/index", "attempt": 1, "task_ref": task_ref,
                            "operation_type": "normal_message", "phase": "claimed",
                            "created_at": now - post_index.INDEX_TTL_SECONDS - 2,
                            "tool_use_id": "expired", "claimed_at": now - post_index.INDEX_TTL_SECONDS - 1,
                        },
                    }
                },
            }
            state["agents"]["/root/index"] = {"task_id": "index-task", "attempt": 1}
            store.update(session_id, lambda current: current.update(state))
            self.assertEqual(lifecycle.rebuild_claimed_post_index(session_id, store, now=now), 0)
            self.assertIsNone(
                post_index.ClaimedPostIndex(post_index.index_root_for_store(store)).lookup(
                    session_id, "expired", now=now
                )
            )


if __name__ == "__main__":
    unittest.main()
