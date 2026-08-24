import tempfile
import unittest
from pathlib import Path

from scripts import governance_post_index as post_index
from scripts import governance_semantics as semantics
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
            index.record_claim(record)
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
                        post_index.ClaimedPostIndex(Path(directory) / "claimed").record_claim(invalid)


if __name__ == "__main__":
    unittest.main()
