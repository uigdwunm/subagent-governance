#!/usr/bin/env python3

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_concurrency", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_spawns_keep_all_state_records(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["SUBAGENT_GOVERNANCE_DATA"] = directory
            processes = []
            for index in range(32):
                payload = {
                    "session_id": "concurrent-session",
                    "turn_id": f"turn-{index}",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": f"tool-{index}",
                    "tool_input": {
                        "message": f"只读检查并总结第 {index} 个并发任务，不修改文件",
                        "task_name": f"task_{index}",
                        "fork_turns": "none",
                    },
                }
                processes.append(
                    (
                        subprocess.Popen(
                            [sys.executable, str(SCRIPT)],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env=environment,
                        ),
                        json.dumps(payload, ensure_ascii=False),
                    )
                )

            outputs = []
            for process, payload_text in processes:
                stdout, stderr = process.communicate(input=payload_text, timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))

            task_ids = {
                governance.TASK_ID_RE.search(item["hookSpecificOutput"]["updatedInput"]["message"]).group(1)
                for item in outputs
            }
            self.assertEqual(len(task_ids), 32)
            state = governance.StateStore(Path(directory)).read("concurrent-session")
            self.assertEqual(set(state["tasks"]), task_ids)


if __name__ == "__main__":
    unittest.main()
