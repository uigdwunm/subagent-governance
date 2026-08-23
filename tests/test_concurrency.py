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
    def test_parallel_dispatch_preparation_keeps_all_state_and_prepared_records(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["SUBAGENT_GOVERNANCE_DATA"] = directory
            processes = []
            for index in range(32):
                contract = {
                    "semantic_name": f"task_{index}",
                    "requested_mode": "light",
                    "task_features": {
                        "risk": "low",
                        "read_only": True,
                        "writes_files": False,
                        "destructive": False,
                        "production": False,
                        "concurrent_write": False,
                    },
                    "objective": f"只读检查并总结第 {index} 个并发任务",
                    "background": "并发 PreparedContract 和 StateStore 验证。",
                    "work_scope": ["当前测试目录"],
                    "forbidden_scope": ["不得修改业务文件"],
                    "completion_conditions": ["返回检查结果"],
                    "evidence_requirements": ["记录生成结果"],
                    "relevant_files": [],
                    "context_manifest": {"mode": "none"},
                    "current_state": None,
                    "model": None,
                    "reasoning_effort": None,
                    "context_strategy": "isolated",
                    "context_turns": None,
                    "context_reason": None,
                }
                processes.append(
                    (
                        subprocess.Popen(
                            [
                                sys.executable,
                                str(SCRIPT),
                                "--prepare-dispatch",
                                "--session",
                                "concurrent-session",
                                "--data-root",
                                directory,
                            ],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env=environment,
                        ),
                        json.dumps(contract, ensure_ascii=False),
                    )
                )

            outputs = []
            for process, payload_text in processes:
                stdout, stderr = process.communicate(input=payload_text, timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))

            task_ids = {item["task_id"] for item in outputs}
            task_refs = {item["task_ref"] for item in outputs}
            self.assertEqual(len(task_ids), 32)
            self.assertEqual(len(task_refs), 32)
            state = governance.StateStore(Path(directory) / "sessions").read("concurrent-session")
            self.assertEqual(set(state["tasks"]), task_ids)
            prepared = governance.PreparedContractStore(Path(directory) / "prepared")
            self.assertEqual(prepared.refs("concurrent-session"), task_refs)

    def test_parallel_compare_and_set_allows_one_commit_and_one_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = governance.StateStore(Path(directory))
            store.update("cas-session", lambda state: state.update({"marker": 0}))
            worker = f"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('subagent_governance_cas_worker', {str(SCRIPT)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
store = module.StateStore(Path(sys.argv[1]))
try:
    store.compare_and_set(
        'cas-session',
        lambda state: state.get('marker') == 0,
        lambda state: state.update({{'marker': 1}}),
    )
except module.StateConflictError:
    print('conflict')
else:
    print('committed')
"""
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", worker, directory],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            outcomes = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                outcomes.append(stdout.strip())

            self.assertEqual(sorted(outcomes), ["committed", "conflict"])
            self.assertEqual(store.read("cas-session")["marker"], 1)


if __name__ == "__main__":
    unittest.main()
