import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import governance_semantics as semantics
from tests.support import load_governance

governance = load_governance("three_plane")


class ThreePlaneStateModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = governance.StateStore(Path(self.temporary.name) / "sessions")

    @staticmethod
    def contract():
        return governance.TaskContract(
            semantic_name="three_plane",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features={
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            objective="验证当前三平面状态模型",
            background="current state model test",
            work_scope=["state"],
            forbidden_scope=[],
            completion_conditions=["planes validate"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            context_manifest={"mode": "none"},
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )

    def current_state(self, session_id="three-plane"):
        state = governance.StateStore._empty_state(session_id)
        state["tasks"]["three-plane-task"] = governance._initial_task_record(
            1,
            "0123456789ab",
            "sg_standard_three_plane_t_0123456789ab",
            self.contract(),
            100,
        )
        return state

    def write_state(self, state, session_id="three-plane"):
        path, _lock = self.store._paths(session_id)
        path.write_text(json.dumps(state), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_schema_and_runtime_define_same_three_planes(self):
        expected = {
            "dispatch_record": semantics.REQUIRED_DISPATCH_RECORD_FIELDS,
            "observation_record": semantics.REQUIRED_OBSERVATION_RECORD_FIELDS,
            "closure_record": semantics.REQUIRED_CLOSURE_RECORD_FIELDS,
        }
        for name, runtime_fields in expected.items():
            active_properties = {
                field
                for field, definition in governance.SEMANTIC_DEFINITIONS[name][
                    "properties"
                ].items()
                if definition is not False
            }
            self.assertEqual(active_properties, set(runtime_fields))

    def test_current_state_is_returned_without_normalization(self):
        state = self.current_state()
        state["future_extension"] = {"opaque": True}

        loaded = governance._require_current_state_format(state)

        self.assertIs(loaded, state)
        self.assertEqual(loaded["future_extension"], {"opaque": True})

    def test_missing_version_is_rejected_without_rewrite(self):
        state = self.current_state()
        state.pop("state_format_version")
        path = self.write_state(state)
        before = path.read_bytes()

        with self.assertRaisesRegex(
            governance.StateValidationError, "unsupported_state_version"
        ):
            self.store.read("three-plane")

        self.assertEqual(path.read_bytes(), before)

    def test_older_versions_are_rejected_without_rewrite(self):
        for version in (1, 2, 3, 4):
            with self.subTest(version=version):
                state = self.current_state(f"version-{version}")
                state["state_format_version"] = version
                path = self.write_state(state, f"version-{version}")
                before = path.read_bytes()

                with self.assertRaisesRegex(
                    governance.StateValidationError,
                    rf"检测到 {version}.*仅支持 {governance.STATE_FORMAT_VERSION}",
                ):
                    self.store.read(f"version-{version}")

                self.assertEqual(path.read_bytes(), before)

    def test_newer_version_is_rejected_without_rewrite(self):
        state = self.current_state()
        state["state_format_version"] = governance.STATE_FORMAT_VERSION + 1
        path = self.write_state(state)
        before = path.read_bytes()

        with self.assertRaisesRegex(
            governance.StateValidationError, "unsupported_state_version"
        ):
            self.store.update("three-plane", lambda current: current.clear())

        self.assertEqual(path.read_bytes(), before)

    def test_current_managed_execution_requires_all_planes(self):
        for plane in ("dispatch_record", "observation_record", "closure_record"):
            with self.subTest(plane=plane):
                state = self.current_state()
                del state["tasks"]["three-plane-task"]["executions"]["1"][plane]

                with self.assertRaisesRegex(
                    governance.StateValidationError, "canonical execution 缺少字段"
                ):
                    governance._require_current_state_format(state)

    def test_current_planes_reject_unknown_fields(self):
        state = self.current_state()
        execution = state["tasks"]["three-plane-task"]["executions"]["1"]
        execution["dispatch_record"]["old_field"] = True

        with self.assertRaisesRegex(
            governance.StateValidationError, "包含未知字段 old_field"
        ):
            governance._require_current_state_format(state)

    def test_storage_rejects_callback_that_introduces_noncurrent_shape(self):
        self.store.update(
            "three-plane",
            lambda state: state["tasks"].update(
                {"three-plane-task": self.current_state()["tasks"]["three-plane-task"]}
            ),
        )
        path, _lock = self.store._paths("three-plane")
        before = path.read_bytes()

        def invalidate(state):
            del state["tasks"]["three-plane-task"]["executions"]["1"][
                "observation_record"
            ]

        with self.assertRaises(governance.StateValidationError):
            self.store.update("three-plane", invalidate)

        self.assertEqual(path.read_bytes(), before)

    def test_current_state_write_does_not_mutate_callback_value(self):
        captured = {}

        def add_current(state):
            task = copy.deepcopy(self.current_state()["tasks"]["three-plane-task"])
            state["tasks"]["three-plane-task"] = task
            captured["task"] = task

        self.store.update("three-plane", add_current)

        self.assertEqual(
            captured["task"],
            self.store.read("three-plane")["tasks"]["three-plane-task"],
        )


if __name__ == "__main__":
    unittest.main()
