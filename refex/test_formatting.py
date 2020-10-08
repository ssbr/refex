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
"""Tests for refex.formatting."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections

from absl.testing import absltest
from absl.testing import parameterized
import colorama

from refex import formatting
from refex import match
from refex import parsed_file
from refex import substitution


class LineExpandedSpanTest(absltest.TestCase):

  def test_none(self):
    self.assertEqual((0, 12),
                     formatting.line_expanded_span('012\n456\n890\n', None,
                                                   None))

  def test_negative(self):
    self.assertEqual((8, 11),
                     formatting.line_expanded_span('012\n456\n890\n', -2, -1))

  def test_empty_span(self):
    self.assertEqual((4, 7),
                     formatting.line_expanded_span('012\n456\n890\n', 5, 4))
    self.assertEqual((4, 7),
                     formatting.line_expanded_span('012\n456\n890\n', 5, 5))

  def test_line_subset_(self):
    self.assertEqual((4, 7),
                     formatting.line_expanded_span('012\n456\n890\n', 5, 6))

  def test_string_start(self):
    self.assertEqual((0, 3),
                     formatting.line_expanded_span('012\n456\n890\n', 1, 2))

  def test_string_end(self):
    self.assertEqual((8, 11),
                     formatting.line_expanded_span('012\n456\n890\n', 9, 10))

  def test_line_start(self):
    self.assertEqual((4, 7),
                     formatting.line_expanded_span('012\n456\n890\n', 4, 5))

  def test_line_start_2(self):
    self.assertEqual((4, 7),
                     formatting.line_expanded_span('012\n456\n890\n', 4, 4))

  def test_line_end(self):
    self.assertEqual((4, 11),
                     formatting.line_expanded_span('012\n456\n890\n', 7, 8))

  def test_noop(self):
    self.assertEqual((4, 7),
                     formatting.line_expanded_span('012\n456\n890\n', 4, 7))

  def test_line_overlap_span(self):
    self.assertEqual((0, 11),
                     formatting.line_expanded_span('012\n456\n890\n', 3, 9))


class RendererTest(absltest.TestCase):

  def test_empty_style(self):
    """Tests that the empty string is unstyled.

    We want to preserve colors for the _non_ empty spans.
    """
    sub = substitution.Substitution(
        matched_spans={'primary': (0, 0)},
        primary_label='primary',
    )
    self.assertEqual(
        formatting.Renderer(match_format='{match}').render('abc', sub, {}),
        (False, '\n'))

  def test_saves_style(self):
    """Tests that the same style is reused for the same label."""
    renderer = formatting.Renderer(match_format='{match}')
    sub_x = substitution.Substitution(
        matched_spans={'x': (0, 3)},
        primary_label='x',
    )
    is_diff, out_1 = renderer.render('abc', sub_x, {})
    self.assertFalse(is_diff)
    is_diff, out_2 = renderer.render('abc', sub_x, {})
    self.assertFalse(is_diff)

    # The same labels always get the same styling:
    self.assertEqual(out_1, out_2)
    # But a different label gets a new styling:
    sub_y = substitution.Substitution(
        matched_spans={'y': (0, 3)},
        primary_label='y',
    )
    is_diff, out_3 = renderer.render('abc', sub_y, {})
    self.assertFalse(is_diff)
    self.assertNotEqual(out_1, out_3)

  def test_loops_styles(self):
    """When we run out of styles we reuse the old ones.

    (Instead of, e.g., StopIteration.)
    """
    renderer = formatting.Renderer(match_format='{match}')

    def next_out(label):
      sub = substitution.Substitution(
          matched_spans={label: (0, 3)},
          primary_label=label,
      )
      is_diff, out = renderer.render('abc', sub, {})
      self.assertFalse(is_diff)
      return out

    first = next_out('x')
    for label in range(10):
      last = next_out(label)
      if first == last:
        break
    else:
      self.fail('Never repeated: {!r} (last: {!r}'.format(first, last))

  def test_nonsolo_primary_style(self):
    # exploit a weird edge case for testing: if the other label has zero-width,
    # it is not styled, but this still affects how the primary label is treated.
    sub = substitution.Substitution(
        matched_spans={
            'primary': (0, 3),
            'other': (3, 3)
        },
        primary_label='primary',
    )
    self.assertEqual(
        formatting.Renderer(match_format='{match}').render('abc', sub, {}),
        (False, '{colorama.Style.BRIGHT}abc{colorama.Style.RESET_ALL}\n'.format(
            colorama=colorama)))

  def test_diff(self):
    """Tests a basic diff rendering."""
    sub = substitution.Substitution(
        matched_spans={'primary': (0, 3)},
        replacements={'primary': u'new'},
        primary_label='primary',
    )

    renderer = formatting.Renderer(match_format='{match}', color=False)
    is_diff, out = renderer.render('old', sub, {})
    self.assertTrue(is_diff)
    self.assertEqual(out, '-old\n+new\n')


class ShTemplateTest(parameterized.TestCase):

  @parameterized.parameters(('', set()), ('$a $b', {'a', 'b'}))
  def test_variables(self, template, expected_variables):
    self.assertEqual(
        formatting.ShTemplate(template).variables, expected_variables)


class RegexTemplateTest(parameterized.TestCase):

  def test_empty(self):
    self.assertEqual(
        formatting.RegexTemplate('').substitute_match(
            parsed_file.ParsedFile('', path='path', pragmas=()),
            match.SpanMatch('', (0, 0)), {}), '')

  def test_extra(self):
    self.assertEqual(
        formatting.RegexTemplate('').substitute_match(
            parsed_file.ParsedFile('b', path='path', pragmas=()),
            match.SpanMatch('', (0, 0)), {'a': match.SpanMatch('b', (0, 1))}),
        '')

  def test_missing(self):
    for template in [r'\1', r'\g<x>']:
      with self.subTest(template=template):
        with self.assertRaises(KeyError):
          formatting.RegexTemplate(r'\1').substitute_match(
              parsed_file.ParsedFile('', path='path', pragmas=()),
              match.SpanMatch('', (0, 0)), {})

  def test_present_numeric(self):
    self.assertEqual(
        formatting.RegexTemplate(r'\1').substitute_match(
            parsed_file.ParsedFile('a', path='path', pragmas=()),
            match.SpanMatch('', (0, 0)), {1: match.SpanMatch('a', (0, 1))}),
        'a')

  def test_present_numeric_by_name(self):
    self.assertEqual(
        formatting.RegexTemplate(r'\g<1>').substitute_match(
            parsed_file.ParsedFile('a', path='path', pragmas=()),
            match.SpanMatch('', (0, 0)), {1: match.SpanMatch('a', (0, 1))}),
        'a')

  def test_present_named(self):
    self.assertEqual(
        formatting.RegexTemplate(r'\g<x>').substitute_match(
            parsed_file.ParsedFile('a', path='path', pragmas=()),
            match.SpanMatch('', (0, 0)), {'x': match.SpanMatch('a', (0, 1))}),
        'a')

  @parameterized.parameters(('', set()), (r'\1 \3', {1, 3}),
                            (r'\g<foo> \g<4>  \7', {'foo', 4, 7}))
  def test_variables(self, template, expected_variables):
    self.assertEqual(
        formatting.RegexTemplate(template).variables, expected_variables)


class TemplateRewriterTest(absltest.TestCase):

  def test_empty(self):
    self.assertEqual(
        formatting.TemplateRewriter({}).rewrite(
            parsed_file.ParsedFile('abc', path='path', pragmas=()), {}), {})

  def test_named_template(self):
    self.assertEqual(
        formatting.TemplateRewriter({
            'foo': formatting.RegexTemplate(r'x\g<foo>x')
        }).rewrite(
            parsed_file.ParsedFile('abc', path='path', pragmas=()),
            collections.OrderedDict([('foo', match.SpanMatch('b', (1, 2)))])),
        {'foo': 'xbx'})

  def test_missing_template(self):
    self.assertEqual(
        formatting.TemplateRewriter({
            # swap foo and bar
            'foo': formatting.RegexTemplate(r'bar=\g<bar>'),
            'bar': formatting.RegexTemplate(r'foo=\g<foo>'),
        }).rewrite(
            parsed_file.ParsedFile('abc', path='path', pragmas=()),
            collections.OrderedDict([('foo', match.SpanMatch('', (-1, -1))),
                                     ('bar', match.SpanMatch('a', (0, 1)))])),
        # foo is never matched, bar is replaced with foo=<non-match>,
        # which is treated as ''.
        {'bar': 'foo='})

  def test_labels_empty(self):
    self.assertEqual(formatting.TemplateRewriter({}).labels, set())

  def test_labels_nonempty(self):
    self.assertEqual(
        formatting.TemplateRewriter({
            'key': formatting.RegexTemplate(r'\g<template_variable>')
        }).labels, {'key', 'template_variable'})

  def test_string_match(self):
    self.assertEqual(
        formatting.TemplateRewriter({
            'foo': formatting.ShTemplate(r'$bar')
        }).rewrite(
            parsed_file.ParsedFile('abc', path='path', pragmas=()),
            collections.OrderedDict([('foo', match.SpanMatch('abc', (0, 3))),
                                     ('bar', match.StringMatch('xyz'))])),
        {'foo': 'xyz'})


class ConcatenateReplacementsTest(parameterized.TestCase, absltest.TestCase):

  def test_null_concatenation(self):
    self.assertEqual(
        formatting.concatenate_replacements('xyz', []),
        ('', 0, 0),
    )

  @parameterized.parameters(
      (('', 0, 0),),
      (('', 0, 3),),
      (('abc', 0, 3),),
      (('b', 1, 2),),
  )
  def test_noop(self, replacement):
    self.assertEqual(
        formatting.concatenate_replacements('xyz', [replacement]),
        replacement,
    )

  def test_adjacent(self):
    self.assertEqual(
        formatting.concatenate_replacements('xyz', [('b', 1, 2), ('c', 2, 3)]),
        ('bc', 1, 3),
    )

  def test_gap(self):
    self.assertEqual(
        formatting.concatenate_replacements('xyz', [('a', 0, 1), ('c', 2, 3)]),
        ('ayc', 0, 3),
    )

  def test_gap_weirdsizes(self):
    self.assertEqual(
        formatting.concatenate_replacements('xyz', [('abc', 0, 0), ('', 2, 3)]),
        ('abcxy', 0, 3),
    )

  # Failure tests

  def test_bad_swapped_slice(self):
    with self.assertRaises(ValueError):
      formatting.concatenate_replacements('xyz', [('a', 1, 0)])

  def test_bad_overlapping_spans(self):
    string = '01234'
    fixed_start = 1
    fixed_end = len(string) - 1
    for start in (fixed_start - 1, fixed_start, fixed_start + 1):
      for end in (fixed_end - 1, fixed_end, fixed_end + 1):
        # fixed and dynamic are two overlapping spans.
        fixed = ('fixed', fixed_start, fixed_end)
        dynamic = ('dynamic', start, end)
        with self.subTest(start=start, end=end, fixed='first'):
          with self.assertRaises(ValueError):
            formatting.concatenate_replacements(string, [fixed, dynamic])
        with self.subTest(start=start, end=end, fixed='second'):
          with self.assertRaises(ValueError):
            formatting.concatenate_replacements(string, [dynamic, fixed])


class ApplySubstitutionsTest(absltest.TestCase):

  def test_0_matches(self):
    self.assertEqual(
        formatting.apply_substitutions('abc', []),
        'abc',
    )

  def test_1_match(self):
    sub = substitution.Substitution(
        matched_spans={'x': (1, 2)},
        replacements={'x': u'x'},
        primary_label='x',
    )
    self.assertEqual(
        formatting.apply_substitutions('abc', [sub]),
        'axc',
    )

  def test_2_matches(self):
    sub1 = substitution.Substitution(
        matched_spans={'x': (0, 1)},
        replacements={'x': u'x'},
        primary_label='x',
    )
    sub2 = substitution.Substitution(
        matched_spans={'x': (2, 3)},
        replacements={'x': u'x'},
        primary_label='x',
    )
    self.assertEqual(
        formatting.apply_substitutions('abc', [sub1, sub2]),
        'xbx',
    )

  def test_noreplacements(self):
    sub = substitution.Substitution(
        matched_spans={'x': (1, 2)},
        primary_label='x',
    )
    self.assertEqual(
        formatting.apply_substitutions('abc', [sub]),
        'abc',
    )


if __name__ == '__main__':
  absltest.main()
