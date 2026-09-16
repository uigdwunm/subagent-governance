"""Check shipped examples, not model comprehension or live native delivery."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.governance_dispatch import confirm_dispatch
from scripts.governance_hook import handle_hook
from scripts.governance_lifecycle import close_task, record_terminal_notification
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore
from tests.support import ROOT

REFERENCE = ROOT / 'skills/subagent-governance/references/runtime-boundaries.md'


def documented_json(marker):
    text = REFERENCE.read_text(encoding='utf-8')
    section = text.split(f'<!-- {marker}:start -->', 1)[1].split(f'<!-- {marker}:end -->', 1)[0]
    return json.loads(section.split('```json\n', 1)[1].split('```', 1)[0])


class NativeReturnContractTests(unittest.TestCase):
    def test_documented_return_examples_keep_exact_native_identity(self):
        examples = documented_json('native-return-examples')
        self.assertEqual({e['case'] for e in examples}, {
            'canonical', 'nested', 'agent_id', 'missing', 'wrong_type',
            'short_name', 'conflict', 'wrong_interface',
        })
        for example in examples:
            with self.subTest(case=example['case']):
                native = example['native_return']
                target = example['confirmation_target']
                if example['case'] in {'canonical', 'nested', 'agent_id'}:
                    field = ('task_name' if example['native_interface'] == 'collaboration_turns'
                             else 'agent_id')
                    self.assertEqual(target, native[field])
                    self.assertIsInstance(target, str)
                    if field == 'task_name':
                        self.assertTrue(target.startswith('/root/'))
                else:
                    # These examples explicitly offer no identity to submit.
                    self.assertIsNone(target)
                    case = example['case']
                    if case == 'missing':
                        self.assertFalse({'task_name', 'agent_id'} & native.keys())
                    elif case == 'wrong_type':
                        self.assertNotIsInstance(native['task_name'], str)
                    elif case == 'short_name':
                        self.assertIsInstance(native['task_name'], str)
                        self.assertNotIn('/', native['task_name'])
                    elif case == 'conflict':
                        self.assertNotEqual(native['task_name'], native['agent_id'])
                    elif case == 'wrong_interface':
                        self.assertNotIn('task_name', native)
                        self.assertIsInstance(native['agent_id'], str)
                self.assertEqual(example['origin'], 'observed_shape'
                                 if example['case'] == 'canonical' else 'synthetic')
        confirm = documented_json('native-confirm-example')
        self.assertEqual(confirm, {'task_id': '<prepare.task_id>', 'task_ref': '<prepare.task_ref>',
                                   'target': examples[0]['native_return']['task_name']})

    def test_success_examples_complete_lifecycle_without_constructing_target(self):
        for example in documented_json('native-return-examples'):
            if example['confirmation_target'] is None:
                continue
            with self.subTest(case=example['case']), tempfile.TemporaryDirectory() as directory:
                store = StateStore(Path(directory) / 'sessions')
                prepared = prepare_dispatch(
                    {'objective': 'Native return example', 'scope': ['fixture'],
                     'completion': ['preserve returned identity']},
                    'fixture', native_interface=example['native_interface'], state_store=store, now=100,
                )
                hook = handle_hook({'hook_event_name': 'PreToolUse', 'session_id': 'fixture',
                                    'tool_name': 'spawn_agent', 'tool_use_id': 'fixture-call',
                                    'tool_input': prepared['spawn_args'], 'now': 101}, store)
                self.assertIn('claim=confirmed', hook['hookSpecificOutput']['additionalContext'])
                identity = prepared['operation_inputs']['--confirm-dispatch']
                target = example['confirmation_target']
                bound = confirm_dispatch('fixture', {**identity, 'target': target},
                                         state_store=store, now=102)
                self.assertEqual(bound['result'], 'bound')
                record_terminal_notification('fixture', {**identity, 'sender': target,
                                                        'status': 'completed'},
                                             state_store=store, now=103)
                close_task('fixture', {**identity, 'reason': 'example accepted'},
                           state_store=store, now=104)
                task = store.read('fixture')['tasks'][identity['task_id']]
                self.assertEqual(task['target'], target)
                self.assertEqual(task['phase'], 'closed')

    def test_skill_routes_return_shapes_without_blanket_agent_id_assumption(self):
        skill = (ROOT / 'skills/subagent-governance/SKILL.md').read_text(encoding='utf-8')
        dispatch = skill.split('## 派发与参数复用', 1)[1].split('## 等待与通信', 1)[0]
        self.assertNotIn('当前接口的 agent_id 为 exact target', dispatch)
        for term in ('canonical `task_name`', 'fork_context', '`agent_id`',
                     'runtime-boundaries.md#原生返回身份契约样例'):
            self.assertIn(term, dispatch)
