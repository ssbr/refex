# Copyright 2021 Google LLC
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
"""Tests for refex.examples.example_custom_matcher."""

from absl.testing import absltest

from refex import search
from refex.examples import example_custom_matcher
from refex.python import syntactic_template


class SumMatcherTest(absltest.TestCase):
  SEARCH_REPLACE = search.PyExprRewritingSearcher.from_matcher(
      example_custom_matcher.SumMatcher(),
      {search.ROOT_LABEL: syntactic_template.PythonExprTemplate('$sum')},
  )

  def test_sum_rewrite(self):
    self.assertEqual(
        search.rewrite_string(self.SEARCH_REPLACE, '1 + 2 + 3', 'filename.py'),
        '6')

  def test_sum_no_rewrite(self):
    self.assertEqual(
        search.rewrite_string(self.SEARCH_REPLACE, '1 + var', 'filename.py'),
        '1 + var')


if __name__ == '__main__':
  absltest.main()
