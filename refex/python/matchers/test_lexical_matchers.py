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
"""Tests for refex.python.matchers.lexical_matchers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest

from refex.python import matcher_test_util
from refex.python.matchers import ast_matchers
from refex.python.matchers import lexical_matchers
from refex.python.matchers import syntax_matchers


class NoCommentsTest(matcher_test_util.MatcherTestCase):
  _comments_source = '(a # comment\n + b)'
  _nocomments_source = '(a + b)'
  _including_comments_matcher = syntax_matchers.StmtPattern('a + b')
  _requiring_comments_matcher = lexical_matchers.HasComments(
      _including_comments_matcher)
  _banning_comments_matcher = lexical_matchers.NoComments(
      _including_comments_matcher)

  def test_outside_comment_irrelevant(self):
    for prefix in ['', '# earlier comment\n']:
      for suffix in ['', '  # trailing comment']:
        source_code = prefix + self._nocomments_source + suffix
        for m in [
            self._including_comments_matcher, self._requiring_comments_matcher,
            self._banning_comments_matcher
        ]:
          with self.subTest(source_code=source_code, matcher=m):
            self.assertEqual(
                self.get_all_match_strings(m, source_code),
                self.get_all_match_strings(m, self._nocomments_source))

  def test_interior_comments(self):
    for m in [
        self._including_comments_matcher, self._requiring_comments_matcher
    ]:
      with self.subTest(matcher=m):
        self.assertEqual(
            self.get_all_match_strings(m, self._comments_source),
            [self._comments_source])
    for m in [self._banning_comments_matcher]:
      with self.subTest(matcher=m):
        self.assertEqual(
            self.get_all_match_strings(m, self._comments_source), [])

  def test_no_interior_comments(self):
    for m in [self._requiring_comments_matcher]:
      with self.subTest(matcher=m):
        self.assertEqual(
            self.get_all_match_strings(m, self._nocomments_source), [])
    for m in [self._including_comments_matcher, self._banning_comments_matcher]:
      with self.subTest(matcher=m):
        self.assertEqual(
            self.get_all_match_strings(m, self._nocomments_source),
            [self._nocomments_source])

  def test_incorrect_match_type(self):
    nonlexical_matcher = ast_matchers.Add()
    for m in [
        lexical_matchers.NoComments(nonlexical_matcher),
        lexical_matchers.HasComments(nonlexical_matcher)
    ]:
      with self.subTest(matcher=m):
        with self.assertRaises(TypeError):
          self.get_all_match_strings(m, 'a + b')


if __name__ == '__main__':
  absltest.main()
