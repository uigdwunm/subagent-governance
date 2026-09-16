#!/usr/bin/env python3

import json
import multiprocessing
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO, StringIO
from multiprocessing.connection import wait
from pathlib import Path
from threading import Barrier
from time import monotonic
from unittest.mock import patch

from scripts.governance_hook import handle_hook
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore


def _contending_cli(arguments, payload, connection):
    """Run the real CLI in a fresh interpreter, observing its first lock attempt."""
    from scripts import governance_state_store as state_store
    from scripts.governance_cli import main

    original_lock = state_store.exclusive_file_lock
    first_attempt = True

    @contextmanager
    def observed_lock(handle):
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            connection.send(("attempting",))
        with original_lock(handle):
            # This must not happen while the parent owns the Session lock.
            connection.send(("acquired",))
            yield

    output, errors = StringIO(), StringIO()
    try:
        with patch.object(state_store, "exclusive_file_lock", observed_lock):
            code = main(arguments, stdin=BytesIO(json.dumps(payload).encode()),
                        stdout=output, stderr=errors)
        connection.send(("result", code, output.getvalue(), errors.getvalue()))
    finally:
        connection.close()


class ConcurrencyTests(unittest.TestCase):
    def _run_contending_cli(self, directory, session, operation, payloads):
        context = multiprocessing.get_context("spawn")
        store = StateStore(Path(directory) / "sessions")
        processes, connections = [], []
        deadline = monotonic() + 30

        def receive(connection):
            self.assertTrue(connection.poll(max(0, deadline - monotonic())),
                            "child timed out before reporting its lock/result")
            return connection.recv()

        try:
            with store._lock(session):
                for payload in payloads:
                    parent, child = context.Pipe(duplex=False)
                    connections.append(parent)
                    arguments = [*operation, "--session", session, "--data-root", directory]
                    process = context.Process(target=_contending_cli,
                                              args=(arguments, payload, child))
                    try:
                        process.start()
                    finally:
                        child.close()
                    processes.append(process)
                for connection in connections:
                    self.assertEqual(receive(connection), ("attempting",))
                # All children have input and reached the lock boundary. None may
                # enter while another process owns the same Session lock.
                self.assertEqual(wait(connections, timeout=0.3), [],
                                 "a child bypassed the held Session lock")
            outputs = []
            for connection, process in zip(connections, processes):
                message = receive(connection)
                while message[0] == "acquired":
                    message = receive(connection)
                self.assertEqual(message[0], "result")
                _, code, stdout, stderr = message
                self.assertEqual(code, 0, stderr)
                outputs.append(json.loads(stdout))
                process.join(timeout=max(0, deadline - monotonic()))
                self.assertEqual(process.exitcode, 0)
            return outputs
        finally:
            # Failure and timeout must not leave writers alive past temp cleanup.
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                process.close()
            for connection in connections:
                connection.close()

    def test_concurrent_unknown_categories_preserve_all_first_receipts(self):
        from scripts import governance_lifecycle as lifecycle
        from scripts.governance_dispatch import confirm_dispatch

        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "sessions")
            session = "unknown-race"
            prepared = prepare_dispatch(
                {"objective": "Concurrent unknown receipts", "scope": ["tests"], "completion": ["all receipts retained"]},
                session, native_interface="fork_context", state_store=store, now=100,
            )
            handle_hook({"session_id": session, "hook_event_name": "PreToolUse",
                         "tool_name": "spawn_agent", "tool_use_id": "unknown-call",
                         "tool_input": prepared["spawn_args"], "now": 101}, store)
            identity = {"task_id": prepared["task_id"], "task_ref": prepared["task_ref"], "target": "/root/unknown-race"}
            confirm_dispatch(session, identity, state_store=store, now=102)
            barrier = Barrier(3)

            def record(operation, field):
                barrier.wait(timeout=5)
                return operation(session, {**identity, field: "unknown"}, state_store=store, now=103)

            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(record, operation, field) for operation, field in (
                    (lifecycle.record_call_result, "result"),
                    (lifecycle.record_interrupt_result, "result"),
                    (lifecycle.record_platform_observation, "status"),
                )]
                for future in futures:
                    self.assertEqual(future.result(timeout=10)["result"], "unknown_recorded")
            task = store.read(session)["tasks"][prepared["task_id"]]
            self.assertEqual(task["phase"], "bound")
            self.assertEqual(task["unknown_facts"], {code: {"observed_at": 103} for code in (
                "delivery_unknown", "interrupt_unknown", "platform_observation_unknown",
            )})

    def test_parallel_prepare_keeps_all_tasks_in_one_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = self._run_contending_cli(
                directory, "parallel", ["--prepare-dispatch", "--native-interface", "fork_context"],
                [{"objective": f"Concurrent task {index}", "scope": ["tests"],
                  "completion": ["prepared"]} for index in range(16)],
            )
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
                "confirm-race", native_interface="fork_context", state_store=store,
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
            outputs = self._run_contending_cli(
                directory, "confirm-race", ["--confirm-dispatch"],
                [{"task_id": prepared["task_id"], "task_ref": prepared["task_ref"], "target": target}
                 for target in ("/root/a", "/root/b")],
            )
            outcomes = [output["result"] for output in outputs]
            self.assertEqual(sorted(outcomes), ["bound", "reconcile"])
            task = store.read("confirm-race")["tasks"][prepared["task_id"]]
            self.assertEqual(task["phase"], "reconcile")
            winner = ("/root/a", "/root/b")[outcomes.index("bound")]
            self.assertEqual(task["target"], winner)
            self.assertEqual(task["reconcile"]["code"], "dispatch_target_conflict")


if __name__ == "__main__":
    unittest.main()
