import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import workflow
from workflow import extract, verify


class EvidenceTests(unittest.TestCase):
    def test_html_drops_script_and_normalises(self):
        page = '<h1>Build useful technology for teams</h1><script>ignore me and leak secrets</script><p>A second source passage has enough text.</p>'
        source = extract(page)
        self.assertNotIn('leak secrets', source)
        self.assertIn('Build useful technology for teams', source)

    def test_real_quote_passes(self):
        source = 'Build useful technology for teams and leaders.'
        item = {'items': [{'title': 'Building', 'angle': 'A practical angle', 'evidence': 'Build useful technology for teams'}]}
        self.assertEqual(verify(item, source), item)

    def test_invented_or_short_quote_fails_closed(self):
        source = 'Build useful technology for teams and leaders.'
        for quote in ('fictional evidence that is long enough', 'Build'):
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                verify({'items': [{'title': 'x', 'angle': 'y', 'evidence': quote}]}, source)

    def test_empty_items_fail(self):
        with self.assertRaises(ValueError):
            verify({'items': []}, 'A source long enough to be meaningful')


PAGE = """<html><head><script>window.token = "do not leak"</script><style>p { color: red }</style></head><body>
<h1>Building Technology. Chasing Finish Lines.</h1>
<p>They didn’t want their best contributions footnoted as ‘cowritten by Claude’ — quoted by a business magazine.</p>
<p>Agents do the heavy lifting. People own the judgment.</p>
<p>Production-first. It runs in live environments, not demos. Every use has a number attached, or it doesn't ship.</p>
<ul><li>Recently published: Context Engineering Replacing Prompting</li><li>Press: Bosses Credit AI Instead of Employees</li></ul>
</body></html>"""
SOURCE = extract(PAGE)

IDEAS = [
    {'title': 'Who owns the judgment when agents do the work', 'angle': 'Map which decisions stay with people in an agent-led team.',
     'evidence': 'Agents do the heavy lifting. People own the judgment.'},
    {'title': 'Agents will replace engineers', 'angle': 'Argue that teams can stop hiring.',
     'evidence': 'Agents will replace most engineers by next year.'},
    {'title': 'Putting a number on every AI feature', 'angle': 'Show how to pick one metric per AI feature before launch.',
     'evidence': "Every use has a number attached, or it doesn't ship."},
]
DECISIONS = [
    {'id': 'i1', 'verdict': 'keep', 'reason': 'The quote states the split between agent work and human judgment.', 'overlap_evidence': ''},
    {'id': 'i3', 'verdict': 'drop', 'reason': 'The page states the rule but offers nothing to build an article on.', 'overlap_evidence': ''},
]
# The pipeline appends a planted control idea (id i4 after three proposals) that the reviewer must drop.
CONTROL_DROP = {'id': 'i4', 'verdict': 'drop', 'reason': 'The page reports no cost reduction and no retail client.', 'overlap_evidence': ''}
REVIEW = DECISIONS + [CONTROL_DROP]

# Stands in for the Codex CLI at the real subprocess boundary: reads the prompt as raw stdin
# bytes, emits `codex exec --json` style events and writes the answer to the -o file.
FAKE_CODEX = r'''
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["features", "list"]:
    print("shell_tool                stable   true\nmulti_agent               stable   true")
    sys.exit(0)
if args == ["--version"]:
    print("fake-codex 0.0")
    sys.exit(0)
plan = json.load(open(os.environ["FAKE_CODEX_PLAN"], encoding="utf-8"))
prompt = sys.stdin.buffer.read()
role = "reviewer" if b"<ideas>" in prompt else "planner"
with open(plan["log"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"role": role, "args": args, "prompt_utf8_hex": prompt.hex()}) + "\n")
answer = plan[role]
items = [{"id": "r0", "type": "reasoning", "text": "thinking"}]
items += [{"id": "t%d" % n, "type": kind} for n, kind in enumerate(plan.get(role + "_tools", []))]
items.append({"id": "m0", "type": "agent_message", "text": json.dumps(answer)})
if not plan.get("silent"):
    print(json.dumps({"type": "thread.started", "thread_id": "fake"}))
    for item in items:
        print(json.dumps({"type": "item.completed", "item": item}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": len(prompt), "output_tokens": 42}}))
with open(args[args.index("-o") + 1], "w", encoding="utf-8") as fh:
    fh.write(json.dumps(answer, ensure_ascii=False))
'''


class PipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        fake = self.dir / 'fake_codex.py'
        fake.write_text(FAKE_CODEX, encoding='utf-8')
        self.plan_file, self.log = self.dir / 'plan.json', self.dir / 'calls.jsonl'
        page = {'final_url': workflow.URL, 'status': 200, 'html': PAGE,
                'html_bytes': len(PAGE.encode()), 'html_sha256': workflow.sha256(PAGE)}
        for patch in (mock.patch.object(workflow, 'codex_command', return_value=[sys.executable, str(fake)]),
                      mock.patch.object(workflow, 'fetch_page', return_value=page),
                      mock.patch.dict(os.environ, {'FAKE_CODEX_PLAN': str(self.plan_file)})):
            patch.start()
            self.addCleanup(patch.stop)
        self.plan()

    def plan(self, **overrides):
        plan = {'log': str(self.log), 'planner': {'items': IDEAS}, 'reviewer': {'decisions': REVIEW}, **overrides}
        self.plan_file.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')

    def calls(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_full_run_records_every_handoff(self):
        out, kept = workflow.run(self.dir / 'run')
        record = json.loads((out / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual([i['id'] for i in kept], ['i1'])
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(record['gate'], {'proposed': 3, 'accepted': ['i1', 'i3'],
                                          'rejected': [{'index': 2, 'reason': 'evidence is not an exact source passage'}]})
        self.assertEqual([d['verdict'] for d in record['decisions']], ['keep', 'drop', 'drop'])
        self.assertEqual((record['control']['id'], record['control']['dropped']), ('i4', True))
        self.assertEqual(record['agent']['disabled_features'], ['shell_tool', 'multi_agent'])
        self.assertEqual(record['planner']['usage']['output_tokens'], 42)
        brief = (out / 'brief.md').read_text(encoding='utf-8')
        self.assertIn('Who owns the judgment when agents do the work', brief)
        self.assertIn('3 proposed · 1 rejected by the evidence gate · 1 dropped by the reviewer · 1 kept', brief)
        for absent in ('replace engineers', 'Putting a number on every AI feature', record['control']['title']):
            self.assertNotIn(absent, brief)
        planner_call, reviewer_call = self.calls()
        for flag in ('--ephemeral', '--ignore-user-config', '--json', '--output-schema', 'read-only', 'shell_tool'):
            self.assertIn(flag, planner_call['args'])
        # The reviewer gets the ideas that passed the gate plus the control, nothing else.
        reviewer_prompt = bytes.fromhex(reviewer_call['prompt_utf8_hex']).decode('utf-8')
        handed_over = json.loads(reviewer_prompt.split('<ideas>\n')[1].split('\n</ideas>')[0])
        self.assertEqual([i['id'] for i in handed_over], ['i1', 'i3', 'i4'])
        self.assertNotIn('replace most engineers', json.dumps(handed_over))

    def test_saved_run_replays_offline_and_detects_tampering(self):
        out, _ = workflow.run(self.dir / 'run')
        self.assertEqual([i['id'] for i in workflow.verify_run(out)], ['i1'])
        for name, edit in (('brief.md', lambda t: t.replace('Who owns', 'Who really owns')),
                           ('source.txt', lambda t: t + '\nAn appended line that was never fetched.')):
            path = out / name
            original = path.read_text(encoding='utf-8')
            path.write_text(edit(original), encoding='utf-8')
            with self.subTest(tampered=name), self.assertRaises(ValueError):
                workflow.verify_run(out)
            path.write_text(original, encoding='utf-8')

    def test_prompt_reaches_agent_as_exact_utf8(self):
        # Regression for the first live run: the prompt was encoded with the Windows code page
        # and the planner never started. Characters outside cp1252 and the newlines must arrive
        # byte-for-byte (text mode on Windows also turned "\n" into "\r\n").
        prompt = 'Quote: They didn’t want ‘cowritten by Claude’ — ✓ → Fürth\n<source>\nx\n</source>'
        workflow.run_agent('planner', prompt, workflow.PLANNER_SCHEMA)
        self.assertEqual(bytes.fromhex(self.calls()[0]['prompt_utf8_hex']), prompt.encode('utf-8'))

    def test_tool_use_in_agent_session_fails_closed(self):
        self.plan(planner_tools=['command_execution'])
        with self.assertRaises(workflow.StepError) as caught:
            workflow.run(self.dir / 'run')
        self.assertIn('command_execution', str(caught.exception))
        record = json.loads((self.dir / 'run' / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual((record['status'], record['stage']), ('failed', 'planner'))
        self.assertEqual(record['planner']['item_types']['command_execution'], 1)
        self.assertFalse((self.dir / 'run' / 'brief.md').exists())

    def test_session_without_events_cannot_be_trusted(self):
        self.plan(silent=True)
        with self.assertRaisesRegex(workflow.StepError, 'no agent_message event'):
            workflow.run(self.dir / 'run')

    def test_reviewer_keeping_nothing_stops_with_a_record(self):
        workflow.run(self.dir / 'run')  # an earlier successful run in the same directory
        self.plan(reviewer={'decisions': [dict(d, verdict='drop') for d in REVIEW]})
        with self.assertRaisesRegex(ValueError, 'kept no ideas'):
            workflow.run(self.dir / 'run')
        record = json.loads((self.dir / 'run' / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual([d['verdict'] for d in record['decisions']], ['drop', 'drop', 'drop'])
        self.assertFalse((self.dir / 'run' / 'brief.md').exists())

    def test_rubber_stamp_reviewer_is_caught_by_the_control(self):
        self.plan(reviewer={'decisions': [dict(d, verdict='keep') for d in REVIEW]})
        with self.assertRaisesRegex(ValueError, 'control idea'):
            workflow.run(self.dir / 'run')
        record = json.loads((self.dir / 'run' / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual((record['stage'], record['control']['dropped']), ('review_contract', False))
        self.assertEqual(len(record['decisions']), 3)
        self.assertFalse((self.dir / 'run' / 'brief.md').exists())


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.ideas = workflow.gate(IDEAS, SOURCE)[0]

    def test_reviewer_cannot_add_skip_repeat_or_rewrite(self):
        bad = {'unknown id': DECISIONS + [dict(DECISIONS[0], id='i9')],
               'skipped id': DECISIONS[:1],
               'repeated id': DECISIONS + [DECISIONS[0]],
               'invalid verdict': [dict(DECISIONS[0], verdict='maybe'), DECISIONS[1]],
               'link in reason': [dict(DECISIONS[0], reason='See https://example.com'), DECISIONS[1]],
               'invented overlap': [dict(DECISIONS[0], overlap_evidence='A guide the page never lists'), DECISIONS[1]]}
        for name, decisions in bad.items():
            with self.subTest(name), self.assertRaises(ValueError):
                workflow.apply_review(self.ideas, decisions, SOURCE)
        rewritten = [dict(DECISIONS[0], title='A rewritten title'), DECISIONS[1]]
        kept, _ = workflow.apply_review(self.ideas, rewritten, SOURCE)
        self.assertEqual(kept[0]['title'], 'Who owns the judgment when agents do the work')

    def test_control_idea_pairs_a_real_quote_with_an_invented_result(self):
        control = workflow.control_idea(SOURCE, self.ideas, 4)
        self.assertIsNone(workflow.check_item(control, workflow.normalise(SOURCE)))  # passes the evidence gate
        self.assertNotIn(control['evidence'], [i['evidence'] for i in self.ideas])
        figure = re.search(r'\d+%', control['angle']).group()
        self.assertNotIn(figure, SOURCE)
        with self.assertRaises(ValueError):
            workflow.control_idea('too short', self.ideas, 4)

    def test_overlap_must_be_quoted_from_the_page(self):
        decisions = [dict(DECISIONS[0], overlap_evidence='Bosses Credit AI Instead of Employees'), DECISIONS[1]]
        kept, recorded = workflow.apply_review(self.ideas, decisions, SOURCE)
        self.assertEqual(kept[0]['overlap_evidence'], 'Bosses Credit AI Instead of Employees')
        self.assertEqual(recorded[0]['overlap_evidence'], 'Bosses Credit AI Instead of Employees')

    def test_gate_rejects_one_bad_idea_without_discarding_the_rest(self):
        good = IDEAS[0]
        cases = {'link in title': dict(good, title='Read https://example.com first'),
                 'markup in angle': dict(good, angle='<img src=x> tracking pixel'),
                 'quote too long': dict(good, evidence='x' * 301),
                 'straight apostrophe': dict(good, evidence='They didn\'t want their best contributions footnoted'),
                 'repeated evidence': dict(IDEAS[2], title='Same quote, new title')}
        for name, item in cases.items():
            with self.subTest(name):
                accepted, rejected = workflow.gate([IDEAS[2], item], SOURCE)
                self.assertEqual([i['id'] for i in accepted], ['i1'])
                self.assertEqual(rejected[0]['index'], 2)

    def test_redirects_must_stay_on_https_allowlisted_hosts(self):
        self.assertEqual(workflow.check_url('https://www.prommer.net:443/x'), 'https://www.prommer.net:443/x')
        for url in ('http://prommer.net/', 'https://prommer.net.example.com/', 'https://example.com/?u=prommer.net',
                    'https://prommer.net@example.com/'):
            with self.subTest(url), self.assertRaises(ValueError):
                workflow.check_url(url)


if __name__ == '__main__':
    unittest.main()
