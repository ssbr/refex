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

# python3
"""
:mod:`refex.formatting`
=======================

Utilities for generating, applying, and displaying
:class:`~refex.substitution.Substitution` objects.

User Display
------------

.. autofunction:: diff_substitutions

.. autoclass:: Renderer
   :members:


Rewriting
---------

.. autofunction:: apply_substitutions

.. autoexception:: RewriteError


Templates
.........

.. autoclass:: Template
   :members:

.. autoclass:: LiteralTemplate
   :show-inheritance:
   :members:

.. autoclass:: ShTemplate
   :show-inheritance:
   :members:

.. autoclass:: RegexTemplate
   :show-inheritance:
   :members:

"""
# Historical note: this module glues together "output for humans" and
# "perform changes", unrelated things, because once they were actually related:
# it used to be that output for humans was itself a special case of performing
# changes (i.e. performed by replacing the match with a colorized version
# thereof). Clever! But no longer the case: that approach is not compatible
# with showing diffs and matches together.
# TODO: Move things into more appropriate places.
# The doc split above gives a potentially useful split.


import abc
import collections
import functools
import itertools
import operator
import sre_parse
import string
import sys
from typing import (Any, Dict, Iterable, Iterator, Mapping, Optional, Set, Text,
                    Tuple)

import attr
import cached_property
import colorama
from refex import match as _match
from refex import parsed_file
from refex import substitution

_DEFAULT_STYLES = (
    colorama.Style.BRIGHT + colorama.Fore.YELLOW,
    colorama.Style.BRIGHT + colorama.Fore.BLUE,
    colorama.Style.BRIGHT + colorama.Fore.MAGENTA,
    colorama.Style.BRIGHT + colorama.Fore.CYAN,
    # colorama.Fore.RED,  # reserved for conflicts/errors/etc.
    # colorama.Fore.GREEN,  # looks like a diff marker
)


# TODO: Move this onto the Substitution as a "context" span.
def line_expanded_span(s: str, start: int, end: int) -> Tuple[int, int]:
  """Expands a slice of a string to the edges of the lines it overlaps.

  The start is moved left until it takes place after the preceding newline,
  and the end is moved right until before the succeeding newline. If either hit
  the end of the string, that is where they stay.

  Args:
    s: str to expand slices in.
    start: slice start, (inclusive)
    end: slice start (exclusive)

  Returns:
    (new_start, new_end)
  """
  if start is None:
    start = 0
  if end is None:
    end = len(s)
  if start < 0:
    start = len(s) + start
  if end < 0:
    end = len(s) + end
  if end < start:
    end = start
  return (_line_expanded_left(s, start), _line_expanded_right(s, end))


def _line_expanded_left(s, start):
  try:
    return min(start, s.rindex('\n', 0, start) + 1)
  except ValueError:
    return 0


def _line_expanded_right(s, end):
  try:
    return s.index('\n', end)
  except ValueError:
    return len(s)


def apply_substitutions(
    data: str, subs: Iterable[substitution.Substitution]
  ) -> str:
  """Applies all substitutions and returns the result."""
  all_replacements = []
  for sub in subs:
    all_replacements.append(_substitution_to_replacement(data, sub))
  all_replacements.sort(key=operator.itemgetter(1))
  rewritten_interior, inner_start, inner_end = concatenate_replacements(
      data, all_replacements)
  return u''.join([
      data[:inner_start],
      rewritten_interior,
      data[inner_end:],
  ])


def diff_substitutions(content: str, subs: Iterable[substitution.Substitution],
                       filename: str,
                       renderer: 'Renderer') -> Iterable[Tuple[bool, str]]:
  """Yields (is_diff, displayable diff/match information) for ``subs``."""
  # TODO: Inline this into RefexRunner?
  last_was_diff = False
  for sub in subs:
    is_diff, display = renderer.render(
        content,
        sub,
        extra=dict(
            path=filename,
            file=filename,
            filename=filename,
        ))
    if last_was_diff:
      provided_display = (
          '{colorama.Style.RESET_ALL}'
          '{colorama.Fore.CYAN}---{colorama.Style.RESET_ALL}\n'.format(
              colorama=colorama) + display)
    else:
      provided_display = display
    yield is_diff, provided_display
    last_was_diff = is_diff


class RewriteError(Exception):
  """Rewriting failed.

  After a :exc:`RewriteError`, that particular set of rewrites is skipped, but
  the rest of the program moves on.
  """


def _split_labeled_span_after(ls, pos):
  pos += 1
  start, end = ls.span
  return (
      attr.evolve(ls, span=(start, pos)),
      attr.evolve(ls, span=(pos, end)),
  )


def _partition_labeled_span(
    contents: Text, labeled_span: substitution.LabeledSpan
) -> Tuple[substitution.LabeledSpan, Optional[substitution.LabeledSpan],
           Optional[substitution.LabeledSpan]]:
  """Splits a labeled span into first line, intermediate, last line."""

  start, end = labeled_span.span
  first_newline = contents.find('\n', start, end)
  if first_newline == -1:
    return (labeled_span, None, None)

  first, remainder = _split_labeled_span_after(labeled_span, first_newline)

  last_newline = contents.rfind('\n', *remainder.span)
  if last_newline == -1:
    return (first, None, remainder)

  between, last = _split_labeled_span_after(remainder, last_newline)
  return (first, between, last)


def _sub_diff_blocks(contents, diffs):
  """Breaks a substitution's diff into blocks.

  A block is a diff as returned by as_diff(), with the constraint that
  if a block contains a DiffSpan, then it also contains the full content of
  every line that the diff touches. All the blocks are disjoint.

  LabeledSpan entries are broken up in order to allow a block to only include
  the part of the LabeledSpan that is on the same line as the block.

  This makes it ~basically the same as a block you'd see in a diff. The
  following example unified diff has three entries, each of which is labeled
  at the end of the line:

        unchanged       1
        also unchanged  1
      - removed         2
      - removed also    2
      + added           2
      - removed again!  3
        unchanged       4

  """
  current_block = []
  current_block_is_diff = False
  for diff in diffs:
    if isinstance(diff, substitution.LabeledSpan):
      first_line, intervening_lines, last_line = _partition_labeled_span(
          contents, diff)
      current_block.append(first_line)
      if last_line is not None:
        yield current_block_is_diff, current_block
        if intervening_lines is not None:
          yield False, [intervening_lines]
        current_block = [last_line]
        current_block_is_diff = False
    else:
      current_block.append(diff)
      current_block_is_diff = True
  yield current_block_is_diff, current_block


@attr.s
class Renderer:
  """Applies substitutions and gives styled output for humans.

  Matches and diffs are styled via ``colorama``.

  Non-diff spans with the same label will always be styled the same, even across
  multiple calls to :math:`render()`. (:class:`Renderer` keeps the styling as
  state). However, just because two spans are styled the same doesn't mean they
  have the same label -- styles can be reused.

  The one exception to this is the primary label / primary span, which is only
  styled normally if there are no other labels. If there *are* other labels,
  then instead of being assigned its normal color, the primary span is just
  given a neutral bright style.

  Overlapping non-diff spans are given their own unique color, per-combination.

  The displayed output covers the entire substitution, even when nothing
  changes.

  Args:
    match_format: The format string when displaying a match (a
        :class:`~refex.substitution.Substitution` without a replacement).
        It can use the following variables:

        ``match``
             The styled match.
        ``head``
             The part of the line before the match.
        ``tail``
             The part of the line after the match.

        As well as anything in the ``extra`` argument passed to
        :meth:`render()`.
    color: Whether to style and colorize human-readable output or not.
  """
  _match_format = attr.ib(default='{head}{match}{tail}', type=str)
  color = attr.ib(default=True, type=bool)
  _label_to_style = attr.ib(
      factory={frozenset(): ''}.copy, init=False, type=Dict[Set[str], str])
  _styles = attr.ib(
      default=itertools.cycle(_DEFAULT_STYLES), init=False, type=Iterator[str])

  def render(
      self,
      contents: str,
      sub: substitution.Substitution,
      extra: Mapping[str, Any]
  ) -> Tuple[bool, str]:
    """Renders a single Substitution for display on the terminal.

    Args:
      contents: the original string the substitution is against.
      sub: a Substitution object.
      extra: extra substitution variables for the match format template.

    Returns:
      ``(is_diff, display)``

      ``is_diff`` is ``True`` if this represents a diff, ``False`` if it
      represents a mere match with no replacement.

      ``display`` is a human-readable string to represent the substitution,
      printable to the terminal.
    """
    restricted_diffs = substitution.as_diff(sub)
    # TODO: this is ridiculous, compute this somewhere else.
    # (e.g. include line_start/line_end as context in attributes on the
    # Substitution)
    match_start = min(start for (start, end) in sub.matched_spans.values())
    match_end = max(end for (start, end) in sub.matched_spans.values())
    line_start, line_end = line_expanded_span(contents, match_start, match_end)

    if sub.replacements:
      # include the surrounding context up to the line ends in the diff.
      extended_diffs = itertools.chain(
          [
              substitution.LabeledSpan(
                  labels=frozenset(), span=(line_start, match_start))
          ],
          restricted_diffs,
          [
              substitution.LabeledSpan(
                  labels=frozenset(), span=(match_end, line_end))
          ],
      )
      rendered = []

      def create_diff(prefix, s):
        if not s:
          # non-removals and non-additions should be elided from diff.
          return ''
        if not s.endswith('\n'):
          s += '\n'
        return ''.join(prefix + line for line in s.splitlines(True))

      for is_diff, block in _sub_diff_blocks(contents, extended_diffs):
        if is_diff:
          rendered.append(
              create_diff(
                  self._style(colorama.Fore.RED, '-'),
                  self._render_diff_block(
                      contents, sub, block, before=True, is_diff=True)))
          rendered.append(
              create_diff(
                  self._style(colorama.Fore.GREEN, '+'),
                  self._render_diff_block(
                      contents, sub, block, before=False, is_diff=True)))
        else:
          rendered.append(
              create_diff(
                  ' ',
                  self._render_diff_block(
                      contents, sub, block, before=True, is_diff=True)))
      return True, ''.join(rendered)
    else:
      display = self._render_diff_block(
          contents, sub, restricted_diffs, before=True, is_diff=False)
      head = contents[line_start:match_start]
      tail = contents[match_end:line_end]

      fmt_variables = extra.copy()
      fmt_variables.update(head=head, tail=tail, match=display)
      return False, self._match_format.format(**fmt_variables) + '\n'

  def _style(self, styles, text):
    if self.color:
      return styles + text + colorama.Style.RESET_ALL
    else:
      return text

  def _style_for(self, sub, labeled_span):
    if (len(sub.matched_spans) > 1 and
        labeled_span.labels == {sub.primary_label}):
      # Special case: the primary span is only colored if it's the only group.
      style = colorama.Style.BRIGHT
    else:
      try:
        style = self._label_to_style[labeled_span.labels]
      except KeyError:
        self._label_to_style[labeled_span.labels] = style = next(self._styles)
    return style

  def _render_diff_block(self, contents, sub, current_block, before, is_diff):
    """Renders one side of a diff block (either `before` or `after`)."""

    rendered = []

    for diff in current_block:
      start, end = diff.span
      if isinstance(diff, substitution.DiffSpan):
        style = colorama.Fore.RED if before else colorama.Fore.GREEN
        style += colorama.Style.BRIGHT
        string = contents[start:end] if before else diff.after
      else:
        style = self._style_for(sub, diff)
        # TODO: How to colorize a diff is actually really difficult
        # to decide. For example, should we make the match itself non-dim? red
        # but not bright?
        # It may be that we want to add more configuration hooks and metadata
        # that gets injected here.
        if is_diff:
          style += colorama.Style.DIM
        string = contents[start:end]

      # Style the whole string, but break around \n so that we can add/remove
      # formatting at line boundaries.
      for line in string.splitlines(True):
        tail = ''
        if line.endswith('\n'):
          tail = '\n'
          line = line[:-1]
        rendered.append(self._style(style, line) + tail)

    return ''.join(rendered)


@attr.s
class _VarDict:
  """A dict-like object for mapping variables to newly-crafted negative indexes."""

  var_to_index = attr.ib(factory=dict)
  _next_index = attr.ib(default=-1)

  def __getitem__(self, var: str | int):
    if var in self.var_to_index:
      return self.var_to_index[var]
    else:
      index = self._next_index
      self.var_to_index[var] = index
      self._next_index -= 1
      return index


@attr.s(frozen=True)
class _Var:
  label = attr.ib(type=str)


@functools.total_ordering
class _AlwaysGreater:
  def __gt__(self, other):
    del other  # unused
    return True
  def __eq__(self, other):
    return False


@attr.s
class _FakePattern:
  r"""Hacky fake pattern object to get around the fact that we don't have one.

  sre_parse expects an existing compiled regexp in order to parse. In
  particular, it uses groupindex to get an index from a string label, and
  (in python 3) groups to find out if a group reference like \7 is an error or
  not.

  We don't need to map named groups to indexes, so we need to override both
  groupindex and groups so that sre_parse doesn't choke when a group "index" is
  a string.

  This is obviously terrible.
  """
  # TODO: maybe give it a real pattern object for --py patterns, or else
  # restrict use of regex templates to just --mode=re.
  groupindex = attr.ib(factory=_VarDict)
  groups = attr.ib(default=_AlwaysGreater())


def _parse_re_template(
    template: str | bytes,
) -> tuple[list[str | bytes | int], dict[int, int | str | bytes]]:
  """Parses a regex template.

  Args:
    template: The regular expression template to parse.

  Returns:
    The expanded template (a list of strings and group indexes), and a list of
    variables.
  """
  pattern = _FakePattern()
  if sys.version_info >= (3, 12):
    expanded_template = sre_parse.parse_template(template, pattern)
  else:
    # In Python 3.11 and below, parse_template used `None` in each location of
    # the template that was a group reference, and separately had a list of
    # (index_which_is_none, group_for_that_undex). We postprocess this into the
    # python 3.12 format for compatibility.
    fillers, expanded_template = sre_parse.parse_template(template, pattern)
    for i, group in fillers:
      assert expanded_template[i] is None
      expanded_template[i] = group
    assert None not in expanded_template

  var_to_index = pattern.groupindex.var_to_index
  for i in expanded_template:
    if isinstance(i, int) and i >= 0:
      var_to_index[i] = i

  return expanded_template, {index: var for var, index in var_to_index.items()}


class Template(metaclass=abc.ABCMeta):
  """A substitution template for matches within a :class:`~refex.parsed_file.ParsedFile`.

  Implementations must define a :meth:`substitute_match()` method which returns
  a replacement string for any given match. Implementations apply some template,
  whose results may be tweaked according to knowledge about the syntax being
  used and the context in which it is used. (For example, parenthesization,
  formatting, etc.)
  """

  @abc.abstractmethod
  def substitute_match(
      self,
      parsed: parsed_file.ParsedFile,
      match: _match.Match,
      matches: Mapping[Text, Tuple[int, int]]
  ) -> Text:
    """Substitute in pre-existing matches into the template.

    Arguments:
      parsed: The :class:`~refex.parsed_file.ParsedFile` each match was on.
      match: The match being replaced.
      matches: A mapping from variable name to ``(start, end)`` span.

    Returns:
      The rendered template.
    """
    pass

  @abc.abstractproperty
  def variables(self):
    """Returns the set of metavariables present in the template."""
    return frozenset()

  template: str


def stringify_matches(matches):
  stringified = {}
  for label, m in matches.items():
    string = m.string
    if string is None:
      continue
    stringified[label] = string
  return stringified


@attr.s(frozen=True)
class LiteralTemplate(Template):
  """A no-op template which does no substitution at all."""

  #: The source template.
  template = attr.ib(type=str)
  variables = frozenset()

  def substitute_match(self, parsed, match, matches):
    del parsed, match, matches  # unused
    return self.template


@attr.s(frozen=True)
class ShTemplate(Template):
  """A :class:`string.Template`-style literal template.

  This does no special reformatting.
  """

  #: The source template.
  template = attr.ib(type=str)

  _template = attr.ib(repr=False, init=False, type=string.Template)

  @_template.default
  def _template_default(self):
    return string.Template(self.template)

  def substitute_match(self, parsed, match, matches):
    del match  # unused
    return self._template.substitute(stringify_matches(matches))

  @cached_property.cached_property
  def variables(self):
    d = collections.defaultdict(str)
    _ = self._template.substitute(d)
    return d.keys()


@attr.s(frozen=True)
class RegexTemplate(Template):
  """A template using regex template syntax."""
  #: The source template.
  template = attr.ib(type=Text)
  _template = attr.ib(
      repr=False,
      init=False,
      default=attr.Factory(
          lambda self: _parse_re_template(self.template),
          takes_self=True,
      ),
  )

  def substitute_match(self, parsed, match, matches):
    del match  # unused
    mapping = stringify_matches(matches)
    empty_string = self.template[0:0]  # bytes/unicode compatibility hack.
    expanded_template, index_to_var = self._template
    expanded_template = list(expanded_template)
    for i, s in enumerate(expanded_template):
      if isinstance(s, int):
        expanded_template[i] = mapping[index_to_var[s]]
    return empty_string.join(expanded_template)

  @cached_property.cached_property
  def variables(self):
    _, index_to_var = self._template
    return frozenset(index_to_var.values())


def rewrite_templates(parsed, matches, templates):
  r"""Rewrite labeled spans using Template classes.

  For example, given matches with labels 0, 1, and 'foobar', you can use the
  replacement templates:

      {0: RegexTemplate(r'\1'),
       1: RegexTemplate(r'\g<foobar>'),
       'foobar': RegexTemplate(r'\g<0>')}

  And this will rewrite match 0 with the contents of match 1, match 1 with the
  contents of match foobar, and match foobar with the contents of match 0.

  Args:
    parsed: the ParsedFile.
    matches: the matches.
    templates: a map from matches key to template.

  Returns:
    a map from matches key to formatted template.
  """
  replacements = collections.OrderedDict()
  for label, template in templates.items():
    if label in matches:
      m = matches[label]
      if m.span in (None, (-1, -1)):
        # Either the match doesn't have position information,
        # or it was not present at all, respectively.
        continue
    elif label.startswith('__'):
      # Special label, fake a zero-length match.
      m = _match.Match()
    else:
      continue
    replacements[label] = template.substitute_match(parsed, m, matches)
  return replacements


def template_variables(templates: Mapping[Any, Template]) -> Set[Any]:
  """Returns the set of labels used in the templates."""
  labels = set()
  for label, template in templates.items():
    labels.add(label)
    labels |= template.variables
  return frozenset(labels)


def _rewrite_to_replacements(label_to_span, label_to_text):
  if label_to_text is None:
    return
  assert (
      frozenset(label_to_span) >= frozenset(label_to_text)
  ), '%r is not a superset of %r' % (set(label_to_span), set(label_to_text))
  for label, (start, end) in sorted(
      label_to_span.items(), key=operator.itemgetter(1)):
    if label in label_to_text:
      yield label_to_text[label], start, end


def _substitution_to_replacement(text, sub):
  """Returns (new_text, start_of_replacement, end_of_replacement)."""
  return concatenate_replacements(
      text, _rewrite_to_replacements(sub.matched_spans, sub.replacements))


def concatenate_replacements(text, replacements):
  """Applies a rewrite to some text and returns a span to be replaced.

  Args:
    text: Text to be rewritten.
    replacements: An iterable of (new_text, start of replacement, end)

  Returns:
    A new replacement.
  """
  joined = []
  first_start = None
  last_end = None
  for rewritten, start, end in replacements:
    if start > end:
      raise ValueError(
          'Rewrites have invalid spans: start=%r > end=%r' % (start, end))
    if first_start is None:
      first_start = start
    if last_end is not None:
      joined.append(text[last_end:start])
    if last_end is not None and last_end > start:
      raise ValueError(
          'Rewrites overlap: end > next start: '
          '{last_end} > {start}. '
          '(Was about to write: text[{start}:{end}] (== {old!r}) <- {new!r})'
          .format(
              start=start,
              end=end,
              last_end=last_end,
              old=text[start:end],
              new=rewritten))
    joined.append(rewritten)
    last_end = end
  return ''.join(joined), first_start or 0, last_end or 0
