"""All ways to close a task obey the same ledger retention boundary."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import governance_lifecycle as lifecycle
from scripts.governance_dispatch import claim_spawn, confirm_dispatch, record_dispatch_result
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore


class DispatchRetentionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = StateStore(Path(directory.name) / 'sessions')
        self.tick = 100

    def prepare(self):
        self.tick += 1
        return prepare_dispatch({'objective': 'Retention check', 'scope': ['fixture'],
                                 'completion': ['retain correct records']},
                                'retention', native_interface='collaboration_turns',
                                state_store=self.store, now=self.tick)

    def failed(self, prepared):
        identity = prepared['operation_inputs']['--confirm-dispatch']
        result = record_dispatch_result('retention', {**identity, 'result': 'failed'},
                                        state_store=self.store, now=self.tick)
        self.assertEqual(result, {'result': 'closed', **identity})

    def test_failed_dispatch_immediately_retains_only_latest_64_closed(self):
        identities = []
        for _ in range(65):
            prepared = self.prepare()
            identities.append(prepared['task_id'])
            self.failed(prepared)
        tasks = self.store.read('retention')['tasks']
        self.assertEqual(set(tasks), set(identities[-64:]))
        self.assertTrue(all(t['phase'] == 'closed' for t in tasks.values()))

    def test_mixed_close_paths_preserve_open_tasks_and_remaining_facts(self):
        protected = {}
        for phase in ('prepared', 'claimed', 'bound', 'terminal', 'reconcile'):
            prepared = self.prepare()
            identity = prepared['operation_inputs']['--confirm-dispatch']
            if phase in ('claimed', 'bound', 'terminal'):
                claim_spawn('retention', prepared['task_ref'], 'call-' + phase,
                            prepared['spawn_args'], state_store=self.store, now=self.tick)
            if phase in ('bound', 'terminal'):
                confirm_dispatch('retention', {**identity, 'target': '/root/' + phase},
                                 state_store=self.store, now=self.tick)
            if phase == 'terminal':
                lifecycle.record_terminal_notification(
                    'retention', {**identity, 'sender': '/root/terminal', 'status': 'completed'},
                    state_store=self.store, now=self.tick)
            if phase == 'reconcile':
                record_dispatch_result('retention', {**identity, 'result': 'unknown'},
                                       state_store=self.store, now=self.tick)
            task = self.store.read('retention')['tasks'][prepared['task_id']]
            self.assertEqual(task['phase'], phase)
            protected[prepared['task_id']] = task
        with patch.object(lifecycle, 'CLOSED_TASK_RETENTION', 2):
            closed = []
            for method in ('failed', 'parent', 'failed', 'parent'):
                prepared = self.prepare()
                identity = prepared['operation_inputs']['--confirm-dispatch']
                if method == 'failed':
                    self.failed(prepared)
                else:
                    lifecycle.close_task('retention', {**identity, 'reason': 'cancelled'},
                                         state_store=self.store, now=self.tick)
                tasks = self.store.read('retention')['tasks']
                closed.append((prepared['task_id'], tasks[prepared['task_id']]))
                expected = {**protected, **dict(closed[-2:])}
                self.assertEqual(tasks, expected)
