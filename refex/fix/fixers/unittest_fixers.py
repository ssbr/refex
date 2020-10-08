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
"""Fixers for unit test specific logic.

* assertions: assertTrue(arg) and assertFalse(arg) give very poor error messages
  compared to methods like assertEqual, assertNotEqual, etc.  These fixers
  change the calls to the more specific assertion methods, without changing
  behavior at all.
* Deprecated unittest assertion aliases are replaced with the newer variants.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals  # for convenience

from refex import future_string
from refex.fix import fixer
from refex.python import syntactic_template
from refex.python.matchers import syntax_matchers


def assert_alias_fixer(old_expr, new_expr):
  """Fixer for deprecated unittest aliases.

  Args:
    old_expr: A string for an ExprPattern matching the target expr.
    new_expr: A string for a PythonExprTemplate to replace it with.

  Returns:
    A fixer that replaces old_expr with new_expr.
  """
  dotdotdot = fixer.ImmutableDefaultDict(lambda _: '...')
  return fixer.SimplePythonFixer(
      message=('{old} is a deprecated alias for {new} in the unittest module.'
               .format(
                   old=future_string.Template(old_expr).substitute(dotdotdot),
                   new=future_string.Template(new_expr).substitute(dotdotdot))),
      matcher=syntax_matchers.ExprPattern(old_expr),
      replacement=syntactic_template.PythonExprTemplate(new_expr),
      url='https://docs.python.org/3/library/unittest.html#deprecated-aliases',
      significant=False,
      category='pylint.g-deprecated-assert',
  )


def assert_message_fixer(old_expr, new_expr, method):
  """Fixer for assertTrue()/assertFalse()/etc.

  related error fixes.

  assertTrue(...) often produces less readable error information than
  alternative methods like assertEqual etc.

  Args:
    old_expr: a ExprPattern string for the expr to match
    new_expr: a template string for the replacement
    method: the method to link to in the unittest docs.

  Returns:
    A fixer that replaces old_expr with new_expr.
  """
  dotdotdot = fixer.ImmutableDefaultDict(lambda _: '...')
  return fixer.SimplePythonFixer(
      message=('%s will give more detailed error information than %s.' %
               (future_string.Template(new_expr).substitute(dotdotdot),
                future_string.Template(old_expr).substitute(dotdotdot))),
      matcher=syntax_matchers.ExprPattern(old_expr),
      replacement=syntactic_template.PythonExprTemplate(new_expr),
      url=(
          'https://docs.python.org/3/library/unittest.html#unittest.TestCase.%s'
          % method),
      category='pylint.g-generic-assert',
  )


SIMPLE_PYTHON_FIXERS = [
    # Deprecated alias fixers:
    assert_alias_fixer('self.failUnlessEqual', 'self.assertEqual'),
    assert_alias_fixer('self.assertEquals', 'self.assertEqual'),
    assert_alias_fixer('self.failIfEqual', 'self.assertNotEqual'),
    assert_alias_fixer('self.assertNotEquals', 'self.assertNotEqual'),
    assert_alias_fixer('self.assert_', 'self.assertTrue'),
    assert_alias_fixer('self.failUnless', 'self.assertTrue'),
    assert_alias_fixer('self.failIf', 'self.assertFalse'),
    assert_alias_fixer('self.failUnlessRaises', 'self.assertRaises'),
    assert_alias_fixer('self.failUnlessAlmostEqual', 'self.assertAlmostEqual'),
    assert_alias_fixer('self.assertAlmostEquals', 'self.assertAlmostEqual'),
    assert_alias_fixer('self.failIfAlmostEqual', 'self.assertNotAlmostEqual'),
    assert_alias_fixer('self.assertNotAlmostEquals',
                       'self.assertNotAlmostEqual'),

    # Assertion message fixers:
    # assertFalse(...) is excluded for now because will change which method is
    # called -- for example, if you're specifically testing your implementation
    # of __ne__, switching to assertEqual would be a bad move.

    # ==, !=
    assert_message_fixer('self.assertTrue($lhs == $rhs)',
                         'self.assertEqual($lhs, $rhs)', 'assertEqual'),
    assert_message_fixer('self.assertTrue($lhs != $rhs)',
                         'self.assertNotEqual($lhs, $rhs)', 'assertNotEqual'),
    assert_message_fixer('self.assertTrue($lhs == $rhs)',
                         'self.assertEqual($lhs, $rhs)', 'assertEqual'),
    assert_message_fixer('self.assertTrue($lhs != $rhs)',
                         'self.assertNotEqual($lhs, $rhs)', 'assertNotEqual'),

    # is, is not
    # We could also change 'assertIs(..., None)' to 'assertIsNone(...)',
    # but the error messages are identical, so this suggestion would
    # just be a waste of programmer time and code churn.
    assert_message_fixer('self.assertTrue($lhs is $rhs)',
                         'self.assertIs($lhs, $rhs)', 'assertIs'),
    assert_message_fixer('self.assertTrue($lhs is not $rhs)',
                         'self.assertIsNot($lhs, $rhs)', 'assertIsNot'),
    assert_message_fixer('self.assertFalse($lhs is $rhs)',
                         'self.assertIsNot($lhs, $rhs)', 'assertIsNot'),
    assert_message_fixer('self.assertFalse($lhs is not $rhs)',
                         'self.assertIs($lhs, $rhs)', 'assertIs'),

    # in, not in
    assert_message_fixer('self.assertTrue($lhs in $rhs)',
                         'self.assertIn($lhs, $rhs)', 'assertIn'),
    assert_message_fixer('self.assertTrue($lhs not in $rhs)',
                         'self.assertNotIn($lhs, $rhs)', 'assertNotIn'),
    assert_message_fixer('self.assertFalse($lhs in $rhs)',
                         'self.assertNotIn($lhs, $rhs)', 'assertNotIn'),
    assert_message_fixer('self.assertFalse($lhs not in $rhs)',
                         'self.assertIn($lhs, $rhs)', 'assertIn'),

    # <, <=, >, >=
    assert_message_fixer('self.assertTrue($lhs > $rhs)',
                         'self.assertGreater($lhs, $rhs)', 'assertGreater'),
    assert_message_fixer('self.assertTrue($lhs >= $rhs)',
                         'self.assertGreaterEqual($lhs, $rhs)',
                         'assertGreaterEqual'),
    assert_message_fixer('self.assertTrue($lhs < $rhs)',
                         'self.assertLess($lhs, $rhs)', 'assertLess'),
    assert_message_fixer('self.assertTrue($lhs <= $rhs)',
                         'self.assertLessEqual($lhs, $rhs)', 'assertLessEqual'),

    # isinstance
    assert_message_fixer('self.assertTrue(isinstance($lhs, $rhs))',
                         'self.assertIsInstance($lhs, $rhs)',
                         'assertIsInstance'),
    assert_message_fixer('self.assertTrue(not isinstance($lhs, $rhs))',
                         'self.assertNotIsInstance($lhs, $rhs)',
                         'assertNotIsInstance'),
    assert_message_fixer('self.assertFalse(isinstance($lhs, $rhs))',
                         'self.assertNotIsInstance($lhs, $rhs)',
                         'assertNotIsInstance'),
    assert_message_fixer('self.assertFalse(not isinstance($lhs, $rhs))',
                         'self.assertIsInstance($lhs, $rhs)',
                         'assertIsInstance'),

    # TODO: assertLen and other absltest methods.
    # Those are slightly more complicated because we must check whether or not
    # the test even _is_ an absltest.
]
