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
"""Base class and test-only utilities for testing matchers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest

from refex.python import matcher


class MatcherTestCase(absltest.TestCase):

  def _get_match_string(self, match, source_code):
    if not match.span:
      self.fail("%r is not a lexical match, and so doesn't match"
                ' substrings of the source code' % (match,))
    return source_code[slice(*match.span)]

  def _get_matchinfo_string(self, matchinfo, source_code):
    if matchinfo is None:
      self.fail('Failed to match')
    self.assertIsInstance(matchinfo, matcher.MatchInfo)
    return self._get_match_string(matchinfo.match, source_code)

  def get_all_match_strings(self, m, source_code):
    return [
        self._get_matchinfo_string(matchinfo, source_code)
        for matchinfo in matcher.find_iter(
            m, matcher.parse_ast(source_code, '<string>'))
    ]


def empty_context():
  """Returns a new match context for some empty file.

  The return value is suitable for use with matchers, e.g.:

    >>> from refex.python.matchers import base_matchers
    >>> base_matchers.Anything().match(empty_context(), object())
    MatchInfo(...)
  """
  return matcher.MatchContext(matcher.parse_ast(''))
