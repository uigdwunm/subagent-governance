"""All ways to close a task obey the same ledger retention boundary."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import governance_lifecycle as lifecycle
from scripts import governance_state_store as storage
from scripts.governance_errors import DispatchPreparationError
from scripts.governance_dispatch import claim_spawn, confirm_dispatch, record_dispatch_result
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore


class DispatchRetentionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = StateStore(Path(directory.name) / 'sessions')
        self.tick = 100

    def prepare(self, **overrides):
        self.tick += 1
        return prepare_dispatch({'objective': 'Retention check', 'scope': ['fixture'],
                                 'completion': ['retain correct records'], **overrides},
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

    def test_large_closed_history_allows_further_dispatch_before_count_limit(self):
        closed = {}
        evicted = []
        for _ in range(55):
            prepared = self.prepare(scope=[f'{index}: ' + '界' * 320 for index in range(64)])
            removed = prepared.get('pruned_task_ids', [])
            self.assertEqual(removed, list(closed)[:len(removed)])
            for task_id in removed:
                evicted.append(task_id)
                del closed[task_id]
            tasks = self.store.read('retention')['tasks']
            self.assertEqual({key: value for key, value in tasks.items()
                              if key != prepared['task_id']}, closed)
            self.assertLessEqual(len(self.store._encoded_state(self.store.read('retention'))),
                                 storage.NEW_TASK_SOFT_LIMIT_BYTES)
            self.failed(prepared)
            closed[prepared['task_id']] = self.store.read('retention')['tasks'][prepared['task_id']]
        self.assertTrue(evicted, 'Byte pressure must prune closed records before 64 tasks')
        self.assertLess(len(closed), 64)

    def test_capacity_rejection_preserves_open_tasks_and_closed_history_on_disk(self):
        closed = self.prepare()
        self.failed(closed)
        self.prepare(context={'summary': 'independent open work'})
        path, _ = self.store._paths('retention')
        before = path.read_bytes()
        # Even removing all closed records cannot fit the new prepared record.
        with patch.object(storage, 'NEW_TASK_SOFT_LIMIT_BYTES', len(before)):
            with self.assertRaises(DispatchPreparationError):
                self.prepare(context={'summary': 'large new work ' * 100})
        self.assertEqual(path.read_bytes(), before)

    def test_capacity_pruning_preserves_open_task_and_whole_surviving_records(self):
        for _ in range(3):
            self.failed(self.prepare())
        opened = self.prepare()
        before = self.store.read('retention')
        with patch.object(storage, 'NEW_TASK_SOFT_LIMIT_BYTES',
                          len(self.store._encoded_state(before))):
            prepared = self.prepare()
        removed = prepared['pruned_task_ids']
        self.assertTrue(removed)
        self.assertNotIn(opened['task_id'], removed)
        after = self.store.read('retention')['tasks']
        self.assertEqual({key: value for key, value in after.items()
                          if key != prepared['task_id']},
                         {key: value for key, value in before['tasks'].items()
                          if key not in removed})

    def test_capacity_pruning_ties_use_created_at_then_task_id(self):
        state = {'tasks': {
            'b': {'phase': 'closed', 'closed_at': 10, 'created_at': 2},
            'a': {'phase': 'closed', 'closed_at': 10, 'created_at': 2},
            'c': {'phase': 'closed', 'closed_at': 10, 'created_at': 1},
            'open': {'phase': 'bound'},
        }}
        removed = lifecycle.prune_closed_tasks(
            state, exceeds_capacity=lambda: len(state['tasks']) > 2,
        )
        self.assertEqual(removed, ('c', 'a'))
        self.assertEqual(set(state['tasks']), {'b', 'open'})

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
