# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for refex.search."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import re

from absl.testing import absltest
from absl.testing import parameterized

from refex import formatting
from refex import parsed_file
from refex import search
from refex.fix import fixer
from refex.python import matcher
from refex.python import syntactic_template
from refex.python.matchers import syntax_matchers


class ExcludedRangesTest(parameterized.TestCase):
  """Tests range exclusion pragmas, using Python for convenience."""

  @parameterized.parameters(
      '\nhello # pylint: disable=foo',
      '\nhello # refex: disable=pylint.foo',
  )
  def test_correct_offset(self, source):
    parsed_file = matcher.parse_ast(source)
    # the covered range is everything but the first byte (a newline)
    self.assertEqual(
        search._pragma_excluded_ranges(parsed_file),
        {'pylint.foo': [(1, len(source))]})

  def test_bad_tag(self):
    parsed_file = matcher.parse_ast(' # foo: disable=bar')
    self.assertEqual(search._pragma_excluded_ranges(parsed_file), {})


class TrimRemovedStatementsTest(parameterized.TestCase):

  @parameterized.parameters(
      # Module emptying.
      ('0xbad', ''),
      ('0xbad; 0xbad;', ''),
      ('0xbad\n0xbad;', ''),
      # Suite emptying.
      ('if 1: 0xbad', 'if 1: pass'),
      ('if 1: 0xbad;', 'if 1: pass;'),
      ('if 1:\n 0xbad', 'if 1:\n pass'),
      ('if 1:\n 0xbad\n 0xbad', 'if 1:\n pass'),
      ('if 1:\n 0xbad; 0xbad;', 'if 1:\n pass'),
      # Module prefix collapse.
      ('0xbad;\n2', '2'),
      ('0xbad; 2;', '2;'),
      ('0xbad;\n2', '2'),
      ('0xbad;\n2;', '2;'),
      # NOTE: Replacements ending a suite will strip off the semicolon.
      ('2; 0xbad', '2'),
      ('2; 0xbad;', '2'),
      # Suite prefix collapse.
      ('if 1: 0xbad; 2', 'if 1: 2'),
      ('if 1:\n 0xbad; 2', 'if 1:\n 2'),
      ('if 1:\n 0xbad\n 2', 'if 1:\n 2'),
      ('if 1:\n 0xbad\n 2', 'if 1:\n 2'),
      # Suite multi-statement collapse.
      ('if 1: 2; 0xbad; 3;', 'if 1: 2; 3;'),
      ('if 1:\n 2; 0xbad\n 3', 'if 1:\n 2; 3'),
      ('if 1:\n 0xbad; 2\n 3', 'if 1:\n 2\n 3'),
      ('if 1:\n 2; 0xbad; 3', 'if 1:\n 2; 3'),
      ('if 1: 0xbad; 0xbad; 2', 'if 1: 2'),
      ('if 1:\n 0xbad; 2\n 0xbad;', 'if 1:\n 2'),
      # NOTE: Adjacent replacements ending a suite cause excess whitespace.
      ('if 1:\n 2\n 0xbad\n 0xbad', 'if 1:\n 2\n '),
      ('if 1: 2; 0xbad; 0xbad; 0xbad', 'if 1: 2; '),
      ('if 1: 0xbad; 2; 0xbad; 0xbad', 'if 1: 2; '),
      # Adjacent comment behavior.
      ('0xbad  #trailing', '  #trailing'),
      ('#block\n0xbad', '#block\n'),
      ('#block\n0xbad\n2', '#block\n2'),
      ('2;  #trailing\n0xbad\n3', '2;  #trailing\n3'),
      # NOTE: Replacements ending a suite will strip off preceding comments.
      ('2  #trailing\n0xbad', '2'),
      ('2\n #block\n0xbad', '2'),
      # Other suite types.
      ('if 1: pass\nelse: 0xbad', 'if 1: pass\nelse: pass'),
      ('for _ in []: 0xbad', 'for _ in []: pass'),
      ('while 1: 0xbad', 'while 1: pass'),
      ('with 1: 0xbad', 'with 1: pass'),
  )
  def test_single_statement(self, before, after):
    searcher = search.PyStmtRewritingSearcher.from_pattern(
        '0xbad',
        {search.ROOT_LABEL: syntactic_template.PythonTemplate('')})
    substitutions = list(search.find_iter(searcher, before, 'a.py'))
    self.assertEqual(after,
                     formatting.apply_substitutions(before, substitutions))


class RewriteStringTest(absltest.TestCase):

  def test_replace(self):
    fix = fixer.SimplePythonFixer(
        matcher=syntax_matchers.ExprPattern('$obj.attr'),
        replacement=syntactic_template.PythonTemplate(u'$obj.other'),
    )

    source = 'my_obj.attr + other_obj.attr'
    self.assertEqual('my_obj.other + other_obj.other',
                     search.rewrite_string(fix, source, 'example.py'))


def _sub_string(s, sub):
  start, end = sub.primary_span
  return s[start:end]


def _sub_strings(s, subs):
  return [_sub_string(s, sub) for  sub in subs]


class CombinedSearcherTest(parameterized.TestCase):

  @parameterized.parameters(
      search.RegexSearcher.from_pattern('x', None),
      search.PyExprRewritingSearcher.from_pattern('x', None),
  )
  def test_compatible_searchers(self, x_searcher):
    src = 'x, y'
    searcher = search.CombinedSearcher([
        x_searcher,
        search.RegexSearcher.from_pattern('y', None),
    ])

    self.assertEqual(
        _sub_strings(src, search.find_iter(searcher, src, '<string>')),
        ['x', 'y'],
    )

  def test_incompatible_searchers(self):

    class IncompatibleParsedFile(parsed_file.ParsedFile):
      pass

    class IncompatibleSearcher(search.RegexSearcher):

      def parse(self, data, filename):
        return IncompatibleParsedFile(data, filename)

  def test_approximate_regex(self):
    searcher = search.CombinedSearcher([
        search.RegexSearcher.from_pattern('x', None),
        search.RegexSearcher.from_pattern('y', None),
    ])

    self.assertEqual(searcher.approximate_regex(), '(?:x)|(?:y)')
    # doesn't crash
    re.compile(searcher.approximate_regex())

  def test_null_approximate_regex(self):
    searcher = search.CombinedSearcher([
        search.PyExprRewritingSearcher.from_pattern('x', None),
        search.RegexSearcher.from_pattern('y', None),
    ])

    self.assertIsNone(searcher.approximate_regex())


if __name__ == '__main__':
  absltest.main()
