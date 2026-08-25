#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from scripts.governance_contracts import contract_from_input
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore


class ContextContractV2Tests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
