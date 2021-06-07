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
"""Tests for refex.python.python_pattern."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tokenize

from absl.testing import absltest
from absl.testing import parameterized

from refex.python import python_pattern


class PythonPatternTest(parameterized.TestCase):

  @parameterized.parameters('', 'x', 'x y')
  def test_simple_nonpattern(self, pattern):
    tokenized, _ = python_pattern.token_pattern(pattern)
    self.assertEqual(tokenize.untokenize(tokenized), pattern)

  @parameterized.parameters('$x', 'foo + $x', 'import $x', '$x "$y"', '$x = 0')
  def test_simple_pattern(self, pattern):
    tokenized, [metavar_i] = python_pattern.token_pattern(pattern)
    # token text is 'x' -- that's the only variable in the pattern.
    self.assertEqual(tokenized[metavar_i][1], 'x')
    # it round trips to the same string except $x -> x
    self.assertEqual(tokenize.untokenize(tokenized), pattern.replace('$x', 'x'))

  @parameterized.parameters('$1', '$', '$\n', '$[', '$""', '$ x', '$\nx')
  def test_syntax_error(self, pattern):
    with self.assertRaises(SyntaxError):
      python_pattern.token_pattern(pattern)


if __name__ == '__main__':
  absltest.main()
