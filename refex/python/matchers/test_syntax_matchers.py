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

# python3 python2
"""Tests for refex.python.matchers.syntax_matchers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from unittest import mock
import textwrap
import unittest

from absl.testing import absltest
from absl.testing import parameterized
import six

from refex.python import matcher
from refex.python import matcher_test_util
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers

_FAKE_CONTEXT = matcher.MatchContext(matcher.parse_ast('', 'foo.py'))


class RemapMacroVariablesTest(absltest.TestCase):
  """Tests for the lower-level parsing of expressions.

  Higher level behavior is tested using the public API.
  """

  def test_error_eof(self):
    with self.assertRaises(SyntaxError):
      syntax_matchers._remap_macro_variables('$')

  def test_error_nonword(self):
    with self.assertRaises(SyntaxError):
      syntax_matchers._remap_macro_variables('$0')

  def test_error_spacing(self):
    with self.assertRaises(SyntaxError):
      raise Exception(syntax_matchers._remap_macro_variables('$ foo'))

  def test_error_spacing_line(self):
    with self.assertRaises(SyntaxError):
      raise Exception(syntax_matchers._remap_macro_variables('$\n foo'))

  def test_identity(self):
    self.assertEqual(
        syntax_matchers._remap_macro_variables('a + b'), ('a + b', {}))

  def test_remap(self):
    self.assertEqual(
        syntax_matchers._remap_macro_variables('a + $b'), ('a + gensym_b', {
            'b': 'gensym_b'
        }))

  def test_remap_twice(self):
    # But why would you _do_ this?
    self.assertEqual(
        syntax_matchers._remap_macro_variables('gensym_b + $b'),
        ('gensym_b + gensym0_b', {
            'b': 'gensym0_b'
        }))

  def test_remap_doesnt_eat_tokens(self):
    """Expanding the size of a variable mustn't eat into neighboring tokens."""
    self.assertEqual(
        syntax_matchers._remap_macro_variables('$a in b'),
        # Two different disasters are possible due to the way untokenize uses
        # columns to regenerate where things should go:
        # 1) eating whitespace: 'gensym_ain b'
        # 2) leavint the $ empty and causing a pahton indent: ' gensym_a in b'
        ('gensym_a in b', {
            'a': 'gensym_a'
        }))

  def test_remap_is_noninvasive(self):
    """Remapping is lexical and doesn't invade comments or strings."""
    for s in ('# $cash', '"$money"'):
      with self.subTest(s=s):
        self.assertEqual(syntax_matchers._remap_macro_variables(s), (s, {}))


class ExprPatternTest(matcher_test_util.MatcherTestCase):

  def test_nonname(self):
    with self.assertRaises(ValueError) as cm:
      syntax_matchers.ExprPattern('a.$x')
    self.assertIn('metavariable', str(cm.exception))

  def test_no_such_variable(self):
    with self.assertRaises(KeyError):
      syntax_matchers.ExprPattern('a', {'x': base_matchers.Anything()})

  def test_syntaxerror(self):
    with self.assertRaises(ValueError):
      syntax_matchers.ExprPattern('{')

  def test_no_statement(self):
    with self.assertRaises(ValueError):
      syntax_matchers.ExprPattern('')

  def test_no_expr(self):
    with self.assertRaises(ValueError):
      syntax_matchers.ExprPattern('x = 1')

  def test_multiple_statements(self):
    with self.assertRaises(ValueError):
      syntax_matchers.ExprPattern('{}; {}')

  def test_identical_patterns(self):
    """Tests that patterns match themselves when not parameterized.

    Many cases (e.g. None) are interesting for 2/3 compatibility, because the
    AST changes in Python 3. syntax_matchers gives an easy way to get
    cross-version compatibility.
    """
    for code in ['None', '{}', '[]', '{1:2, 3:4}', 'lambda a: a', '""']:
      parsed = matcher.parse_ast(code, '<string>')
      expr = parsed.tree.body[0].value
      for extra_comment in ['', "# comment doesn't matter"]:
        with self.subTest(code=code, extra_comment=extra_comment):
          self.assertEqual(
              syntax_matchers.ExprPattern(code + extra_comment).match(
                  matcher.MatchContext(parsed), expr),
              matcher.MatchInfo(
                  matcher.LexicalASTMatch(expr, parsed.text, expr.first_token,
                                          expr.last_token)))

  def test_dict_wrong_order(self):
    parsed = matcher.parse_ast('{1:2, 3:4}', '<string>')
    expr = parsed.tree.body[0].value
    self.assertIsNone(
        syntax_matchers.ExprPattern('{3:4, 1:2}').match(
            matcher.MatchContext(parsed), expr))

  def test_nonvariable_name_fails(self):
    """Names are only treated as variables, or anything weird, on request."""
    parsed = matcher.parse_ast('3', '<string>')
    expr = parsed.tree.body[0].value
    self.assertIsNone(
        syntax_matchers.ExprPattern('name').match(
            matcher.MatchContext(parsed), expr))

  def test_variable_name(self):
    parsed = matcher.parse_ast('3', '<string>')
    expr = parsed.tree.body[0].value
    expr_match = matcher.LexicalASTMatch(expr, parsed.text, expr.first_token,
                                         expr.last_token)
    self.assertEqual(
        syntax_matchers.ExprPattern('$name').match(
            matcher.MatchContext(parsed), expr),
        matcher.MatchInfo(expr_match, {'name': matcher.BoundValue(expr_match)}))

  def test_complex_variable(self):
    parsed = matcher.parse_ast('foo + bar', '<string>')
    expr = parsed.tree.body[0].value
    self.assertEqual(
        syntax_matchers.ExprPattern('foo + $name').match(
            matcher.MatchContext(parsed), expr),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(expr, parsed.text, expr.first_token,
                                    expr.last_token),
            bindings=mock.ANY))

  def test_restrictions(self):
    parsed = matcher.parse_ast('1\n2', '<string>')
    expr_match = parsed.tree.body[0].value
    expr_nomatch = parsed.tree.body[1].value
    m = syntax_matchers.ExprPattern('$name',
                                    {'name': syntax_matchers.ExprPattern('1')})
    self.assertIsNotNone(m.match(matcher.MatchContext(parsed), expr_match))
    self.assertIsNone(m.match(matcher.MatchContext(parsed), expr_nomatch))

  def test_repeated_variable(self):
    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.ExprPattern('$x + $x'),
            '1 + 1\n1 + 2\na + a\na + b'), ['1 + 1', 'a + a'])

  def test_variable_conflict(self):
    """Variables use the default conflict resolution outside of the pattern.

    Inside of the pattern, they use MERGE_EQUIVALENT_AST, but this is opaque to
    callers.
    """
    # The AllOf shouldn't make a difference, because the $x variable is just
    # a regular Bind() variable outside of the pattern, and merges via KEEP_LAST
    # per normal.
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                syntax_matchers.ExprPattern('$x'), base_matchers.Bind('x')),
            '1'), ['1'])


class StmtPatternTest(matcher_test_util.MatcherTestCase):

  def test_nonname(self):
    with self.assertRaises(ValueError) as cm:
      syntax_matchers.ExprPattern('import $x')
    self.assertIn('metavariables', str(cm.exception))

  def test_no_such_variable(self):
    with self.assertRaises(KeyError):
      syntax_matchers.StmtPattern('a', {'x': base_matchers.Anything()})

  def test_syntaxerror(self):
    with self.assertRaises(ValueError):
      syntax_matchers.StmtPattern('{')

  def test_no_statement(self):
    with self.assertRaises(ValueError):
      syntax_matchers.StmtPattern('')

  def test_multiple_statements(self):
    with self.assertRaises(ValueError):
      syntax_matchers.StmtPattern('{}; {}')

  def test_identical_patterns(self):
    """Tests that patterns match themselves when not parameterized.

    Many cases (e.g. None) are interesting for 2/3 compatibility, because the
    AST changes in Python 3. syntax_matchers gives an easy way to get
    cross-version compatibility.
    """
    for code in ['None', '{}', '[]', '{1:2, 3:4}', 'lambda a: a', '""', 'x=1']:
      parsed = matcher.parse_ast(code, '<string>')
      stmt = parsed.tree.body[0]
      for extra_comment in ['', "# comment doesn't matter"]:
        with self.subTest(code=code, extra_comment=extra_comment):
          self.assertEqual(
              syntax_matchers.StmtPattern(code + extra_comment).match(
                  matcher.MatchContext(parsed), stmt),
              matcher.MatchInfo(
                  matcher.LexicalASTMatch(stmt, parsed.text, stmt.first_token,
                                          stmt.last_token)))

  def test_dict_wrong_order(self):
    parsed = matcher.parse_ast('{1:2, 3:4}', '<string>')
    stmt = parsed.tree.body[0]
    self.assertIsNone(
        syntax_matchers.StmtPattern('{3:4, 1:2}').match(
            matcher.MatchContext(parsed), stmt))

  def test_nonvariable_name_fails(self):
    """Names are only treated as variables, or anything weird, on request."""
    parsed = matcher.parse_ast('3', '<string>')
    stmt = parsed.tree.body[0]
    self.assertIsNone(
        syntax_matchers.StmtPattern('name').match(
            matcher.MatchContext(parsed), stmt))

  def test_variable_name(self):
    parsed = matcher.parse_ast('3', '<string>')
    stmt = parsed.tree.body[0]
    self.assertEqual(
        syntax_matchers.StmtPattern('$name').match(
            matcher.MatchContext(parsed), stmt),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(stmt, parsed.text, stmt.first_token,
                                    stmt.last_token),
            bindings=mock.ANY))

  def test_complex_variable(self):
    parsed = matcher.parse_ast('foo = bar', '<string>')
    stmt = parsed.tree.body[0]
    self.assertEqual(
        syntax_matchers.StmtPattern('foo = $name').match(
            matcher.MatchContext(parsed), stmt),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(stmt, parsed.text, stmt.first_token,
                                    stmt.last_token),
            bindings=mock.ANY))

  def test_lvalue_variable(self):
    parsed = matcher.parse_ast('a = b', '<string>')
    stmt = parsed.tree.body[0]
    self.assertEqual(
        syntax_matchers.StmtPattern('$x = $y').match(
            matcher.MatchContext(parsed), stmt),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(stmt, parsed.text, stmt.first_token,
                                    stmt.last_token),
            bindings=mock.ANY))

  def test_restrictions(self):
    parsed = matcher.parse_ast('a = 1\na = 2', '<string>')
    stmt_match, stmt_nomatch = parsed.tree.body
    m = syntax_matchers.StmtPattern('a = $name',
                                    {'name': syntax_matchers.ExprPattern('1')})
    self.assertIsNotNone(m.match(matcher.MatchContext(parsed), stmt_match))
    self.assertIsNone(m.match(matcher.MatchContext(parsed), stmt_nomatch))

  def test_repeated_variable(self):
    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtPattern('$x + $x'),
            '1 + 1\n1 + 2\na + a\na + b'), ['1 + 1', 'a + a'])

  def test_variable_conflict(self):
    """Variables use the default conflict resolution outside of the pattern.

    Inside of the pattern, they use MERGE_EQUIVALENT_AST, but this is opaque to
    callers.
    """
    # The AllOf shouldn't make a difference, because the $x variable is just
    # a regular Bind() variable outside of the pattern, and merges via KEEP_LAST
    # per normal.
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                syntax_matchers.StmtPattern('$x'), base_matchers.Bind('x')),
            '1'), ['1'])


class DescendantMatchersTest(matcher_test_util.MatcherTestCase,
                             parameterized.TestCase):

  @parameterized.parameters(syntax_matchers.HasChild,
                            syntax_matchers.HasDescendant)
  def test_wrongtype(self, matcher_type):
    m = matcher_type(base_matchers.Anything())
    self.assertIsNone(m.match(_FAKE_CONTEXT, object()))

  def test_wrongtype_isorhas(self):
    """IsOrHasDescendant doesn't care about the type unless it recurses."""
    m = syntax_matchers.IsOrHasDescendant(base_matchers.Anything())
    self.assertIsNotNone(m.match(_FAKE_CONTEXT, object()))

  @parameterized.parameters(syntax_matchers.HasChild,
                            syntax_matchers.HasDescendant,
                            syntax_matchers.IsOrHasDescendant)
  def test_nomatch(self, matcher_type):
    m = matcher_type(ast_matchers.Num())
    self.assertEqual(self.get_all_match_strings(m, 'x + y'), [])

  @parameterized.parameters(syntax_matchers.HasChild,
                            syntax_matchers.HasDescendant,
                            syntax_matchers.IsOrHasDescendant)
  def test_has_haschild(self, matcher_type):
    m = matcher_type(ast_matchers.Num())
    # even for IsOrHasDescendant, find_iter doesn't recurse into a matched node.
    self.assertEqual(self.get_all_match_strings(m, 'x + 1'), ['x + 1'])

  @parameterized.parameters(syntax_matchers.HasDescendant,
                            syntax_matchers.IsOrHasDescendant)
  def test_nonchild_descendant(self, matcher_type):
    m = base_matchers.AllOf(ast_matchers.Call(),
                            matcher_type(ast_matchers.Num()))
    self.assertEqual(
        self.get_all_match_strings(m, 'foo(x + 1)'), ['foo(x + 1)'])

  def test_nonchild_descendant_haschild(self):
    m = base_matchers.AllOf(ast_matchers.Call(),
                            syntax_matchers.HasChild(ast_matchers.Num()))
    self.assertEqual(self.get_all_match_strings(m, 'foo(x + 1)'), [])


class AncestorMatchersTest(matcher_test_util.MatcherTestCase,
                           parameterized.TestCase):
  """Inversions of DescendantMatchersTest for HasParent etc."""

  @parameterized.parameters(syntax_matchers.HasParent,
                            syntax_matchers.HasAncestor)
  def test_wrongtype(self, matcher_type):
    m = matcher_type(base_matchers.Anything())
    self.assertIsNone(m.match(matcher_test_util.empty_context(), []))

  def test_wrongtype_isorhas(self):
    """IsOrHasAncestor doesn't care about the type unless it recurses."""
    m = syntax_matchers.IsOrHasAncestor(base_matchers.Anything())
    self.assertIsNotNone(m.match(matcher_test_util.empty_context(), []))

  @parameterized.parameters(syntax_matchers.HasParent,
                            syntax_matchers.HasAncestor,
                            syntax_matchers.IsOrHasAncestor)
  def test_nomatch(self, matcher_type):
    m = matcher_type(ast_matchers.While())
    self.assertEqual(self.get_all_match_strings(m, 'x'), [])

  @parameterized.parameters(syntax_matchers.HasParent,
                            syntax_matchers.HasAncestor)
  def test_has_hasparent(self, matcher_type):
    m = base_matchers.AllOf(
        base_matchers.Unless(ast_matchers.Add()),  # Add can't stringify.
        matcher_type(ast_matchers.BinOp()))
    # even for IsOrHasAncestor, find_iter doesn't recurse into a matched node.
    self.assertEqual(
        self.get_all_match_strings(m, '1 + (2 + 3)'), ['1', '2 + 3'])

  @parameterized.parameters(syntax_matchers.HasAncestor,
                            syntax_matchers.IsOrHasAncestor)
  def test_nonparent_ancestor(self, matcher_type):
    m = base_matchers.AllOf(ast_matchers.Num(),
                            matcher_type(ast_matchers.Call()))
    self.assertEqual(self.get_all_match_strings(m, 'foo(x + 1)'), ['1'])

  def test_nonparent_ancestor_hasparent(self):
    m = base_matchers.AllOf(ast_matchers.Num(),
                            syntax_matchers.HasParent(ast_matchers.Call()))
    self.assertEqual(self.get_all_match_strings(m, 'foo(x + 1)'), [])


class WithTopLevelImportTest(parameterized.TestCase):

  @parameterized.parameters('import os', 'import os.path', 'import os as os')
  def test_has_import(self, import_stmt):
    any_m = base_matchers.Anything()
    matchers = [
        syntax_matchers.WithTopLevelImport(any_m, 'os'),
        syntax_matchers.WithTopLevelImport(any_m, 'os', 'os'),
    ]

    context = matcher.MatchContext(matcher.parse_ast(import_stmt))
    for m in matchers:
      with self.subTest(m=m):
        self.assertIsNotNone(m.match(context, 1))

  @parameterized.parameters('import os.path as path', 'from os import path',
                            'from os import path as path')
  def test_has_nested_import(self, import_stmt):
    any_m = base_matchers.Anything()
    matchers = [
        syntax_matchers.WithTopLevelImport(any_m, 'os.path'),
        syntax_matchers.WithTopLevelImport(any_m, 'os.path', 'path'),
    ]

    context = matcher.MatchContext(matcher.parse_ast(import_stmt))
    for m in matchers:
      with self.subTest(m=m):
        self.assertIsNotNone(m.match(context, 1))

  @parameterized.parameters('from os import path as renamed',
                            'from os import path as renamed')
  def test_renamed_fromimport(self, import_stmt):
    any_m = base_matchers.Anything()
    m_success = syntax_matchers.WithTopLevelImport(any_m, 'os.path', 'renamed')
    m_fail = syntax_matchers.WithTopLevelImport(any_m, 'os.path')
    context = matcher.MatchContext(matcher.parse_ast(import_stmt))
    self.assertIsNotNone(m_success.match(context, 1))
    self.assertIsNone(m_fail.match(context, 1))

  def test_renamed_import(self):
    any_m = base_matchers.Anything()
    m_success = syntax_matchers.WithTopLevelImport(any_m, 'os', 'renamed')
    m_fail = syntax_matchers.WithTopLevelImport(any_m, 'os')
    context = matcher.MatchContext(matcher.parse_ast('import os as renamed'))
    self.assertIsNotNone(m_success.match(context, 1))
    self.assertIsNone(m_fail.match(context, 1))

  @parameterized.parameters(
      'from not_os import path',
      'from os import not_path',
      'from .os import path',
  )
  def test_missing_import(self, import_stmt):
    any_m = base_matchers.Anything()
    m = syntax_matchers.WithTopLevelImport(any_m, 'os.path')
    context = matcher.MatchContext(matcher.parse_ast(import_stmt))
    self.assertIsNone(m.match(context, 1))


class FromFunctionTest(matcher_test_util.MatcherTestCase):

  def test_lvalue_variable(self):

    def inner(x, y):  # pylint: disable=unused-argument
      x = y

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner), 'a = b'),
        ['a = b'])

  def test_docstring(self):

    def inner(x, y):  # pylint: disable=unused-argument
      """This function should just transform certain assignments."""
      x = y

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner), 'a = b'),
        ['a = b'])

  def test_empty_function(self):

    def inner():
      """This is a load-bearing docstring!"""

    with self.assertRaisesRegex(ValueError, 'docstring'):
      syntax_matchers.StmtFromFunctionPattern(func=inner)

  def test_lambda(self):

    with self.assertRaisesRegex(ValueError, 'lambda'):
      self.get_all_match_strings(
          syntax_matchers.StmtFromFunctionPattern(func=lambda x: x))

  def test_pass(self):

    def inner():
      pass

    with self.assertRaisesRegex(ValueError, 'pass'):
      syntax_matchers.StmtFromFunctionPattern(func=inner)

  def test_doctstring_pass(self):

    def inner():
      """This is just a function that passes."""
      pass

    with self.assertRaisesRegex(ValueError, 'pass'):
      syntax_matchers.StmtFromFunctionPattern(func=inner)

  def test_single_line(self):

    def inner(x, y): x = y  # pylint: disable=unused-argument,multiple-statements

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner), 'a = b'),
        ['a = b'])

  def test_single_line_multi_statement(self):
    # This is bad don't ever do this.

    def inner(x, y): x = y; y = x  # pylint: disable=unused-argument,multiple-statements

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner), 'a = b'),
        ['a = b'])

  def test_empty_return(self):
    def inner():
      return

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner),
            'def x():\n  return'),
        ['return'])

  def test_return(self):
    def inner(x):
      return x.y

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner),
            'def f():\n  return z.y'),
        ['return z.y'])

  def test_bare_raise(self):
    def inner():
      raise  # pylint: disable=misplaced-bare-raise

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner),
            'def f():\n  raise'),
        ['raise'])

  def test_bare_yield(self):
    def inner():
      yield  # pylint: disable=misplaced-bare-raise

    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.StmtFromFunctionPattern(func=inner),
            'def f():\n  yield'),
        ['yield'])


class NamedFunctionTest(matcher_test_util.MatcherTestCase):

  def test_default(self):
    self.assertEqual(
        self.get_all_match_strings(syntax_matchers.NamedFunctionDefinition(),
                                   'def f(): pass\nlambda: None\n'),
        ['def f(): pass'])

  def test_body(self):
    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.NamedFunctionDefinition(
                body=syntax_matchers.HasDescendant(2)),
            'def f1(): pass\ndef f2(): 2\n'), ['def f2(): 2'])

  @unittest.skipIf(six.PY2, "Python 2 doesn't support annotations.")
  def test_returns(self):
    self.assertEqual(
        self.get_all_match_strings(
            syntax_matchers.NamedFunctionDefinition(
                returns=base_matchers.Unless(None)),
            textwrap.dedent("""\
                def f1(): pass
                def f2() -> None: pass
                def f3() -> int: return 3
            """),
        ),
        ['def f2() -> None: pass', 'def f3() -> int: return 3'],
    )


class InNamedFunctionTest(matcher_test_util.MatcherTestCase):

  def test_in_named_function(self):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Name(),
                syntax_matchers.InNamedFunction(
                    ast_matchers.FunctionDef(name='foo'))),
            textwrap.dedent("""\
                in_nothing
                def parent():
                  in_parent
                  def foo():
                    in_foo
                    def foo_nested():
                      in_foo_nested
                def bar():
                  in_bar
            """),
        ), ['in_foo'])


class HasPrevSiblingTest(matcher_test_util.MatcherTestCase,
                         parameterized.TestCase):

  @parameterized.parameters(
      'a + b + c',
      '{a: b}',
      'a; b',
  )
  def test_no_sibling(self, expr):
    self.assertEmpty(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Name(),
                syntax_matchers.HasPrevSibling(ast_matchers.Name())), expr))

  @parameterized.named_parameters(
      ('plain_list', '[a, b, c]'),
      ('arg_list', 'func(a, b, c)'),
  )
  def test_expression_sibling(self, expr):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Name(),
                syntax_matchers.HasPrevSibling(ast_matchers.Name())), expr),
        ['b', 'c'])

  def test_matches_only_immediate_siblings(self):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Assign(),
                syntax_matchers.HasPrevSibling(ast_matchers.ClassDef())),
            textwrap.dedent("""\
        class Before: pass
        a = 1
        b = 2
        class After: pass

        if a:
          c = 3
        else:
          class AlsoBefore: pass
          d = 4
                      """)), [
                          'a = 1',
                          'd = 4',
                      ])

  def test_compound_sibling(self):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.BinOp(),
                syntax_matchers.HasPrevSibling(ast_matchers.BinOp())),
            '[a+c, a+b]'), ['a+b'])


class HasNextSiblingTest(matcher_test_util.MatcherTestCase,
                         parameterized.TestCase):

  @parameterized.parameters(
      'a + b + c',
      '{a: b}',
      'a; b',
  )
  def test_no_sibling(self, expr):
    self.assertEmpty(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Name(),
                syntax_matchers.HasNextSibling(ast_matchers.Name())), expr))

  @parameterized.named_parameters(
      ('plain_list', '[a, b, c]'),
      ('arg_list', 'func(a, b, c)'),
  )
  def test_expression_sibling(self, expr):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Name(),
                syntax_matchers.HasNextSibling(ast_matchers.Name())), expr),
        ['a', 'b'])

  def test_matches_only_immediate_siblings(self):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.Assign(),
                syntax_matchers.HasNextSibling(ast_matchers.ClassDef())),
            textwrap.dedent("""\
        class Before: pass
        a = 1
        b = 2
        class After: pass

        if a:
          c = 3
        else:
          class AlsoBefore: pass
          d = 4
                      """)), ['b = 2'])

  def test_compound_sibling(self):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.AllOf(
                ast_matchers.BinOp(),
                syntax_matchers.HasNextSibling(ast_matchers.BinOp())),
            '[a+c, a+b]'), ['a+c'])


if __name__ == '__main__':
  absltest.main()
