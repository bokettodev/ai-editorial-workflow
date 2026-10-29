import unittest

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


if __name__ == '__main__':
    unittest.main()
