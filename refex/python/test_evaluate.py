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
"""Tests for refex.py.evaluate."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest

from refex.python import evaluate
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers


class EvaluateTest(absltest.TestCase):

  def test_base_matchers(self):
    for expr in ['base_matchers.Anything()', 'Anything()']:
      with self.subTest(expr=expr):
        self.assertEqual(
            evaluate.compile_matcher(expr), base_matchers.Anything())

  def test_ast_matchers(self):
    for expr in ['ast_matchers.Name()', 'Name()']:
      with self.subTest(expr=expr):
        self.assertEqual(evaluate.compile_matcher(expr), ast_matchers.Name())

  def test_syntax_matchers(self):
    for expr in ["syntax_matchers.ExprPattern('$bar')", "ExprPattern('$bar')"]:
      with self.subTest(expr=expr):
        self.assertEqual(
            evaluate.compile_matcher(expr), syntax_matchers.ExprPattern('$bar'))

  def test_whitespace(self):
    """Whitespace should be ignored to let people pretty-print their inputs."""
    self.assertEqual(
        evaluate.compile_matcher("""
            _
        """), base_matchers.Anything())


if __name__ == '__main__':
  absltest.main()
