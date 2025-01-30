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

import string

from refex.fix import fixer
from refex.python import syntactic_template
from refex.python.matchers import syntax_matchers


def assert_alias_fixer(
    old_expr,
    new_expr,
    url='https://docs.python.org/3/library/unittest.html#deprecated-aliases'):
  """Fixer for deprecated unittest aliases.

  Args:
    old_expr: A string for an ExprPattern matching the target expr.
    new_expr: A string for a PythonExprTemplate to replace it with.
    url: The URL documenting the deprecation.

  Returns:
    A fixer that replaces old_expr with new_expr.
  """
  dotdotdot = fixer.ImmutableDefaultDict(lambda _: '...')
  return fixer.SimplePythonFixer(
      message=('{old} is a deprecated alias for {new} in the unittest module.'
               .format(
                   old=string.Template(old_expr).substitute(dotdotdot),
                   new=string.Template(new_expr).substitute(dotdotdot))),
      matcher=syntax_matchers.ExprPattern(old_expr),
      replacement=syntactic_template.PythonExprTemplate(new_expr),
      url=url,
      significant=False,
      category='pylint.g-deprecated-assert',
  )


def assert_message_fixer(old_expr, new_expr, method, is_absl=False):
  """Fixer for assertTrue()/assertFalse()/etc.

  related error fixes.

  assertTrue(...) often produces less readable error information than
  alternative methods like assertEqual etc.

  Args:
    old_expr: a ExprPattern string for the expr to match
    new_expr: a template string for the replacement
    method: the method to link to in the docs.
    is_absl: Whether this is an absl method with absl docs.

  Returns:
    A fixer that replaces old_expr with new_expr.
  """
  if is_absl:
    # absl doesn't have docs per se.
    url = f'https://github.com/abseil/abseil-py/search?q=%22def+{method}%22'
  else:
    url = f'https://docs.python.org/3/library/unittest.html#unittest.TestCase.{method}'
  dotdotdot = fixer.ImmutableDefaultDict(lambda _: '...')
  return fixer.SimplePythonFixer(
      message=(
          '%s is a more specific assertion, and may give more detailed error information than %s.'
          % (string.Template(new_expr).substitute(dotdotdot),
             string.Template(old_expr).substitute(dotdotdot))),
      matcher=syntax_matchers.ExprPattern(old_expr),
      replacement=syntactic_template.PythonExprTemplate(new_expr),
      url=url,
      category='pylint.g-generic-assert',
  )


SIMPLE_PYTHON_FIXERS = [
    # failUnlessEqual etc. are really REALLY gone in 3.12, so if you haven't
    # fixed it by now, it's too late!
    # The only deprecated aliases left of any interest are ones defined by
    # absltest as a compatibility shim.
    assert_alias_fixer(
        'self.assertItemsEqual',
        'self.assertCountEqual',
        url='https://docs.python.org/2/library/unittest.html#unittest.TestCase.assertItemsEqual',
    ),
    # Assertion message fixers:
    # assertFalse(...) is excluded for now because will change which method is
    # called -- for example, if you're specifically testing your implementation
    # of __ne__, switching to assertEqual would be a bad move.
    # ==, !=
    assert_message_fixer(
        'self.assertTrue($lhs == $rhs)',
        'self.assertEqual($lhs, $rhs)',
        'assertEqual',
    ),
    assert_message_fixer(
        'self.assertTrue($lhs != $rhs)',
        'self.assertNotEqual($lhs, $rhs)',
        'assertNotEqual',
    ),
    assert_message_fixer(
        'self.assertTrue($lhs == $rhs)',
        'self.assertEqual($lhs, $rhs)',
        'assertEqual',
    ),
    assert_message_fixer(
        'self.assertTrue($lhs != $rhs)',
        'self.assertNotEqual($lhs, $rhs)',
        'assertNotEqual',
    ),
    # is, is not
    # We could also change 'assertIs(..., None)' to 'assertIsNone(...)',
    # but the error messages are identical, so this suggestion would
    # just be a waste of programmer time and code churn.
    assert_message_fixer(
        'self.assertTrue($lhs is $rhs)', 'self.assertIs($lhs, $rhs)', 'assertIs'
    ),
    assert_message_fixer(
        'self.assertTrue($lhs is not $rhs)',
        'self.assertIsNot($lhs, $rhs)',
        'assertIsNot',
    ),
    assert_message_fixer(
        'self.assertFalse($lhs is $rhs)',
        'self.assertIsNot($lhs, $rhs)',
        'assertIsNot',
    ),
    assert_message_fixer(
        'self.assertFalse($lhs is not $rhs)',
        'self.assertIs($lhs, $rhs)',
        'assertIs',
    ),
    # in, not in
    assert_message_fixer(
        'self.assertTrue($lhs in $rhs)', 'self.assertIn($lhs, $rhs)', 'assertIn'
    ),
    assert_message_fixer(
        'self.assertTrue($lhs not in $rhs)',
        'self.assertNotIn($lhs, $rhs)',
        'assertNotIn',
    ),
    assert_message_fixer(
        'self.assertFalse($lhs in $rhs)',
        'self.assertNotIn($lhs, $rhs)',
        'assertNotIn',
    ),
    assert_message_fixer(
        'self.assertFalse($lhs not in $rhs)',
        'self.assertIn($lhs, $rhs)',
        'assertIn',
    ),
    # <, <=, >, >=
    assert_message_fixer(
        'self.assertTrue($lhs > $rhs)',
        'self.assertGreater($lhs, $rhs)',
        'assertGreater',
    ),
    assert_message_fixer(
        'self.assertTrue($lhs >= $rhs)',
        'self.assertGreaterEqual($lhs, $rhs)',
        'assertGreaterEqual',
    ),
    assert_message_fixer(
        'self.assertTrue($lhs < $rhs)',
        'self.assertLess($lhs, $rhs)',
        'assertLess',
    ),
    assert_message_fixer(
        'self.assertTrue($lhs <= $rhs)',
        'self.assertLessEqual($lhs, $rhs)',
        'assertLessEqual',
    ),
    # isinstance
    assert_message_fixer(
        'self.assertTrue(isinstance($lhs, $rhs))',
        'self.assertIsInstance($lhs, $rhs)',
        'assertIsInstance',
    ),
    assert_message_fixer(
        'self.assertTrue(not isinstance($lhs, $rhs))',
        'self.assertNotIsInstance($lhs, $rhs)',
        'assertNotIsInstance',
    ),
    assert_message_fixer(
        'self.assertFalse(isinstance($lhs, $rhs))',
        'self.assertNotIsInstance($lhs, $rhs)',
        'assertNotIsInstance',
    ),
    assert_message_fixer(
        'self.assertFalse(not isinstance($lhs, $rhs))',
        'self.assertIsInstance($lhs, $rhs)',
        'assertIsInstance',
    ),
    # TODO: suggest assertLen, and other absltest methods.
    # Those are slightly more complicated because we must check whether or not
    # the test even _is_ an absltest.
    # However, if we're already using one abslTest method, we can suggest
    # another:
    assert_message_fixer(
        'self.assertLen($x, 0)',
        'self.assertEmpty($x)',
        'assertEmpty',
        is_absl=True,
    ),
]
