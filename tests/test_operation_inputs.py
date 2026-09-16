"""Generated stdin objects exercised through the unchanged CLI contracts."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_cli, governance_dispatch, governance_lifecycle, governance_protocol
from scripts.governance_diagnostics import diagnose, status
from scripts.governance_errors import DispatchPreparationError, StateConflictError
from scripts.governance_hook import handle_hook
from scripts.governance_state_store import StateStore


class OperationInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = StateStore(self.root / 'sessions')
        self.session = 'operation-inputs-session'
        self.target = '/root/exact-target'
        self.prepared = governance_protocol.prepare_dispatch(
            {'objective': 'Verify generated inputs', 'scope': ['tests'], 'completion': ['verified']},
            self.session, native_interface='collaboration_turns', state_store=self.store,
        )
        self.identity = {key: self.prepared[key] for key in ('task_id', 'task_ref')}

    def claim(self):
        handle_hook({'hook_event_name': 'PreToolUse', 'session_id': self.session,
                     'tool_name': 'spawn_agent', 'tool_use_id': 'exact-call',
                     'tool_input': self.prepared['spawn_args']}, self.store)

    def bind(self):
        self.claim()
        return governance_dispatch.confirm_dispatch(
            self.session, {**self.identity, 'target': self.target}, state_store=self.store)

    def invoke(self, command, value, session=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = governance_cli.main(
            [command, '--session', session or self.session, '--data-root', str(self.root)],
            stdin=io.BytesIO(json.dumps(value).encode()), stdout=stdout, stderr=stderr,
        )
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()

    def detail(self):
        return status(self.session, self.root, **self.identity)['tasks'][0]

    def raw(self):
        return self.store._paths(self.session)[0].read_bytes()

    def test_normal_chain_uses_generated_inputs_and_never_persists_them(self):
        confirm = self.prepared['operation_inputs']['--confirm-dispatch']
        self.assertEqual(confirm, self.identity)
        self.claim()
        code, bound, error = self.invoke('--confirm-dispatch', {**confirm, 'target': self.target})
        self.assertEqual(code, 0, error)
        terminal = bound['operation_inputs']['--record-terminal-notification']
        self.assertEqual(terminal, {**self.identity, 'sender': self.target})
        code, ended, error = self.invoke('--record-terminal-notification',
                                         {**terminal, 'status': 'completed'})
        self.assertEqual(code, 0, error)
        self.assertEqual(set(ended['operation_inputs']), {'--close-task'})
        close = ended['operation_inputs']['--close-task']
        self.assertEqual(close, self.identity)
        code, closed, error = self.invoke('--close-task', {**close, 'reason': 'parent verified'})
        self.assertEqual(code, 0, error)
        self.assertEqual(closed['operation_inputs'], {})
        self.assertEqual(self.invoke('--close-task', {**close, 'reason': 'parent verified'})[1]
                         ['result'], 'already_closed')
        self.assertEqual(self.detail()['operation_inputs'], {})
        self.assertNotIn(b'operation_inputs', self.raw())

    def test_detail_is_exact_readonly_and_default_views_stay_light(self):
        self.assertEqual(self.detail()['operation_inputs'], self.prepared['operation_inputs'])
        self.claim()
        self.assertEqual(self.detail()['operation_inputs'], self.prepared['operation_inputs'])
        bound = governance_dispatch.confirm_dispatch(
            self.session, {**self.identity, 'target': self.target}, state_store=self.store)
        before = self.raw()
        with mock.patch.object(StateStore, 'update', side_effect=AssertionError('write')):
            self.assertEqual(self.detail()['operation_inputs'], bound['operation_inputs'])
            self.assertNotIn('operation_inputs', status(self.session, self.root)['tasks'][0])
            self.assertNotIn('operation_inputs', diagnose(self.session, self.root)['status']['tasks'][0])
        self.assertEqual(self.raw(), before)
        with self.assertRaises(ValueError):
            status(self.session, self.root, task_id=self.identity['task_id'])
        for session, identity in [('other-session', self.identity),
                                  (self.session, {**self.identity, 'task_ref': '0' * 8})]:
            with self.assertRaises((StateConflictError, ValueError)):
                status(session, self.root, **identity)
        self.assertFalse(self.store._paths('other-session')[0].exists())

    def test_unknown_replay_terminal_confirm_and_conflict_follow_actual_phase(self):
        bound = self.bind()
        observation = bound['operation_inputs']['--record-platform-observation']
        self.assertEqual(observation, {**self.identity, 'target': self.target})
        for expected in ('unknown_recorded', 'already_unknown'):
            code, observed, error = self.invoke('--record-platform-observation',
                                                {**observation, 'status': 'unknown'})
            self.assertEqual(code, 0, error)
            self.assertEqual(observed['result'], expected)
            self.assertEqual(observed['operation_inputs'], bound['operation_inputs'])
        self.invoke('--record-platform-observation', {**observation, 'status': 'completed'})
        replay = self.invoke('--confirm-dispatch', {**self.identity, 'target': self.target})[1]
        self.assertEqual(replay['result'], 'already_bound')
        self.assertEqual(set(replay['operation_inputs']), {'--close-task'})
        replay = self.invoke('--record-platform-observation',
                             {**observation, 'status': 'completed'})[1]
        self.assertEqual(replay['result'], 'already_terminal')
        conflict = self.invoke('--record-platform-observation',
                               {**observation, 'status': 'stopped'})[1]
        self.assertEqual(conflict['result'], 'reconcile')
        self.assertEqual(set(conflict['operation_inputs']), {'--close-task'})
        self.assertIn('platform_observation_unknown', self.detail()['unknown_facts'])

    def test_missing_facts_wrong_identity_and_stale_inputs_do_not_bypass_validation(self):
        bound = self.bind()
        terminal = bound['operation_inputs']['--record-terminal-notification']
        for fields in ({}, {'status': 'running'}, {'status': 'completed', 'sender': '/root/wrong'},
                       {'status': 'completed', 'task_ref': 'bad'},
                       {'status': 'completed', 'reason': 'extra field'}):
            before = self.raw()
            self.assertNotEqual(self.invoke('--record-terminal-notification',
                                           {**terminal, **fields})[0], 0)
            self.assertEqual(self.raw(), before)
        self.assertNotEqual(self.invoke('--record-terminal-notification',
                                       {**terminal, 'status': 'completed'}, 'foreign-session')[0], 0)
        close = bound['operation_inputs']['--close-task']
        self.assertNotEqual(self.invoke('--close-task', close)[0], 0)
        self.invoke('--close-task', {**close, 'reason': 'stop tracking'})
        before = self.raw()
        self.assertNotEqual(self.invoke('--record-terminal-notification',
                                       {**terminal, 'status': 'completed'})[0], 0)
        self.assertNotEqual(self.invoke('--close-task', {**close, 'reason': 'different'})[0], 0)
        self.assertEqual(self.raw(), before)
        replay = self.invoke('--confirm-dispatch', {**self.identity, 'target': self.target})[1]
        self.assertEqual(replay['operation_inputs'], {})

    def test_confirm_conflicts_never_emit_bound_inputs_or_submitted_wrong_identity(self):
        result = governance_dispatch.confirm_dispatch(
            self.session, {**self.identity, 'target': self.target}, state_store=self.store)
        self.assertEqual(result['result'], 'reconcile')
        self.assertEqual(result['operation_inputs'], {'--close-task': self.identity})
        self.assertEqual(self.detail()['operation_inputs'], result['operation_inputs'])

    def test_confirm_ref_conflict_uses_preserved_identity(self):
        self.bind()
        result = governance_dispatch.confirm_dispatch(
            self.session, {**self.identity, 'task_ref': 'wrong', 'target': self.target},
            state_store=self.store)
        self.assertEqual(result['operation_inputs'], {'--close-task': self.identity})

    def test_generation_and_write_failure_do_not_partially_commit(self):
        self.claim()
        before = self.raw()
        with mock.patch.object(governance_dispatch, 'operation_inputs',
                               side_effect=RuntimeError('render failure')):
            with self.assertRaisesRegex(RuntimeError, 'render failure'):
                governance_dispatch.confirm_dispatch(
                    self.session, {**self.identity, 'target': self.target}, state_store=self.store)
        self.assertEqual(self.raw(), before)
        bound = governance_dispatch.confirm_dispatch(
            self.session, {**self.identity, 'target': self.target}, state_store=self.store)
        before = self.raw()
        terminal = bound['operation_inputs']['--record-terminal-notification']
        for owner, name in [(governance_lifecycle, 'operation_inputs'),
                            (StateStore, '_write_path')]:
            with mock.patch.object(owner, name, side_effect=RuntimeError('injected failure')):
                self.assertNotEqual(self.invoke('--record-terminal-notification',
                                               {**terminal, 'status': 'completed'})[0], 0)
            self.assertEqual(self.raw(), before)

    def test_returned_input_mutation_cannot_change_ledger_or_other_inputs(self):
        bound = self.bind()
        original = copy.deepcopy(bound['operation_inputs'])
        bound['operation_inputs']['--close-task']['task_ref'] = 'changed'
        self.assertEqual(self.detail()['operation_inputs'], original)
        self.assertEqual(bound['operation_inputs']['--record-terminal-notification'],
                         original['--record-terminal-notification'])

    def test_prepare_render_failure_preserves_existing_ledger(self):
        before = self.raw()
        with mock.patch.object(governance_protocol, 'operation_inputs',
                               side_effect=RuntimeError('render failure')):
            with self.assertRaises(DispatchPreparationError):
                governance_protocol.prepare_dispatch(
                    {'objective': 'Another task', 'scope': ['tests'], 'completion': ['verified']},
                    self.session, native_interface='collaboration_turns', state_store=self.store)
        self.assertEqual(self.raw(), before)

    def test_inputs_survive_exact_committed_prepare_readback_recovery(self):
        original = self.store._write_path

        def write_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('reported after commit')

        with mock.patch.object(self.store, '_write_path', side_effect=write_then_fail):
            prepared = governance_protocol.prepare_dispatch(
                {'objective': 'Recover committed task', 'scope': ['tests'], 'completion': ['verified']},
                self.session, native_interface='collaboration_turns', state_store=self.store)
        self.assertIn('warning', prepared)
        recovered = status(self.session, self.root, task_id=prepared['task_id'],
                           task_ref=prepared['task_ref'])['tasks'][0]
        self.assertEqual(prepared['operation_inputs'], recovered['operation_inputs'])
        self.assertEqual(len(self.store.read(self.session)['tasks']), 2)

    def test_target_ownership_conflict_never_exposes_owner_as_new_bound_input(self):
        self.bind()
        second = governance_protocol.prepare_dispatch(
            {'objective': 'Second task', 'scope': ['tests'], 'completion': ['verified']},
            self.session, native_interface='collaboration_turns', state_store=self.store)
        handle_hook({'hook_event_name': 'PreToolUse', 'session_id': self.session,
                     'tool_name': 'spawn_agent', 'tool_use_id': 'second-call',
                     'tool_input': second['spawn_args']}, self.store)
        identity = second['operation_inputs']['--confirm-dispatch']
        result = governance_dispatch.confirm_dispatch(
            self.session, {**identity, 'target': self.target}, state_store=self.store)
        self.assertEqual(result['result'], 'reconcile')
        self.assertEqual(result['operation_inputs'], {'--close-task': identity})
        self.assertEqual(self.detail()['phase'], 'bound')

    def test_inactive_then_explicit_terminal_keeps_acceptance_separate_without_extra_reads(self):
        bound = self.bind()
        governance_lifecycle.record_interrupt_result(
            self.session, {**self.identity, 'target': self.target, 'result': 'inactive'},
            state_store=self.store)
        self.assertEqual(set(self.detail()['operation_inputs']), {'--close-task'})
        notification = bound['operation_inputs']['--record-terminal-notification']
        with mock.patch.object(self.store, 'read', side_effect=AssertionError('extra read')):
            ended = governance_lifecycle.record_terminal_notification(
                self.session, {**notification, 'status': 'completed'}, state_store=self.store)
        self.assertEqual(set(ended['operation_inputs']), {'--close-task'})
        self.assertEqual(self.detail()['phase'], 'terminal')
        self.assertEqual(self.detail()['terminal_status'], 'completed')
