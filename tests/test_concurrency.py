#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.governance_hook import handle_hook
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore
from tests.support import ROOT

SCRIPT = ROOT / "scripts/subagent_governance.py"


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_prepare_keeps_all_tasks_in_one_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, "SUBAGENT_GOVERNANCE_DATA": directory}
            processes = []
            for index in range(16):
                contract = {
                    "objective": f"Concurrent task {index}",
                    "scope": ["tests"],
                    "completion": ["prepared"],
                }
                process = subprocess.Popen(
                    [sys.executable, str(SCRIPT), "--prepare-dispatch", "--session", "parallel", "--data-root", directory],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, env=environment,
                )
                processes.append((process, json.dumps(contract)))
            outputs = []
            for process, payload in processes:
                stdout, stderr = process.communicate(payload, timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))
            state = StateStore(Path(directory) / "sessions").read("parallel")
            self.assertEqual(set(state["tasks"]), {item["task_id"] for item in outputs})
            self.assertEqual(len({item["task_ref"] for item in outputs}), 16)
            self.assertFalse((Path(directory) / "prepared").exists())

    def test_competing_confirms_preserve_first_bind_and_reconcile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = StateStore(root / "sessions")
            prepared = prepare_dispatch(
                {"objective": "Race exact confirms", "scope": ["tests"], "completion": ["one bind"]},
                "confirm-race", state_store=store,
                task_id_factory=lambda: "confirm-race-task", now=100,
            )
            result = handle_hook(
                {
                    "session_id": "confirm-race", "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent", "tool_use_id": "race-call",
                    "tool_input": prepared["spawn_args"], "now": 101,
                }, store,
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
            processes = []
            for target in ("/root/a", "/root/b"):
                payload = json.dumps(
                    {"task_id": prepared["task_id"], "task_ref": prepared["task_ref"], "target": target}
                )
                process = subprocess.Popen(
                    [sys.executable, str(SCRIPT), "--confirm-dispatch", "--session", "confirm-race", "--data-root", directory],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                processes.append((process, payload))
            outcomes = []
            for process, payload in processes:
                stdout, stderr = process.communicate(payload, timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                outcomes.append(json.loads(stdout)["result"])
            self.assertEqual(sorted(outcomes), ["bound", "reconcile"])
            task = store.read("confirm-race")["tasks"][prepared["task_id"]]
            self.assertEqual(task["phase"], "reconcile")
            self.assertIn(task["target"], {"/root/a", "/root/b"})
            self.assertEqual(task["reconcile"]["code"], "dispatch_target_conflict")


if __name__ == "__main__":
    unittest.main()
