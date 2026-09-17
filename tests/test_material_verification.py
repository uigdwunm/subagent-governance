"""Declared materials must be usable, handed off, and checked within one budget."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import governance_context as context
from scripts.governance_contracts import contract_from_input
from scripts.governance_dispatch_rendering import spawn_args
from scripts.governance_errors import ContextMaterialConflictError, ContextVerificationError
from scripts.governance_hook import handle_hook
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_semantics import (
    MACHINE_SEMANTICS,
    MAX_HOOK_INPUT_BYTES,
    SEMANTIC_DEFINITIONS,
)
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class MaterialVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        (self.workspace / 'docs').mkdir()
        (self.workspace / 'docs/input.txt').write_bytes(b'stable\n')
        (self.workspace / 'required.txt').write_bytes(b'stable\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.revision = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.workspace), *args], check=True,
                              capture_output=True, text=True).stdout

    def manifest(self, path='required.txt', kind='file', baseline='git_commit'):
        return {'mode': 'declared', 'workspace_root': str(self.workspace),
                'baseline': {'kind': baseline, 'revision': self.revision if baseline == 'git_commit' else None},
                'required_paths': [{'path': path, 'type': kind}]}

    def contract(self, manifest):
        return {'objective': 'Review materials', 'scope': ['declared materials'],
                'completion': ['report evidence'], 'context': {'verified': manifest},
                'spawn': {'fork_turns': 'none'}}

    def prepare(self, manifest):
        self.store = StateStore(self.root / 'state')
        return prepare_dispatch(self.contract(manifest), 'fixture',
                                native_interface='collaboration_turns', state_store=self.store, now=100)

    def hook(self, prepared):
        return handle_hook({'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent',
                            'session_id': 'fixture', 'tool_use_id': 'call', 'now': 101,
                            'tool_input': prepared['spawn_args']}, self.store)['hookSpecificOutput']

    def test_skip_worktree_and_assume_unchanged_do_not_hide_absence_or_change(self):
        for flag in ('--skip-worktree', '--assume-unchanged'):
            for contents in (None, b'changed\n'):
                with self.subTest(flag=flag, contents=contents):
                    file = self.workspace / 'required.txt'
                    file.write_bytes(b'stable\n')
                    self.git('update-index', '--no-skip-worktree', '--no-assume-unchanged', 'required.txt')
                    self.git('update-index', flag, 'required.txt')
                    if contents is None:
                        file.unlink()
                    else:
                        file.write_bytes(contents)
                    with self.assertRaises(ContextMaterialConflictError):
                        context.verify_context_manifest(self.manifest())

    def test_directory_checks_actual_tracked_descendants(self):
        context.verify_context_manifest(self.manifest('docs', 'directory'))
        self.git('update-index', '--skip-worktree', 'docs/input.txt')
        (self.workspace / 'docs/input.txt').unlink()
        with self.assertRaises(ContextMaterialConflictError):
            context.verify_context_manifest(self.manifest('docs', 'directory'))

    def test_links_are_unavailable_even_when_the_target_is_readable(self):
        for target in ('missing', 'required.txt'):
            with self.subTest(target=target):
                link = self.workspace / 'link'
                if link.is_symlink():
                    link.unlink()
                try:
                    link.symlink_to(target)
                except OSError as exc:
                    self.skipTest(f'symlinks unavailable: {exc}')
                self.git('add', 'link')
                self.git('commit', '-qm', 'link')
                self.revision = self.git('rev-parse', 'HEAD').strip()
                with self.assertRaises(ContextVerificationError) as caught:
                    context.verify_context_manifest(self.manifest('link'))
                self.assertNotIsInstance(caught.exception, ContextMaterialConflictError)

    def test_raw_bytes_reject_git_clean_crlf_conversion(self):
        (self.workspace / '.gitattributes').write_text('required.txt text eol=crlf\n')
        self.git('add', '.gitattributes')
        self.git('add', '--renormalize', 'required.txt')
        self.git('commit', '-qm', 'attributes')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        (self.workspace / 'required.txt').write_bytes(b'stable\r\n')
        self.assertEqual(self.git('hash-object', '--path=required.txt', 'required.txt'),
                         self.git('rev-parse', 'HEAD:required.txt'))
        self.git('update-index', '--skip-worktree', 'required.txt')
        self.assertEqual(self.git('status', '--porcelain', '--', 'required.txt'), '')
        with self.assertRaises(ContextMaterialConflictError):
            context.verify_context_manifest(self.manifest())

    def test_paths_are_literal_and_binary_files_are_supported(self):
        for name in ('special[1].txt', 'space name.txt', '中文.txt'):
            (self.workspace / name).write_bytes(b'\x00\xff\r\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'names')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        manifest = self.manifest()
        manifest['required_paths'] = [{'path': name, 'type': 'file'} for name in
                                      ('special[1].txt', 'space name.txt', '中文.txt')]
        verified = context.verify_context_manifest(manifest)
        self.assertEqual(len(verified['required_paths']), 3)

    def test_sparse_checkout_requires_declared_material_to_be_present(self):
        self.git('sparse-checkout', 'set', '--no-cone', '/required.txt')
        context.verify_context_manifest(self.manifest())
        self.assertFalse((self.workspace / 'docs/input.txt').exists())
        with self.assertRaises(ContextMaterialConflictError):
            context.verify_context_manifest(self.manifest('docs', 'directory'))

    def test_working_tree_internal_link_hashes_target(self):
        try:
            (self.workspace / 'link').symlink_to('required.txt')
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        verified = context.verify_context_manifest(self.manifest('link', baseline='working_tree'))
        self.assertEqual(verified['required_paths'][0]['sha256'], hashlib.sha256(b'stable\n').hexdigest())

    def test_claim_detects_hidden_change_without_consuming_capability(self):
        prepared = self.prepare(self.manifest())
        self.git('update-index', '--skip-worktree', 'required.txt')
        (self.workspace / 'required.txt').write_bytes(b'changed')
        result = self.hook(prepared)
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('code=material_conflict', result['permissionDecisionReason'])
        self.assertEqual(self.store.read('fixture')['tasks'][prepared['task_id']]['phase'], 'prepared')

    def test_all_verified_paths_and_baselines_reach_isolated_child(self):
        for baseline in ('git_commit', 'working_tree'):
            manifest = self.manifest(baseline=baseline)
            manifest['required_paths'].append({'path': 'docs/input.txt', 'type': 'file'})
            verified = context.verify_context_manifest(manifest)
            contract = contract_from_input(self.contract(manifest))
            for interface in ('collaboration_turns', 'fork_context'):
                message = spawn_args(contract, 'sg_standard_review_t_abcdefabcdef', verified,
                                     native_interface=interface)['message']
                self.assertIn(str(self.workspace.resolve()), message)
                self.assertIn(baseline, message)
                for item in manifest['required_paths']:
                    self.assertIn(item['path'], message)
                if baseline == 'git_commit':
                    self.assertIn(self.revision, message)

    def test_git_subprocesses_share_remaining_budget(self):
        real_run = subprocess.run
        now = [100.0]
        timeouts = []

        def slow_git(*args, **kwargs):
            timeouts.append(kwargs['timeout'])
            result = real_run(*args, **kwargs)
            now[0] += 2.0
            return result

        with patch.object(context.time, 'monotonic', side_effect=lambda: now[0]):
            with patch.object(context.subprocess, 'run', side_effect=slow_git):
                with self.assertRaisesRegex(ContextVerificationError, '预算'):
                    context.verify_context_manifest(self.manifest())
        self.assertLessEqual(len(timeouts), 3)
        self.assertLessEqual(timeouts[0], 5)
        self.assertEqual(timeouts, sorted(timeouts, reverse=True))

    def test_hook_elapsed_time_is_not_reset_after_ledger_lock(self):
        prepared = self.prepare(self.manifest())
        real_update = self.store.update
        now = [100.0]

        def delayed_update(*args, **kwargs):
            now[0] += 6.0
            return real_update(*args, **kwargs)

        with patch.object(context.time, 'monotonic', side_effect=lambda: now[0]):
            with patch.object(self.store, 'update', side_effect=delayed_update):
                result = self.hook(prepared)
        self.assertEqual(result['permissionDecision'], 'allow')
        self.assertIn('code=material_unavailable', result['additionalContext'])
        self.assertIn('claim=unconfirmed', result['additionalContext'])
        self.assertEqual(self.store.read('fixture')['tasks'][prepared['task_id']]['phase'], 'prepared')

    def test_read_errors_fail_open_without_verification_success(self):
        prepared = self.prepare(self.manifest(baseline='working_tree'))
        with patch.object(context, 'sha256_file', side_effect=PermissionError('private detail')):
            result = self.hook(prepared)
        self.assertIn('code=material_unavailable', result['additionalContext'])
        self.assertNotIn('private detail', json.dumps(result))
        self.assertEqual(self.store.read('fixture')['tasks'][prepared['task_id']]['phase'], 'prepared')

    def test_timeout_during_working_tree_read_does_not_return_a_digest(self):
        real_fdopen = os.fdopen
        now = [100.0]

        class SlowReader:
            def __init__(self, fd, mode):
                self.handle = real_fdopen(fd, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def fileno(self):
                return self.handle.fileno()

            def read(self, count):
                result = self.handle.read(count)
                now[0] += 6
                return result

        with patch.object(context.time, 'monotonic', side_effect=lambda: now[0]):
            with patch.object(context.os, 'fdopen', side_effect=SlowReader):
                with self.assertRaisesRegex(ContextVerificationError, '预算'):
                    context.verify_context_manifest(self.manifest(baseline='working_tree'))

    def test_git_timeout_is_unavailable_and_does_not_claim(self):
        prepared = self.prepare(self.manifest())
        with patch.object(context.subprocess, 'run', side_effect=subprocess.TimeoutExpired('git', 0.1)):
            result = self.hook(prepared)
        self.assertEqual(result['permissionDecision'], 'allow')
        self.assertIn('code=material_unavailable', result['additionalContext'])
        self.assertIn('claim=unconfirmed', result['additionalContext'])
        self.assertEqual(self.store.read('fixture')['tasks'][prepared['task_id']]['phase'], 'prepared')

    def test_directory_rejects_links_and_submodules_without_recursing_outside(self):
        self.git('update-index', '--add', '--cacheinfo', f'160000,{self.revision},docs/module')
        self.git('commit', '-qm', 'gitlink')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        for path, kind in (('docs', 'directory'), ('docs/module', 'directory')):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ContextVerificationError, '子模块') as caught:
                    context.verify_context_manifest(self.manifest(path, kind))
                self.assertNotIsInstance(caught.exception, ContextMaterialConflictError)

    def test_untracked_addition_is_conflict_but_ignored_and_unrelated_files_are_not(self):
        (self.workspace / 'outside.txt').write_text('unrelated')
        (self.workspace / '.git/info/exclude').write_text('docs/ignored.txt\n')
        (self.workspace / 'docs/ignored.txt').write_text('ignored')
        context.verify_context_manifest(self.manifest('docs', 'directory'))
        (self.workspace / 'docs/new.txt').write_text('new')
        with self.assertRaises(ContextMaterialConflictError):
            context.verify_context_manifest(self.manifest('docs', 'directory'))

    def test_directory_with_special_descendant_names_and_overlapping_declarations(self):
        if os.name == 'nt':
            self.skipTest('control characters in filenames are not supported on Windows')
        (self.workspace / 'docs/tab\tline\r\n.txt').write_bytes(b'binary\x00\xff')
        self.git('add', 'docs')
        self.git('commit', '-qm', 'special descendant')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        manifest = self.manifest('docs', 'directory')
        manifest['required_paths'].append({'path': 'docs/input.txt', 'type': 'file'})
        self.assertEqual(len(context.verify_context_manifest(manifest)['required_paths']), 2)

    def test_read_permission_failure_is_not_a_material_conflict(self):
        with patch.object(context.os, 'open', side_effect=PermissionError('fixture')):
            with self.assertRaises(ContextVerificationError) as caught:
                context.verify_context_manifest(self.manifest())
        self.assertNotIsInstance(caught.exception, ContextMaterialConflictError)

    def test_unreadable_directory_is_not_verified_from_child_stat_alone(self):
        with patch.object(context.os, 'scandir', side_effect=PermissionError('fixture')):
            with self.assertRaises(ContextVerificationError) as caught:
                context.verify_context_manifest(self.manifest('docs', 'directory'))
        self.assertNotIsInstance(caught.exception, ContextMaterialConflictError)

    def test_maximum_byte_contract_hands_off_all_64_materials_and_can_claim(self):
        manifest = self.manifest(baseline='working_tree')
        manifest['required_paths'] = []
        for index in range(64):
            relative = f'{index:02d}' + 'f' * 178
            file = self.workspace / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'data')
            manifest['required_paths'].append({'path': relative, 'type': 'file'})
        raw = self.contract(manifest)
        raw['scope'] = ['x' * 1000] * 46
        normalized = contract_from_input(raw).business_record()
        size = len(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
        raw['context']['summary'] = 's' * (65536 - size)
        self.assertEqual(len(json.dumps(contract_from_input(raw).business_record(), ensure_ascii=False,
                                       sort_keys=True, separators=(',', ':')).encode()), 65536)
        self.store = StateStore(self.root / 'state')
        prepared = prepare_dispatch(raw, 'fixture', native_interface='collaboration_turns',
                                    state_store=self.store, now=100)
        message = prepared['spawn_args']['message']
        for item in manifest['required_paths']:
            self.assertIn(item['path'], message)
        self.assertLessEqual(len(message), SEMANTIC_DEFINITIONS['expected_native_parameters']['properties']['message']['maxLength'])
        self.assertLess(len(json.dumps({'tool_input': prepared['spawn_args']}).encode()), MAX_HOOK_INPUT_BYTES)
        self.assertEqual(self.hook(prepared)['permissionDecision'], 'allow')
        ledger = self.store.read('fixture')
        self.assertEqual(ledger['tasks'][prepared['task_id']]['phase'], 'claimed')
        self.assertEqual(validate_instance(ledger, SEMANTIC_DEFINITIONS['session_ledger'],
                                           root_schema=MACHINE_SEMANTICS), [])

    def test_git_64_paths_share_batched_commands_and_accept_unchanged_claim(self):
        manifest = self.manifest()
        manifest['required_paths'] = []
        for index in range(64):
            name = f'file-{index}.txt'
            (self.workspace / name).write_bytes(b'unchanged')
            manifest['required_paths'].append({'path': name, 'type': 'file'})
        self.git('add', '.')
        self.git('commit', '-qm', '64 files')
        manifest['baseline']['revision'] = self.git('rev-parse', 'HEAD').strip()
        with patch.object(context.subprocess, 'run', wraps=subprocess.run) as calls:
            prepared = self.prepare(manifest)
        self.assertLessEqual(calls.call_count, 6)
        self.assertEqual(len(prepared['context_verification']['required_paths']), 64)
        self.assertIn('claim=confirmed', self.hook(prepared)['additionalContext'])

    def test_sha256_git_repository_matches_actual_bytes(self):
        self.workspace = self.root / 'sha256'
        self.workspace.mkdir()
        try:
            self.git('init', '-q', '--object-format=sha256')
        except subprocess.CalledProcessError:
            self.skipTest('Git does not support SHA-256 repositories')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.workspace / 'required.txt').write_bytes(b'bytes\x00\xff')
        self.git('add', '.')
        self.git('commit', '-qm', 'sha256')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        record = context.verify_context_manifest(self.manifest())
        self.assertEqual(record['required_paths'][0]['object_id'],
                         self.git('rev-parse', 'HEAD:required.txt').strip())
        self.assertEqual(len(record['required_paths'][0]['object_id']), 64)

    def test_physical_parent_link_is_unavailable(self):
        (self.workspace / 'docs').rename(self.workspace / 'actual-docs')
        try:
            (self.workspace / 'docs').symlink_to('actual-docs', target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        with self.assertRaisesRegex(ContextVerificationError, '符号链接') as caught:
            context.verify_context_manifest(self.manifest('docs/input.txt'))
        self.assertNotIsInstance(caught.exception, ContextMaterialConflictError)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO requires POSIX')
    def test_fifo_replacement_does_not_block_or_verify(self):
        path = self.workspace / 'required.txt'
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ContextVerificationError, '非普通文件'):
            context.verify_context_manifest(self.manifest())

    def test_working_tree_change_at_claim_is_a_conflict(self):
        prepared = self.prepare(self.manifest(baseline='working_tree'))
        (self.workspace / 'required.txt').write_bytes(b'changed')
        result = self.hook(prepared)
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('code=material_conflict', result['permissionDecisionReason'])
