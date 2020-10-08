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
"""Tests for refex.fix.fixer."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals  # for convenience.

from unittest import mock
import re

from absl.testing import absltest
from absl.testing import parameterized
import attr

from refex import formatting
from refex import future_string
from refex import search
from refex import substitution
from refex.fix import find_fixer
from refex.fix import fixer
from refex.python import syntactic_template
from refex.python.matchers import ast_matchers
from refex.python.matchers import syntax_matchers


def _search_replace_fixer(search_expr, replace, message=None, url='', **kwargs):
  return fixer.SimplePythonFixer(
      message=message if message is not None else search_expr,
      matcher=syntax_matchers.ExprPattern(search_expr),
      replacement=syntactic_template.PythonExprTemplate(replace),
      url=url,
      category='TESTONLY',
      **kwargs)


def _substitution(**kwargs):
  """Match with a substitution that shares the provided fields.

  The rest are replaced with mock.ANY.

  Args:
    **kwargs: The arguments to Substitution().

  Returns:
    A Substitution.
  """
  for attribute in attr.fields(substitution.Substitution):
    if attribute.name not in kwargs:
      kwargs[attribute.name] = mock.ANY
  # temporarily disable input validation:
  with mock.patch.object(substitution.Substitution,
                         '_validate', lambda self: None):
    return substitution.Substitution(**kwargs)


# TODO(b/120294113): Split this test out into other test files.
# Since the fixer framework has been almost entirely dissolved, tests need to
# be moved out into more relevant files like search_test.py.


class PythonFixerFrameworkTest(parameterized.TestCase):

  def test_empty_fixers(self):
    fx = fixer.CombiningPythonFixer([])
    self.assertEqual(list(search.find_iter(fx, 'b', 'foo.py')), [])

  def test_empty_results(self):
    fx = fixer.CombiningPythonFixer([_search_replace_fixer('a', 'x')])
    self.assertEqual(list(search.find_iter(fx, 'b', 'foo.py')), [])

  def test_output_sorted(self):
    pyfixers = [
        _search_replace_fixer('a', 'x'),
        _search_replace_fixer('b', 'x')
    ]
    for python_fixers in [pyfixers, pyfixers[::-1]]:
      fx = fixer.CombiningPythonFixer(python_fixers)
      with self.subTest(reversed=python_fixers != pyfixers):
        self.assertEqual(
            list(search.find_iter(fx, 'a + b', 'foo.py')),
            [_substitution(message='a'),
             _substitution(message='b')])

  def test_discards_overlap(self):
    """PythonFixer discards overlapping matches in a consistent way."""
    # we want to have both a small fix that sorts before the big fix, and
    # a small fix that sorts after it, to test discards in both directions.
    small_fixers = [
        _search_replace_fixer('a', 'x', message='small'),
        _search_replace_fixer('b', 'x', message='small'),
    ]
    big_fixer = _search_replace_fixer('a + b', 'x')
    for i, small_fixer in enumerate(small_fixers):
      pyfixers = [small_fixer, big_fixer]
      for python_fixers in [pyfixers, pyfixers[::-1]]:
        fx = fixer.CombiningPythonFixer(python_fixers)
        with self.subTest(small_fixer=i, reversed=python_fixers != pyfixers):
          self.assertEqual(
              list(search.find_iter(fx, 'a + b', 'foo.py')),
              [_substitution(message='small')])

  def test_discards_rewrite_error(self):
    # If we knew how to trigger a rewrite error, we'd just fix the bug, so let's
    # make one up.
    fx = fixer.CombiningPythonFixer([_search_replace_fixer('$x', '$x')])
    with mock.patch.object(
        syntactic_template.PythonExprTemplate,
        'substitute_match',
        side_effect=formatting.RewriteError,
        autospec=True):
      self.assertEqual(list(search.find_iter(fx, 'a', 'foo.py')), [])

  def test_discards_unparseable_expr(self):
    """Searching discards unparseable substitutions for expressions.

    (Note: this only happens during fixedpoint computation.)
    """
    fx = fixer.CombiningPythonFixer([
        fixer.SimplePythonFixer(
            message='',
            matcher=syntax_matchers.ExprPattern('a'),
            replacement=formatting.ShTemplate('x x x'),
            url='')
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [])

  def test_discards_unparseable_stmt(self):
    """Searching discards unparseable substitutions for statements.

    (Note: this only happens during fixedpoint computation.
    """
    fx = fixer.CombiningPythonFixer([
        fixer.SimplePythonFixer(
            message='',
            matcher=syntax_matchers.StmtPattern('raise e'),
            replacement=formatting.ShTemplate('x x x'),
            url='')
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'raise e', 'foo.py', max_iterations=10)), [])

  def test_doesnt_discard_unparseable_compound_stmt(self):
    fx = fixer.CombiningPythonFixer([
        fixer.SimplePythonFixer(
            message='ouch',
            matcher=ast_matchers.For(),
            replacement=formatting.ShTemplate('x x x'),
            url='')
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'for x in y: pass', 'foo.py')),
        [_substitution(message='ouch')])

  def test_fixedpoint_infinite_loop(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'a', url='url_a'),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)),
        [_substitution(replacements={'fixedpoint': 'a'})])

  def test_fixedpoint(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', url='url_a'),
        _search_replace_fixer('b', 'c', url='url_b'),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            substitution.Substitution(
                message='There are a few findings here:\n\na\n(url_a)\n\nb\n(url_b)',
                matched_spans={'fixedpoint': (0, 1)},
                primary_label='fixedpoint',
                replacements={'fixedpoint': 'c'},
                url='https://refex.readthedocs.io/en/latest/guide/fixers/merged.html',
                significant=True,
                category='refex.merged.significant',
            )
        ])

  def test_fixedpoint_insignificant_only(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', url='merged', significant=False),
        _search_replace_fixer('b', 'c', url='merged', significant=False),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            _substitution(
                significant=False, category='refex.merged.not-significant')
        ])

  @parameterized.parameters((False, True), (True, False), (True, True))
  def test_fixedpoint_significant(self, ab_significant, bc_sigificant):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer(
            'a', 'b', url='merged', significant=ab_significant),
        _search_replace_fixer(
            'b', 'c', url='merged', significant=bc_sigificant),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)),
        [_substitution(significant=True, category='refex.merged.significant')])

  def test_fixedpoint_merged_url(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', url='merged'),
        _search_replace_fixer('b', 'c', url='merged'),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            _substitution(
                message='There are a few findings here:\n\na\n\nb',
                url='merged')
        ])

  def test_fixedpoint_drop_insignificant(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', url='url_a', significant=False),
        _search_replace_fixer('b', 'c', url='url_b', significant=True),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            substitution.Substitution(
                message='b',
                matched_spans={'fixedpoint': (0, 1)},
                primary_label='fixedpoint',
                replacements={'fixedpoint': 'c'},
                url='url_b',
                significant=True,
                category='refex.merged.significant',
            )
        ])

  def test_fixedpoint_keep_insignificant(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', url='url_a', significant=False),
        _search_replace_fixer('b', 'c', url='url_b', significant=False),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            substitution.Substitution(
                message='There are a few findings here:\n\na\n(url_a)\n\nb\n(url_b)',
                matched_spans={'fixedpoint': (0, 1)},
                primary_label='fixedpoint',
                replacements={'fixedpoint': 'c'},
                url='https://refex.readthedocs.io/en/latest/guide/fixers/merged.html',
                significant=False,
                category='refex.merged.not-significant',
            )
        ])

  def test_fixedpoint_drop_redundant_messages(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', message='z', url='url_z'),
        _search_replace_fixer('b', 'c', message='z', url='url_z'),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            _substitution(
                message='z',
                matched_spans={'fixedpoint': (0, 1)},
                primary_label='fixedpoint',
                replacements={'fixedpoint': 'c'},
                url='url_z',
            )
        ])

  def test_fixedpoint_nodrop_redundant_messages_with_different_urls(self):
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a', 'b', message='z', url='url_a'),
        _search_replace_fixer('b', 'c', message='z', url='url_b'),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a', 'foo.py', max_iterations=10)), [
            _substitution(
                message='There are a few findings here:\n\nz\n(url_a)\n\nz\n(url_b)',
                matched_spans={'fixedpoint': (0, 1)},
                primary_label='fixedpoint',
                replacements={'fixedpoint': 'c'},
                url='https://refex.readthedocs.io/en/latest/guide/fixers/merged.html',
            )
        ])

  def test_fixedpoint_disjoint_merge(self):
    """Disjoint rewrites should be merged together when it helps."""
    fx = fixer.CombiningPythonFixer([
        _search_replace_fixer('a1', 'a2'),
        _search_replace_fixer('b1', 'b2'),
        _search_replace_fixer('a2, b2', 'final'),
    ])
    self.assertEqual(
        list(search.find_iter(fx, 'a1, b1', 'foo.py', max_iterations=10)),
        [_substitution(replacements={'fixedpoint': 'final'})])

  def test_labeled_replacements_example_fragment(self):
    fx = fixer.SimplePythonFixer(
        message='',
        matcher=syntax_matchers.ExprPattern('$y'),
        replacement={'y': syntactic_template.PythonExprTemplate('$y')},
    )
    with self.assertRaises(TypeError):
      fx.example_replacement()


class PythonFixerTest(parameterized.TestCase):
  FIXER = find_fixer.from_pattern('*')

  @parameterized.parameters('bare_foo.py', 'foo/bar.py', 'foo/bar_test.py')
  def test_includes_paths(self, path):
    self.assertRegex(path, self.FIXER.include_regex)

  @parameterized.parameters(
      'foo/bar',
      'foo/bar_py',  # "." trips people up :)
      'foo/bar.pyx',  # don't forget $
  )
  def test_excludes_paths(self, path):
    self.assertNotRegex(path, self.FIXER.include_regex)

  # The remaining tests are in refex_test.py


class ImmutableDefaultDictTest(absltest.TestCase):

  def test_replacement(self):
    self.assertEqual(
        future_string.Template('$a == $b').substitute(
            fixer.ImmutableDefaultDict(lambda k: k)), 'a == b')

  def test_len(self):
    self.assertLen(fixer.ImmutableDefaultDict(lambda _: 'a'), 0)


class DefaultFixerTest(absltest.TestCase):

  def assert_equivalent_under_mock(self, lhs, rhs, m):
    """Checks that lhs and rhs perform the same operations in a mock namespace.

    The mock object has its _attributes_ used as members of the namespace. So,
    for example, if you want to ensure a global FOO is set to 3 during
    evaluation, you must set m.FOO = 3.

    The mock is reset between calls, so things like return_value will not work.

    Args:
      lhs: An object that can be passed to eval()
      rhs: An object that can be passed to eval()
      m: A Mock object.
    """
    m.reset_mock()  # to be safe.

    objs_map = fixer.ImmutableDefaultDict(lambda k: getattr(m, k))
    lhs_result = None
    lhs_e = None
    try:
      lhs_result = eval(lhs, {}, objs_map)  # It's for the greater good: pylint: disable=eval-used
    except Exception as e:  # pylint: disable=broad-except
      lhs_e = e
    lhs_calls = m.mock_calls
    # Rest the mock so we can reuse it. This keeps sub-mock ids the same,
    # so that e.g. a(b) is the "same call".
    # If we used two mocks, then b would be a different object each time,
    # and the calls would not compare equal.
    m.reset_mock()
    rhs_result = None
    rhs_e = None
    try:
      rhs_result = eval(rhs, {}, objs_map)  # It's for the greater good: pylint: disable=eval-used
    except Exception as e:  # pylint: disable=broad-except
      rhs_e = e

    self.assertEqual(lhs_calls, m.mock_calls)
    # Try to check that the return values are at least remotely similar.
    # Either the return values are equal (e.g. 1L == 1), or the types are the
    # same (eg. object() != object(), but we'd still like that case to pass.)
    self.assertTrue(
        lhs_result == rhs_result or type(lhs_result) == type(rhs_result),  # pylint: disable=unidiomatic-typecheck
        '{!r} != {!r}'.format(lhs_result, rhs_result))
    self.assertEqual(type(lhs_e), type(rhs_e))
    # Would like to assert similarity of the exception messages, but they can
    # include things like the mock id / address in memory.
    # So we can't do `self.assertEqual(str(lhs_e), str(rhs_e))`

  def test_smoke_equivalent(self):
    """Tests that the test fixer conversions seem equivalent."""
    for fx in find_fixer.from_pattern('*').fixers:
      with self.subTest(
          fixer=type(fx).__name__, fragment=fx.example_fragment()):
        # Use compile() here to test as much as possible before breaking early.
        # (e.g. if we can't execute the test, at least verify it parses.)
        # We either parse both as expressions or both as statements, so that we
        # can compare the return value of eval().
        try:
          replacement = compile(fx.example_replacement(), '<replacement>',
                                'eval')
          exemplar = compile(fx.example_fragment(), '<exemplar>', 'eval')
        except SyntaxError:
          replacement = compile(fx.example_replacement(), '<replacement>',
                                'exec')
          exemplar = compile(fx.example_fragment(), '<exemplar>', 'exec')

        # TODO(b/130657662): Allow the fix itself to disable smoke checks,
        # rather than keeping this INCREDIBLY GROSS central list of opt-outs.
        if 'IsInstance' in fx.example_replacement():
          # isinstance requires it be a type, not a mock, so we'll skip this.
          continue
        if fx._category == 'pylint.literal-comparison':
          # literal equality isn't equivalent to literal is, so don't check
          # for equivalent semantics.
          continue
        if 'has_key' in (fx._category or ''):
          # The has_key fix intentionally rewrites expressions.
          continue
        if 'attrib-default' in (fx._category or ''):
          # default= is not exactly equivalent to factory=.
          continue
        if 'mutable' in fx._message:
          # By definition, an immutable constant is not equivalent to a mutable
          # one
          continue
        if 'logging.fatal' in fx.example_fragment():
          # absl.logging.fatal is dangerous, yo!
          continue
        if 'idioms.uncessary-comprehension' in (fx._category or ''):
          # list(x) is not completely equivalent to [a for a in x]
          continue

        m = mock.MagicMock()
        m.self = self
        self.assert_equivalent_under_mock(exemplar, replacement, m)

  def test_examples_real(self):
    """Tests that the fixers do actually give the example replacement."""
    for fx in find_fixer.from_pattern('*').fixers:
      example = fx.example_fragment()
      example_replacement = fx.example_replacement()
      with self.subTest(
          fixer=type(fx).__name__,
          example=example,
          example_replacement=example_replacement):
        self.assertIsNotNone(example)
        substitutions = list(
            search.find_iter(fixer.CombiningPythonFixer([fx]), example, 'a.py'))
        self.assertLen(substitutions, 1)
        replaced = formatting.apply_substitutions(example, substitutions)
        self.assertEqual(replaced, example_replacement)

  def test_categories(self):
    """Tests that all default fixers have a category assigned.

    This makes them more useful in tricorder, where they are all enabled.
    """
    for fx in find_fixer.from_pattern('*').fixers:
      with self.subTest(fixer=fx):
        self.assertIsNotNone(fx._category)


if __name__ == '__main__':
  absltest.main()
