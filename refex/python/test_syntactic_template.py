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
"""Tests for refex.python.syntactic_template."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from absl.testing import absltest
from absl.testing import parameterized
import six

from refex import formatting
from refex.python import matcher
from refex.python import syntactic_template
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers


class LexicalTemplateTest(parameterized.TestCase):

  @parameterized.parameters('', 'y', '"', '#')
  def test_substitute(self, replacement):
    """Tests substitutions, as either the template or a substituted-in variable."""
    for template in ['$x', replacement]:
      with self.subTest(template=template):
        replaced = syntactic_template._LexicalTemplate(template).substitute(
            {'x': replacement})
        self.assertIsInstance(replaced, six.text_type)
        self.assertEqual(replaced, replacement)

  @parameterized.parameters('$ $ $', '\t', ' ')
  def test_substitute_nontemplate(self, replacement):
    """Tests substitution which don't work as templates."""
    replaced = syntactic_template._LexicalTemplate('$x').substitute(
        {'x': replacement})
    self.assertIsInstance(replaced, six.text_type)
    self.assertEqual(replaced, replacement)

  def test_missing_parameter(self):
    with self.assertRaises(KeyError):
      syntactic_template._LexicalTemplate('$x').substitute({})

  def test_extra_parameter(self):
    self.assertEqual(
        syntactic_template._LexicalTemplate('$x').substitute({
            'x': 'v1',
            'y': 'v2'
        }), 'v1')

  @parameterized.parameters('"$y"', '# y')
  def test_substitute_nonprogram(self, template):
    """Substitution doesn't affect the contents of strings or comments."""
    self.assertNotIn(
        'BAD',
        syntactic_template._LexicalTemplate(template).substitute({
            'y': 'BAD',
        }))

  def test_x_eq_x(self):
    self.assertEqual(
        syntactic_template._LexicalTemplate('$x = $x').substitute({'x': '(a)'}),
        '(a) = (a)', str(syntactic_template._LexicalTemplate('$x = $x')))


class PythonTemplateTest(parameterized.TestCase):

  @parameterized.parameters('f("$x")', 'f("$current_expr")')
  def test_nonpython_dollars_source(self, src):
    parsed = matcher.parse_ast(src)
    m = base_matchers.Bind('bound', ast_matchers.Call())
    [matchinfo] = matcher.find_iter(m, parsed)
    self.assertEqual(
        src,
        syntactic_template.PythonExprTemplate('$bound').substitute_match(
            parsed, matchinfo.match, {'bound': matchinfo.match}))

  def test_nonpython_dollars_dest(self):
    src = 'f'
    parsed = matcher.parse_ast(src)
    m = base_matchers.Bind('bound', ast_matchers.Name())
    [matchinfo] = matcher.find_iter(m, parsed)
    self.assertEqual(
        'f("$x")',
        syntactic_template.PythonExprTemplate('$bound("$x")').substitute_match(
            parsed, matchinfo.match, {'bound': matchinfo.match}))

  @parameterized.parameters(('x', set()), ('$a + $b', {'a', 'b'}))
  def test_variables(self, template, expected_variables):
    self.assertEqual(
        syntactic_template.PythonExprTemplate(template).variables,
        expected_variables)

  def test_empty_expr(self):
    with self.assertRaises(ValueError):
      syntactic_template.PythonExprTemplate('')

  def test_empty_stmt(self):
    with self.assertRaises(ValueError):
      syntactic_template.PythonStmtTemplate('')

  @parameterized.parameters('', 'a; b')
  def test_nonsingular_py_ok(self, template):
    """Tests non-singular PythonTemplate in a context where it's acceptable.

    If it is not being placed into a context where it's expected to parse as
    an expression, then '' and even 'a; b' are fine.

    Args:
      template: the template for this test.
    """
    parsed = matcher.parse_ast('x')
    m = base_matchers.Bind('bound', ast_matchers.Name())
    [matchinfo] = matcher.find_iter(m, parsed)
    self.assertEqual(
        template,
        syntactic_template.PythonTemplate(template).substitute_match(
            parsed, matchinfo.match, {'bound': matchinfo.match}))

  @parameterized.parameters(
      syntactic_template.PythonTemplate(''),
      syntactic_template.PythonTemplate('a; b'),
      syntactic_template.PythonTemplate('pass'),
      syntactic_template.PythonStmtTemplate('pass'))
  def test_nonexpr_in_expr_context(self, template):
    parsed = matcher.parse_ast('[x]')
    m = base_matchers.Bind('bound', ast_matchers.Name())
    [matchinfo] = matcher.find_iter(m, parsed)
    with self.assertRaises(formatting.RewriteError):
      template.substitute_match(parsed, matchinfo.match,
                                {'bound': matchinfo.match})


class PythonStmtTemplateTest(parameterized.TestCase):

  @parameterized.parameters(
      '$x = $x',
      'a, $x = $x',
      '(a, $x) = $x',
      '[a, $x] = $x',
      '$x.foo = $x',
  )
  def test_assignment(self, template):
    template = syntactic_template.PythonStmtTemplate(template)
    # Test with different values of `ctx` for the variable being substituted.
    for variable_source in 'a = 1', 'a':
      with self.subTest(variable_souce=variable_source):
        [matchinfo] = matcher.find_iter(
            base_matchers.Bind('x', ast_matchers.Name()),
            matcher.parse_ast(variable_source))
        substituted = template.substitute_match(None, None,
                                                {'x': matchinfo.match})
        self.assertEqual(substituted, template.template.replace('$x', 'a'))

if __name__ == '__main__':
  absltest.main()
