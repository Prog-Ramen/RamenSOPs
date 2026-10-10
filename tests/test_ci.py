import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
import review
import semantic
import merge
import index

CODE = '''import json, sys
args = json.load(sys.stdin)
text = args['text']
if text:
    result = text.upper()
else:
    result = ''
json.dump({'upper': result}, sys.stdout)
'''
META = {'id': 'text.upper', 'description': 'Convert caller supplied text into uppercase characters and return the transformed string in a JSON object, including empty input.',
        'kind': 'script', 'status': 'validated', 'scope': 'public', 'version': '1.0.0', 'entry': 'run.py', 'permissions': ['compute'],
        'inputs': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
        'tests': [{'input': {'text': 'hello'}, 'expect': {'upper': 'HELLO'}}, {'input': {'text': ''}, 'expect': {'upper': ''}}]}

def sh(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', *args], check=True, capture_output=True, text=True).stdout.strip()

class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sh(self.root, 'init', '-q', '-b', 'main')
        (self.root / 'README.md').write_text('Registry')
        sh(self.root, 'add', '.')
        sh(self.root, 'commit', '-qm', 'base')
        self.base = sh(self.root, 'rev-parse', 'HEAD')
        self.path = self.root / 'sops/text/upper'
        self.put()

    def put(self, meta=None, code=CODE):
        self.meta = copy.deepcopy(meta or META)
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / 'sop.json').write_text(json.dumps(self.meta))
        (self.path / 'run.py').write_text(code)

    def check(self, runner=lambda *args: None):
        sh(self.root, 'add', '.')
        sh(self.root, 'commit', '-qm', 'change')
        self.head = sh(self.root, 'rev-parse', 'HEAD')
        return review.review(self.root, self.base, self.head, True, runner)

    def test_new_sop_runs_concrete_cases(self):
        calls = []
        r = self.check(lambda d, e, t: calls.append(t))
        self.assertTrue(r['auto_merge'], r)
        self.assertEqual(calls, META['tests'])

    def test_linear_utility_can_reach_semantic_review(self):
        self.put(code="import json, sys\na = json.load(sys.stdin)\njson.dump({'upper': a['text'].upper()}, sys.stdout)\n")
        r = self.check()
        self.assertTrue(r['auto_merge'], r)
        self.assertEqual(r['head'], self.head)

    def test_failed_tests_block_merge(self):
        def fail(*args): raise ValueError('wrong result')
        r = self.check(fail)
        self.assertFalse(r['ok'])
        self.assertFalse(r['auto_merge'])

    def test_no_untrusted_host_execution(self):
        sentinel = self.root / 'executed'
        self.put(code=CODE + f'\nopen({str(sentinel)!r}, "w").write("bad")\n')
        r = self.check()
        self.assertFalse(sentinel.exists())
        self.assertFalse(r['auto_merge'])

    def test_key_only_tests_block(self):
        self.meta['tests'] = [{'input': {'text': 'a'}, 'expect_keys': ['upper']}] * 2
        self.put(self.meta)
        self.assertFalse(self.check()['ok'])

    def test_error_and_key_tests_run_alongside_concrete_ones(self):
        self.meta['tests'] += [{'input': {'text': 'b'}, 'expect_keys': ['upper']},
                               {'input': {'text': 1}, 'expect_error': True}]
        self.meta['inputs']['properties']['text'] = {}           # untyped, so the error case is a valid input
        self.put(self.meta)
        calls = []
        self.assertTrue(self.check(lambda root, entry, case: calls.append(case))['ok'])
        self.assertEqual(len(calls), 4)                          # every shipped test is executed

    def test_fixture_paths_must_stay_inside_the_scratch_directory(self):
        self.meta['tests'][0]['files'] = {'../escape.txt': 'x'}
        self.put(self.meta)
        self.assertFalse(self.check()['ok'])

    def test_fixtures_make_otherwise_identical_inputs_distinct(self):
        self.meta['tests'] = [{'input': {'text': 'a'}, 'files': {'a.txt': '1'}, 'expect': {'upper': 'A'}},
                              {'input': {'text': 'a'}, 'files': {'a.txt': '2'}, 'expect': {'upper': 'A'}}]
        self.put(self.meta)
        self.assertNotIn('tests must exercise distinct inputs', ' '.join(self.check()['fail']))

    def test_identical_inputs_block(self):
        self.meta['tests'] = [self.meta['tests'][0]] * 2
        self.put(self.meta)
        self.assertFalse(self.check()['ok'])

    def test_constant_outputs_need_human(self):
        self.meta['tests'][1]['expect'] = {'upper': 'HELLO'}
        self.put(self.meta)
        self.assertFalse(self.check()['auto_merge'])

    def test_private_data_needs_human(self):
        self.put(code=CODE + '\nHOST = "cedardock.internal"\n')
        r = self.check()
        self.assertTrue(r['ok'])
        self.assertFalse(r['auto_merge'])

    def test_secret_blocks(self):
        self.put(code=CODE + '\nTOKEN = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n')
        self.assertFalse(self.check()['ok'])

    def test_undeclared_network_blocks(self):
        self.put(code='import socket\n' + CODE)
        self.assertFalse(self.check()['ok'])

    def test_declared_network_needs_human(self):
        self.meta['permissions'] = ['compute', 'network']
        self.put(self.meta, 'import socket\n' + CODE)
        r = self.check()
        self.assertTrue(r['ok'], r)
        self.assertFalse(r['auto_merge'])

    def test_declared_file_write_eligible(self):
        self.meta['permissions'].append('fs:write')
        self.put(self.meta, CODE + '\nif args.get("output_file"):\n    open(args["output_file"], "w").write(result)\n')
        self.assertTrue(self.check()['auto_merge'])

    def test_dynamic_execution_needs_human(self):
        self.put(code=CODE + '\neval("1")\n')
        self.assertFalse(self.check()['auto_merge'])

    def test_symlink_blocks(self):
        (self.path / 'link.py').symlink_to('/etc/passwd')
        self.assertFalse(self.check()['ok'])

    def test_escaping_entry_blocks(self):
        self.meta['entry'] = '../../../README.md'
        self.put(self.meta)
        self.assertFalse(self.check()['ok'])

    def test_malformed_metadata_fails_closed(self):
        (self.path / 'sop.json').write_text('[]')
        self.assertFalse(self.check()['ok'])

    def test_invalid_permissions_fail_closed(self):
        self.meta['permissions'] = [{'compute': True}]
        self.put(self.meta)
        self.assertFalse(self.check()['ok'])

    def test_workflow_changes_require_human(self):
        wf = self.root / '.github/workflows/check.yml'
        wf.parent.mkdir(parents=True)
        wf.write_text('name: fake')
        self.assertFalse(self.check()['auto_merge'])

    def test_index_in_pr_blocked(self):
        (self.root / 'sops/index.json').write_text('{}')
        self.assertFalse(self.check()['ok'])

    def existing(self):
        sh(self.root, 'add', '.')
        sh(self.root, 'commit', '-qm', 'existing SOP')
        self.base = sh(self.root, 'rev-parse', 'HEAD')
        self.meta['version'] = '1.1.0'

    def test_compatible_update_retains_regression_tests(self):
        self.existing()
        self.meta['tests'].append({'input': {'text': 'é'}, 'expect': {'upper': 'É'}})
        self.put(self.meta)
        calls = []
        r = self.check(lambda d, e, t: calls.append(t))
        self.assertTrue(r['auto_merge'], r)
        self.assertEqual(r['sops'][0]['regression_tests'], 2)
        self.assertEqual(len(calls), 3)

    def test_removed_regression_blocks(self):
        self.existing()
        self.meta['tests'][1] = {'input': {'text': 'bye'}, 'expect': {'upper': 'BYE'}}
        self.put(self.meta)
        self.assertFalse(self.check()['ok'])

    def test_breaking_schema_requires_human(self):
        self.existing()
        self.meta['inputs']['properties']['option'] = {'type': 'boolean'}
        self.put(self.meta)
        self.assertFalse(self.check()['auto_merge'])

    def test_semantic_review_exact_booleans(self):
        self.check()
        good = {k: True for k in semantic.KEYS}
        good['reason'] = 'Useful parameterized text operation, tested empty and normal input.'
        def answer(req): return {'choices': [{'message': {'content': json.dumps(good)}}]}
        r = semantic.decide(self.root, self.base, self.head, [{'id': 'text.upper', 'new': True}], 'fake', answer, sleep=lambda _: None)
        self.assertTrue(r['approved'])
        good['meaningful'] = 'true'
        self.assertFalse(semantic.decide(self.root, self.base, self.head, [{'id': 'text.upper', 'new': True}], 'fake', answer, sleep=lambda _: None)['approved'])

    def test_semantic_api_failure_blocks(self):
        self.check()
        def fail(req): raise OSError('unavailable')
        r = semantic.decide(self.root, self.base, self.head, [{'id': 'text.upper', 'new': True}], 'fake', fail, sleep=lambda _: None)
        self.assertFalse(r['approved'])
        self.assertTrue(r['unavailable'])

    def test_index_matches_sharded_format_and_hashes(self):
        index.build(self.root / 'sops')
        top = json.loads((self.root / 'sops/index.json').read_text())
        self.assertEqual(top['format'], 4)
        self.assertEqual(top['entries'][0]['id'], 'text')
        entries = json.loads((self.root / 'sops/text/_index.json').read_text())['entries']
        self.assertEqual(entries[0]['id'], 'text.upper')
        # columnar: the listing holds only what a client chooses by; the rest is in _meta.json, pinned by hash
        self.assertEqual(sorted(entries[0]), ['description', 'id', 'keywords', 'meta', 'path', 'type'])
        meta = (self.root / 'sops' / entries[0]['meta']['path']).read_bytes()
        self.assertEqual(hashlib.sha256(meta).hexdigest(), entries[0]['meta']['sha256'])
        self.assertEqual(len(json.loads(meta)['files']), 2)              # run.py and sop.json, not _meta.json
        first = (self.root / 'sops/text/_index.json').read_text()
        index.build(self.root / 'sops')
        self.assertEqual(first, (self.root / 'sops/text/_index.json').read_text())

    def test_the_root_index_carries_aliases(self):
        (self.root / 'sops/_aliases.json').write_text(json.dumps({'text.old_upper': 'text.upper'}))
        index.build(self.root / 'sops')
        self.assertEqual(json.loads((self.root / 'sops/index.json').read_text())['aliases'], {'text.old_upper': 'text.upper'})

    def test_a_pure_move_is_a_reorganization_not_a_deletion(self):
        sh(self.root, 'add', '.')
        sh(self.root, 'commit', '-qm', 'the SOP exists')
        self.base = sh(self.root, 'rev-parse', 'HEAD')
        target = self.root / 'sops/text/case/upper'
        target.parent.mkdir(parents=True)
        (self.root / 'sops/text/case/_node.json').write_text(json.dumps({'description': 'Change letter case'}))
        sh(self.root, 'mv', 'sops/text/upper', 'sops/text/case/upper')
        meta = json.loads((target / 'sop.json').read_text())
        (target / 'sop.json').write_text(json.dumps({**meta, 'id': 'text.case.upper'}))
        (self.root / 'sops/_aliases.json').write_text(json.dumps({'text.upper': 'text.case.upper'}))
        r = self.check()
        self.assertTrue(r['ok'], r['fail'])
        self.assertFalse(r['auto_merge'])                                   # a reorganization needs a maintainer
        self.assertTrue(any('reorganization: 1 SOP(s) moved' in h for h in r['human']), r['human'])

    def test_a_new_category_alongside_a_new_sop_is_fine(self):
        (self.root / 'sops/text/_node.json').write_text(json.dumps({'description': 'Text utilities'}))
        r = self.check()
        self.assertFalse(any('_node.json' in f for f in r['fail']), r['fail'])

    def test_a_pr_may_not_leave_a_category_crowded(self):
        for i in range(8):
            d = self.root / f'sops/text/other_{i}'
            d.mkdir(parents=True)
            meta = copy.deepcopy(META)
            meta['id'] = f'text.other_{i}'
            (d / 'sop.json').write_text(json.dumps(meta))
            (d / 'run.py').write_text(CODE)
        r = self.check()
        self.assertTrue(any('9 SOPs directly in it (limit 8)' in f for f in r['fail']), r['fail'])

    def test_generated_metadata_must_not_be_committed(self):
        (self.path / '_meta.json').write_text('{}')
        self.assertTrue(any('generated indexes' in f for f in self.check()['fail']))

class MergeGuardTests(unittest.TestCase):
    def test_requires_latest_successful_runs_for_exact_head(self):
        sha = 'a' * 40
        def fake(path, *args):
            if path.startswith('pulls/'):
                return {'head': {'repo': {'full_name': 'contributor/fork'}}}
            filename = path.split('/')[2]
            return {'workflow_runs': [{'id': 1, 'head_sha': sha, 'event': 'pull_request', 'path': '.github/workflows/' + filename,
                  'head_repository': {'full_name': 'contributor/fork'}, 'conclusion': 'success'}]}
        with patch.object(merge, 'api', side_effect=fake):
            self.assertTrue(merge.checked(2, sha))
        def latest_failed(path, *args):
            r = fake(path)
            if 'workflow_runs' in r:
                r['workflow_runs'].append({**r['workflow_runs'][0], 'id': 2, 'conclusion': 'failure'})
            return r
        with patch.object(merge, 'api', side_effect=latest_failed):
            self.assertFalse(merge.checked(2, sha))

    def test_unrelated_event_cannot_authorize_merge(self):
        def fake(path, *args):
            if path.startswith('pulls/'):
                return {'head': {'repo': {'full_name': 'contributor/fork'}}}
            return {'workflow_runs': [{'id': 1, 'head_sha': 'a'*40, 'event': 'push', 'path': '.github/workflows/sop-check.yml', 'head_repository': {'full_name': 'contributor/fork'}, 'conclusion': 'success'}]}
        with patch.object(merge, 'api', side_effect=fake):
            self.assertFalse(merge.checked(2, 'a'*40))


class ContainerAssertionTests(unittest.TestCase):
    def test_docker_forwards_stdin_without_credentials(self):
        def fake(cmd, **kwargs):
            if cmd[:2] == ['docker', 'run']:
                self.assertIn('-i', cmd)
                self.assertIn('--network=none', cmd)
                self.assertNotIn('--env', cmd)
                self.assertNotIn('-e', cmd)
                self.assertEqual(json.loads(kwargs['input']), META['tests'][0])
                kwargs['stdout'].write(b'{"upper":"HELLO"}')
            return subprocess.CompletedProcess(cmd, 0)
        with tempfile.TemporaryDirectory() as temp, patch.object(review.subprocess, 'run', side_effect=fake):
            review.run_case(Path(temp), 'run.py', META['tests'][0])

    def test_file_contents_checked_independently(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'run.py'
            script.write_text('import json,sys\na=json.load(sys.stdin)\nopen(a["output_file"],"w").write(json.dumps({"n":3}))\njson.dump({"n":3},sys.stdout)\n')
            case = {'input': {'output_file': 'report.json'}, 'expect_files': {'report.json': {'n': 3}}}
            cmd = [sys.executable, str(Path(review.__file__).with_name('run_test.py')), str(script)]
            p = subprocess.run(cmd, cwd=root, input=json.dumps(case), text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            case['expect_files']['report.json']['n'] = 4
            p = subprocess.run(cmd, cwd=root, input=json.dumps(case), text=True, capture_output=True)
            self.assertNotEqual(p.returncode, 0)

    def runner(self, root, script, case):
        cmd = [sys.executable, str(Path(review.__file__).with_name('run_test.py')), str(script)]
        return subprocess.run(cmd, cwd=root, input=json.dumps(case), text=True, capture_output=True)

    def test_fixtures_are_built_before_the_sop_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'run.py'
            script.write_text('import json,sys\na=json.load(sys.stdin)\njson.dump({"n": len(open(a["path"],"rb").read())},sys.stdout)\n')
            case = {'input': {'path': 'data/in.txt'}, 'files': {'data/in.txt': 'abc'}, 'expect': {'n': 3}}
            p = self.runner(root, script, case)
            self.assertEqual((p.returncode, json.loads(p.stdout)), (0, {'n': 3}), p.stderr)
            case = {'input': {'path': 'img.bin'}, 'setup': 'open("img.bin","wb").write(bytes(7))', 'expect': {'n': 7}}
            self.assertEqual(json.loads(self.runner(root, script, case).stdout), {'n': 7})

    def test_expected_errors_pass_only_when_the_sop_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / 'run.py'
            script.write_text('import json,sys\na=json.load(sys.stdin)\nsys.exit(2) if a["bad"] else json.dump({},sys.stdout)\n')
            p = self.runner(root, script, {'input': {'bad': True}, 'expect_error': True})
            self.assertEqual(json.loads(p.stdout), {'expected_error': True})
            p = self.runner(root, script, {'input': {'bad': False}, 'expect_error': True})
            self.assertEqual(json.loads(p.stdout), {'unexpected_success': True})

    def test_non_object_output_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'run.py'
            script.write_text('print("[]")')
            p = subprocess.run([sys.executable, str(Path(review.__file__).with_name('run_test.py')), str(script)],
                               input='{"input":{}}', text=True, capture_output=True)
            self.assertNotEqual(p.returncode, 0)

class CacheTests(unittest.TestCase):
    def test_semantic_cache_bound_to_head_policy_and_bot(self):
        import base64
        data = {'head': 'a'*40, 'policy': merge.policy_id(), 'judgment': {'approved': False, 'reason': 'specific'}}
        body = merge.MARKER + '\n<!-- sop-semantic-cache:' + base64.b64encode(json.dumps(data).encode()).decode() + ' -->'
        comments = [{'user': {'login': 'github-actions[bot]'}, 'body': body}]
        with patch.object(merge, 'api', return_value=comments):
            self.assertEqual(merge.cached_semantic(2, 'a'*40)['approved'], False)
            self.assertIsNone(merge.cached_semantic(2, 'b'*40))
        comments[0]['user']['login'] = 'attacker'
        with patch.object(merge, 'api', return_value=comments):
            self.assertIsNone(merge.cached_semantic(2, 'a'*40))

if __name__ == '__main__':
    unittest.main()
