#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import governance_semantics as semantics
from scripts.governance_contracts import contract_from_input
from scripts.governance_errors import DispatchPreparationError
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class ContextContractV2Tests(unittest.TestCase):
    @staticmethod
    def verified_contract(workspace: Path, baseline: dict, required_paths: list[dict]) -> dict:
        return {
            "profile": "strict",
            "objective": "Verify exact material",
            "scope": ["verified context"],
            "forbidden_scope": ["external systems"],
            "completion": ["prepared"],
            "evidence": ["content identity"],
            "context": {
                "verified": {
                    "mode": "declared",
                    "workspace_root": str(workspace),
                    "baseline": baseline,
                    "required_paths": required_paths,
                }
            },
        }

    def test_ordinary_paths_are_hints_and_do_not_read_files(self):
        contract = contract_from_input(
            {
                "objective": "Use path hints",
                "scope": ["tests"],
                "completion": ["prepared"],
                "context": {"paths": ["missing/file.py"]},
            }
        )
        self.assertEqual(contract.context["paths"], ["missing/file.py"])
        self.assertIsNone(contract.context["verified"])

    def test_explicit_verified_working_tree_is_checked_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "input.txt").write_text("stable", encoding="utf-8")
            state = StateStore(Path(directory) / "state")
            prepared = prepare_dispatch(
                {
                    "profile": "strict",
                    "objective": "Verify exact material",
                    "scope": ["input.txt"],
                    "forbidden_scope": ["external systems"],
                    "completion": ["prepared"],
                    "evidence": ["sha256"],
                    "context": {
                        "verified": {
                            "mode": "declared",
                            "workspace_root": str(workspace),
                            "baseline": {"kind": "working_tree", "revision": None},
                            "required_paths": [{"path": "input.txt", "type": "file"}],
                        }
                    },
                },
                "verified-session",
                state_store=state,
                task_id_factory=lambda: "verified-task",
                now=10,
            )
            verification = state.read("verified-session")["tasks"][prepared["task_id"]]["prepared"]["context_verification"]
            self.assertEqual(verification["required_paths"][0]["sha256"], "f379ccb92b9116442dc65bdc35648a85d3786b34779db7f704a901fa07b00cb6")

    def test_schema_and_runtime_reject_working_tree_directory_before_state_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "docs").mkdir()
            manifest = {
                "mode": "declared",
                "workspace_root": str(workspace),
                "baseline": {"kind": "working_tree", "revision": None},
                "required_paths": [{"path": "docs", "type": "directory"}],
            }
            schema_errors = validate_instance(
                manifest,
                semantics.SEMANTIC_DEFINITIONS["verified_context"],
                root_schema=semantics.MACHINE_SEMANTICS,
            )
            self.assertTrue(schema_errors)

            state = StateStore(Path(directory) / "state")
            contract = self.verified_contract(
                workspace,
                {"kind": "working_tree", "revision": None},
                [{"path": "docs", "type": "directory"}],
            )
            with self.assertRaisesRegex(
                DispatchPreparationError, "working_tree.*directory"
            ):
                prepare_dispatch(contract, "directory-session", state_store=state)
            self.assertEqual(list(state.root.glob("*.json")), [])

    def test_git_commit_directory_uses_tree_object_and_rejects_workspace_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "docs").mkdir()
            (workspace / "docs" / "input.txt").write_text("stable", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "docs/input.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-q", "-m", "fixture"],
                check=True,
            )
            revision = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            contract = self.verified_contract(
                workspace,
                {"kind": "git_commit", "revision": revision},
                [{"path": "docs", "type": "directory"}],
            )
            state = StateStore(Path(directory) / "state")
            prepared = prepare_dispatch(
                contract,
                "git-directory-session",
                state_store=state,
                task_id_factory=lambda: "git-directory-task",
                now=10,
            )
            object_id = prepared["context_verification"]["required_paths"][0][
                "object_id"
            ]
            expected = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", f"{revision}:docs"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(object_id, expected)

            (workspace / "docs" / "input.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(
                DispatchPreparationError, "工作区内容与 Git baseline 不一致"
            ):
                prepare_dispatch(
                    contract,
                    "dirty-directory-session",
                    state_store=state,
                )


if __name__ == "__main__":
    unittest.main()
