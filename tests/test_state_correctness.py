"""Regression coverage for identity ownership and monotonic lifecycle facts."""
import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from scripts import governance_dispatch as dispatch
from scripts import governance_lifecycle as lifecycle
from scripts import governance_protocol as protocol
from scripts import governance_semantics as semantics
from scripts.governance_errors import StateConflictError, StateValidationError
from scripts.governance_state import validate_current_state_format
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class StateCorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / 'sessions')
        self.session = 'correctness'

    def claim(self, name, session=None):
        session = session or self.session
        prepared = protocol.prepare_dispatch(
            {'objective': name, 'scope': ['tests'], 'completion': ['verified']},
            session, native_interface='fork_context', state_store=self.store,
            task_id_factory=lambda: name, now=100,
        )
        dispatch.claim_spawn(session, prepared['task_ref'], 'call-' + name,
                             prepared['spawn_args'], state_store=self.store, now=101)
        return {'task_id': name, 'task_ref': prepared['task_ref'], 'target': '/root/shared'}

    def confirm(self, identity, session=None, now=102):
        return dispatch.confirm_dispatch(session or self.session, identity,
                                         state_store=self.store, now=now)

    def task(self, identity):
        return self.store.read(self.session)['tasks'][identity['task_id']]

    def terminal(self, identity, source, status, now):
        request = {**identity, 'status': status}
        operation = lifecycle.record_platform_observation
        if source == 'notification':
            request['sender'] = request.pop('target')
            operation = lifecycle.record_terminal_notification
        return operation(self.session, request, state_store=self.store, now=now)

    def inactive(self, identity, now):
        return lifecycle.record_interrupt_result(
            self.session, {**identity, 'result': 'inactive'}, state_store=self.store, now=now)

    def close(self, identity):
        lifecycle.close_task(self.session, {k: v for k, v in
            {**identity, 'reason': 'accepted'}.items() if k != 'target'},
            state_store=self.store, now=110)

    def assert_valid(self):
        state = self.store.read(self.session)
        self.assertEqual(validate_current_state_format(state), [])
        self.assertEqual(validate_instance(state, semantics.MACHINE_SEMANTICS['$defs']['session_ledger'],
            root_schema=semantics.MACHINE_SEMANTICS), [])

    def test_target_ownership_across_phases(self):
        for phase in ('bound', 'terminal', 'reconcile', 'closed'):
            with self.subTest(phase=phase):
                self.session = phase
                owner = self.claim('owner')
                self.confirm(owner)
                if phase == 'terminal':
                    self.terminal(owner, 'platform', 'completed', 103)
                elif phase == 'reconcile':
                    self.confirm({**owner, 'target': '/root/wrong'}, now=103)
                elif phase == 'closed':
                    self.close(owner)
                before = self.task(owner)
                second = self.claim('second')
                result = self.confirm(second, now=112)
                self.assertEqual(self.task(owner), before)
                if phase == 'closed':
                    self.assertEqual(result['result'], 'bound')
                else:
                    self.assertEqual(result['result'], 'reconcile')
                    self.assertEqual(result['conflicting_task_id'], owner['task_id'])
                    self.assertNotIn('target', self.task(second))
                    self.assertEqual(self.task(second)['reconcile']['code'], 'dispatch_target_already_bound')
                self.assert_valid()

    def test_target_is_session_local_and_validation_rejects_duplicate(self):
        first = self.claim('first')
        self.confirm(first)
        other = self.claim('other', 'other-session')
        self.assertEqual(self.confirm(other, 'other-session')['result'], 'bound')
        state = self.store.read(self.session)
        duplicate = copy.deepcopy(state['tasks']['first'])
        duplicate['task_ref'] = 'abcdefabcdef'
        state['tasks']['duplicate'] = duplicate
        self.assertTrue(any('target' in str(issue) for issue in validate_current_state_format(state)))
        before = self.store.read(self.session)
        with self.assertRaises(StateValidationError):
            self.store.update(self.session, lambda ledger: ledger['tasks'].update(duplicate=duplicate))
        self.assertEqual(self.store.read(self.session), before)
        duplicate.update(phase='closed', close_reason='accepted', closed_at=103)
        self.assertEqual(validate_current_state_format(state), [])

    def test_concurrent_tasks_have_one_target_owner(self):
        identities = [self.claim(name) for name in ('a', 'b')]
        barrier = Barrier(2)
        def confirm(identity):
            barrier.wait(timeout=5)
            return self.confirm(identity)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm, identities))
        self.assertCountEqual([r['result'] for r in results], ['bound', 'reconcile'])
        tasks = self.store.read(self.session)['tasks'].values()
        self.assertEqual(sum('target' in task for task in tasks), 1)
        self.assert_valid()

    def test_inactive_refinement_both_sources_and_event_orders(self):
        for source in ('platform', 'notification'):
            for status in ('completed', 'stopped', 'interrupted'):
                for inactive_first in (True, False):
                    with self.subTest(source=source, status=status, inactive_first=inactive_first):
                        self.session = f'{source}-{status}-{inactive_first}'
                        identity = self.claim('task')
                        self.confirm(identity)
                        if inactive_first:
                            self.inactive(identity, 103)
                            self.terminal(identity, source, status, 104)
                        else:
                            self.terminal(identity, source, status, 103)
                            self.inactive(identity, 104)
                        before = self.task(identity)
                        self.assertEqual(before['phase'], 'terminal')
                        self.assertEqual(before['terminal_fact'], {'source': source, 'status': status,
                            'observed_at': 104 if inactive_first else 103})
                        self.assertEqual(before['interrupt_fact']['observed_at'], 103 if inactive_first else 104)
                        self.inactive(identity, 105)
                        self.terminal(identity, source, status, 106)
                        self.assertEqual(self.task(identity), before)
                        other_source = 'notification' if source == 'platform' else 'platform'
                        self.terminal(identity, other_source, status, 107)
                        self.assertEqual(self.task(identity)['terminal_fact'], before['terminal_fact'])
                        conflict = 'stopped' if status == 'completed' else 'completed'
                        self.assertEqual(self.terminal(identity, other_source, conflict, 108)['result'], 'reconcile')
                        self.assertEqual(self.task(identity)['terminal_fact'], before['terminal_fact'])
                        self.assert_valid()

    def test_confirm_replay_preserves_each_phase_and_closed_rejects_events(self):
        for phase in ('bound', 'terminal', 'closed', 'reconcile'):
            with self.subTest(phase=phase):
                self.session = 'replay-' + phase
                identity = self.claim('task')
                self.confirm(identity)
                if phase != 'bound':
                    self.terminal(identity, 'notification', 'completed', 103)
                if phase == 'closed':
                    self.close(identity)
                elif phase == 'reconcile':
                    self.terminal(identity, 'platform', 'stopped', 104)
                before = self.task(identity)
                result = self.confirm(identity, now=120)
                self.assertEqual(result['result'], {'closed': 'already_closed', 'reconcile': 'reconcile'}.get(phase, 'already_bound'))
                self.assertEqual(self.task(identity), before)
                if phase == 'closed':
                    for operation in (lambda: self.inactive(identity, 121),
                                      lambda: self.terminal(identity, 'platform', 'completed', 121),
                                      lambda: self.terminal(identity, 'notification', 'completed', 121)):
                        with self.assertRaises(StateConflictError):
                            operation()
                    for change in ({'task_ref': 'abcdefabcdef'}, {'target': '/root/wrong'}):
                        with self.assertRaises(StateConflictError):
                            self.confirm({**identity, **change}, now=122)
                    self.assertEqual(self.task(identity), before)
                self.assert_valid()

    def test_terminal_wrong_identity_preserves_first_facts(self):
        for change in ({'task_ref': 'abcdefabcdef'}, {'target': '/root/wrong'}):
            self.session = next(iter(change))
            identity = self.claim('task')
            self.confirm(identity)
            self.terminal(identity, 'platform', 'completed', 103)
            before = self.task(identity)
            self.assertEqual(self.confirm({**identity, **change}, now=104)['result'], 'reconcile')
            after = self.task(identity)
            for field in ('target', 'bound_at', 'terminal_fact'):
                self.assertEqual(after[field], before[field])
            self.assert_valid()

    def test_unbound_reconcile_and_closed_never_acquire_identity(self):
        identity = self.claim('unbound')
        self.confirm({**identity, 'task_ref': 'abcdefabcdef'})
        before = self.task(identity)
        self.assertNotIn('target', before)
        self.assertEqual(self.confirm(identity)['result'], 'reconcile')
        self.assertEqual(self.task(identity), before)
        other = self.claim('other')
        self.assertEqual(self.confirm(other)['result'], 'bound')
        self.close(identity)
        before = self.task(identity)
        with self.assertRaises(StateConflictError):
            self.confirm(identity)
        self.assertEqual(self.task(identity), before)

    def test_inactive_cannot_be_refined_by_nonterminal_observations(self):
        identity = self.claim('task')
        self.confirm(identity)
        self.inactive(identity, 103)
        before = self.task(identity)
        for status in ('running', 'error', 'unknown'):
            with self.assertRaises(StateConflictError):
                self.terminal(identity, 'platform', status, 104)
            self.assertEqual(self.task(identity), before)
        for source in ('platform', 'notification'):
            with self.assertRaises(ValueError):
                self.terminal(identity, source, 'failed', 104)
            self.assertEqual(self.task(identity), before)
