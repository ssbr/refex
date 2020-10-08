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
"""
:mod:`refex.search`
-------------------

Entry Points
~~~~~~~~~~~~

.. autofunction:: rewrite_string

.. autofunction:: find_iter

Searchers
~~~~~~~~~

.. data:: ROOT_LABEL
   :type: str

   The root label, which exists as a span in every returned
   :class:`~refex.substitution.Substitution`.

.. autoexception:: SkipFileError
.. autoexception:: SkipFileNoResultsError
  :show-inheritance:

Base Classes
............

.. autoclass:: AbstractSearcher
   :members:
.. autoclass:: WrappedSearcher
  :show-inheritance:
.. autoclass:: BaseRewritingSearcher
   :show-inheritance:
   :members:
.. autoclass:: BasePythonSearcher
   :show-inheritance:
   :members:
.. autoclass:: BasePythonRewritingSearcher
   :show-inheritance:
   :members:
.. autoclass:: FileRegexFilteredSearcher
   :show-inheritance:

Wrappers
........

.. autoclass:: PragmaSuppressedSearcher
   :show-inheritance:
.. autoclass:: AlsoRegexpSearcher
   :show-inheritance:
   :members:
.. autoclass:: CombinedSearcher
   :show-inheritance:
   :members:

Concrete Searchers
..................

.. autoclass:: RegexSearcher
   :show-inheritance:

.. autoclass:: PyMatcherRewritingSearcher
   :show-inheritance:
   :members:

.. autoclass:: PyExprRewritingSearcher
   :show-inheritance:
   :members:

.. autoclass:: PyStmtRewritingSearcher
   :show-inheritance:
   :members:

"""

from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

import abc
import ast
import itertools
import re
import sys
from typing import (Dict, Iterable, Mapping, MutableMapping, MutableSequence,
                    MutableSet, Optional, Pattern, Sequence, Text, Tuple,
                    Union)

from absl import logging
import attr
import cached_property
import six

from refex import formatting
from refex import match
from refex import parsed_file
from refex import substitution
from refex.python import evaluate
from refex.python import matcher
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers

Span = Tuple[int, int]
# TODO(b/118783544): Only string keys.
MatchKey = Union[str, int]


class SkipFileError(Exception):
  """Exception raised to halt processing and skip this file.

  If this was due to an error (i.e. not a :class:`SkipFileNoResultsError`), it
  will generally be presented as a diagnostic to the end user.
  """
  pass


class SkipFileNoResultsError(SkipFileError):
  """Exception raised to skip this file because it will not have any results.

  This is not, strictly speaking, an error, just an exceptional case and
  optimization.
  """
  pass


def default_compile_regex(r: str) -> Pattern[str]:
  """Compiles a regex with useful flags, and raises ValueError on failure."""
  try:
    return re.compile(r, re.M)
  except re.error as e:
    raise ValueError('Failed to parse regular expression (%s): %s' % (e, r))


def find_iter(searcher: 'AbstractSearcher',
              data: Text,
              path: str,
              max_iterations: int = 1) -> Iterable[substitution.Substitution]:
  """Finds all search results as an iterable of Substitutions.

  Args:
    searcher: The AbstractSearcher to run.
    data: The data to search in.
    path: The path of the data on disk.
    max_iterations: The number of times to try applying and re-applying
      replacements from the searcher to generate new results. There will always
      be at least one application.

  Yields:
    Substitutions.

  Raises:
    SkipFileError: This file was skipped and not searched at all.
  """
  searcher.check_is_included(path)
  parsed = searcher.parse(data, path)

  for span, span_subs in itertools.groupby(
      searcher.find_iter_parsed(parsed), lambda sub: sub.key_span):
    span_subs = list(span_subs)
    logging.debug('For searcher on %s, span group %r yields %d span subs: %r',
                  parsed.path, span, len(span_subs), span_subs)
    if span is None:
      for sub in span_subs:
        yield sub
      continue

    # There were multiple substitutions for the same span.
    simple_start, simple_end = span
    for sub in _fixed_point(
        searcher,
        parsed,
        span_subs,
        simple_start,
        simple_end,
        max_iterations=max_iterations,
    ):
      yield sub


def _fixed_point(
    searcher: 'AbstractSearcher',
    parsed: parsed_file.ParsedFile,
    initial_substitutions: Sequence[substitution.Substitution],
    start: int,
    end: int,
    max_iterations: int,
):
  """Repeatedly apply searcher until there are no more changes."""

  if max_iterations <= 1:
    return initial_substitutions

  # TODO(b/116068515): sort the substitutions here and below.
  new_substitutions = [
      s.relative_to_span(start, end) for s in initial_substitutions
  ]
  if None in new_substitutions:
    logging.error('Out of bounds substitution after filtering: %s',
                  initial_substitutions[new_substitutions.index(None)])
    return initial_substitutions  # give up

  text = parsed.text[start:end]
  logging.debug(
      'Applying _fixed_point with initial subs=%r on on parsed.text[%d:%d]: %r',
      new_substitutions, start, end, text)

  all_substitutions = []

  # max_iterations + 1 to get the extra iteration before the break,
  # and then - 1 to account for the fact that we already did an iteration.
  for i in range(max_iterations):
    rewritten = formatting.apply_substitutions(text, new_substitutions)
    try:
      parsed = matcher.parse_ast(rewritten, parsed.path)
    except matcher.ParseError as e:
      logging.error(
          'Could not parse rewritten substitution in %s: %s\n'
          'Tried to rewrite text[%s:%s] == %r\n'
          'Rewrite was: %r\n'
          'Substitutions: %r', parsed.path, e, start, end, text, rewritten,
          new_substitutions)
      break

    # These substitutions parsed and were valid, add them to the list:
    all_substitutions.extend(new_substitutions)

    # Set up the variables for the next rewrite attempt
    logging.debug('_fixed_point Iteration %d: rewrote %r -> %r', i, text,
                  rewritten)
    text = rewritten

    if i == max_iterations:
      # no point bothering to get the next substitution
      break

    new_substitutions = list(searcher.find_iter_parsed(parsed))
    if not new_substitutions:
      break

  if not all_substitutions:
    # even the first rewrite failed to parse
    return []
  elif len(all_substitutions) == len(initial_substitutions):
    # We didn't discover any new substitutions.
    return initial_substitutions
  else:
    return [_compile_substitutions(all_substitutions, start, end, text)]


def _compile_substitutions(substitutions: Iterable[substitution.Substitution],
                           primary_start: int, primary_end: int,
                           new_primary_contents: Text):
  """Create one substitution out of many that were composed together."""
  if not substitutions:
    return None
  significant = True
  significant_subs = [sub for sub in substitutions if sub.significant]
  if not significant_subs:
    significant_subs = substitutions
    significant = False  # all subs were insignificant
  message_header = 'There are a few findings here:\n\n'
  urls = {sub.url for sub in significant_subs}
  if len(urls) == 1:
    [url] = urls
    messages = [sub.message for sub in significant_subs if sub.message]
    if len(set(messages)) == 1:
      # Present only one message, with no header.
      message_header = ''
      del messages[1:]
  else:
    # Can't give a better URL here :/
    url = 'https://refex.readthedocs.io/en/latest/guide/fixers/merged.html'
    messages = [
        '{message}\n({url})'.format(message=sub.message or '(no message)',
                                    url=sub.url)
        for sub in significant_subs
    ]
  if messages:
    message = message_header + '\n\n'.join(m for m in messages)
  else:
    message = None
  primary_label = 'fixedpoint'
  return substitution.Substitution(
      message=message,
      url=url,
      matched_spans={primary_label: (primary_start, primary_end)},
      primary_label=primary_label,
      replacements={primary_label: new_primary_contents},
      significant=significant,
      category='refex.merged.{}'.format(
          'significant' if significant else 'not-significant'),
  )


class AbstractSearcher(six.with_metaclass(abc.ABCMeta)):
  """A class which finds search/replace results."""

  def parse(self, data: Text, path: str):
    """Parses the data into a representation usable by the searcher."""
    return parsed_file.ParsedFile(text=data, path=path, pragmas=())

  @abc.abstractmethod
  def find_iter_parsed(
      self,
      parsed: parsed_file.ParsedFile) -> Iterable[substitution.Substitution]:
    """Finds all matches as an iterable of Substitutions.

    Args:
      parsed: The parsed data, as returned by ``parse()``.

    Returns:
      An iterable of ``Substitution`` objects.

    Raises:
      SkipFileError: This file was skipped and not searched at all.
    """
    return []

  def check_is_included(self, path: str) -> None:
    """Raises SkipFileError if a path should not be searched.."""
    del path  # unused

  @abc.abstractmethod
  def approximate_regex(self) -> Optional[str]:
    """Returns a regular expression that approximates the searcher (or ``None``).

    Any file that would contain a match MUST be matched by the returned regex.
    If no useful regex exists with that property (e.g. no regex except ``.*``
    would suffice), then it is better to return ``None``.

    Returns:
      Either a regex that matches a file if the search would find a match, or
      None if the regex would have a very large number of false positives.

      The regex is a Python regex in "search" form (i.e. it does not need to
      match the entire file).
    """
    return None


@attr.s(frozen=True)
class WrappedSearcher(AbstractSearcher):
  """Forwards everything to a wrapped searcher.

  Subclasses can override methods to intercept and manipulate calls. By default,
  calls are forwarded to ``searcher``.

  Attributes:
    searcher: the wrapped searcher.
  """
  searcher = attr.ib()

  def parse(self, *args, **kwargs):
    return self.searcher.parse(*args, **kwargs)

  def find_iter_parsed(self, *args, **kwargs):
    return self.searcher.find_iter_parsed(*args, **kwargs)

  def check_is_included(self, *args, **kwargs):
    return self.searcher.check_is_included(*args, **kwargs)

  def approximate_regex(self):
    return self.searcher.approximate_regex()


class PragmaSuppressedSearcher(WrappedSearcher):
  """Automatically suppresses Substitutions based on pragmas in the file."""

  def find_iter_parsed(
      self,
      parsed: matcher.PythonParsedFile) -> Iterable[substitution.Substitution]:
    return substitution.suppress_exclude_bytes(
        self.searcher.find_iter_parsed(parsed),
        _pragma_excluded_ranges(parsed),
    )


@attr.s(frozen=True)
class AlsoRegexpSearcher(WrappedSearcher):
  """Only yields any results if additional regexes are satisfied.

  If the provided regexes don't match the file when they are supposed to, the
  file will not be considered further.
  """
  #: Regexes that must match anywhere in the file.
  _also = attr.ib(default=())
  #: Regexes that must not match anywhere in the file.
  _also_not = attr.ib(default=())

  def parse(self, data, path):
    if (not all(r.search(data) for r in self._also) or
        any(r.search(data) for r in self._also_not)):
      raise SkipFileNoResultsError()
    return self.searcher.parse(data, path)


@attr.s(frozen=True)
class CombinedSearcher(AbstractSearcher):
  """Searcher which combines the results of multiple sub-searchers.

  Note: all searchers must share compatible ``~parsed_file.ParsedFile`` types.
  See the :meth:`parse` docstring for requirements.
  """
  # This algorithm is O(n*m) and keeps growing as you add more
  # searchers. Not avoidable in the general case, but, e.g. for Python, you
  # could walk once and only run the searchers that could possibly match
  # at a given point using an O(1) type lookup -- which would generally cut
  # down the number of results.
  searchers = attr.ib(type=Tuple[AbstractSearcher, ...], converter=tuple,)

  def parse(self, data: Text, filename: str):
    """Parses using each sub-searcher, returning the most specific parsed file.

    Here "Most Specific" means the most specific subclass.

    This places strong requirements on the searchers:

      * values returned by one ``parse()`` method should always be usable in
        place of the value returned by another, if they return the same type,
        or if the type of the first is a subclass of the type of the other.
      * Ideally, for performance, values should be cached.

    Args:
      data: The data to be parsed.
      filename: The name of the file.

    Returns:
      The merged / most specific parsed file.
    """
    # In a language like C++ or Rust, rather than merging the types, we would
    # enforce that they are the same type. Python has *no way to do this* ahead
    # of time: even if we check the type(searcher), for example, two wrapping
    # searchers will look the same even if they wrap different types.
    # So we need to do the check inside parse(), not inside the constructor,
    # and at that point, there's no reason to disallow mixing the use of
    # the base ParsedFile and a subclass -- we can rely on some variant of
    # the Liskov substitution principle to let us use the subclass in place of
    # the base class.
    # If searcher types don't cache parse results, this will be unnecessarily
    # slow.
    parsed = None
    for searcher in self.searchers:
      new_parsed = searcher.parse(data, filename)
      if parsed is None:
        parsed = new_parsed
      if type(parsed) == type(new_parsed):  # pylint: disable=unidiomatic-typecheck
        # compatible, doesn't matter which we pick.
        assert parsed == new_parsed
      elif issubclass(type(new_parsed), type(parsed)):
        parsed = new_parsed
      elif issubclass(type(parsed), type(new_parsed)):
        # compatible, but keep old.
        pass
      else:
        raise TypeError('Incompatible parsed file types: %r / %r' % (parsed, new_parsed))
    return parsed

  def check_is_included(self, *args, **kwargs):
    """Only includes a file if *all* sub-searchers include it."""
    for searcher in self.searchers:
      searcher.check_is_included(*args, **kwargs)

  def approximate_regex(self):
    regexes = [searcher.approximate_regex() for searcher in self.searchers]
    if None in regexes:
      return None
    return '|'.join('(?:%s)' % regex for regex in regexes)

  def find_iter_parsed(self, parsed):
    """Returns all disjoint substitutions for parsed, in sorted order."""
    return substitution.disjoint_substitutions(sub
                 for searcher in self.searchers
                 for sub in searcher.find_iter_parsed(parsed))


def _pragma_excluded_ranges(
    parsed: matcher.PythonParsedFile) -> Mapping[Text, Sequence[Span]]:
  """Returns ranges for the parsed file that were disabled by "disable" pragmas.

  "enable" pragmas override "disable" pragmas within their scope and vice versa.

  Args:
    parsed: a ParsedFile.

  Returns:
    The suppressed ranges, in a form suitable to pass to suppress_exclude_bytes.
  """
  disabled = _pragma_ranges(parsed, 'disable')
  enabled = _pragma_ranges(parsed, 'enable')
  # gross O(n^2) search; probably doesn't matter.
  for category, ranges in six.iteritems(disabled):
    if category not in enabled:
      continue
    for i, (disabled_start, disabled_end) in enumerate(ranges):
      for enabled_start, _ in enabled[category]:
        if disabled_start <= enabled_start < disabled_end:
          disabled_end = enabled_start
      ranges[i] = (disabled_start, disabled_end)
  return disabled


def _pragma_ranges(parsed: matcher.PythonParsedFile,
                   key: str) -> MutableMapping[Text, MutableSequence[Span]]:
  """Returns the pragma-annotated ranges for e.g. suppress_exclude_bytes."""
  annotated_ranges = {}
  for pragma in parsed.pragmas:
    if key not in pragma.data:
      continue
    if pragma.tag == 'pylint':
      prefix = 'pylint.'
    elif pragma.tag == 'refex':
      prefix = ''
    else:
      continue
    annotated = {
        prefix + disabled.strip() for disabled in pragma.data[key].split(',')
    }
    for category in annotated:
      annotated_ranges.setdefault(category, []).append(
          (pragma.start, pragma.end))
  return annotated_ranges


class FileRegexFilteredSearcher(AbstractSearcher):
  """Base class for classes that filter files based on a regex.

  Instances should have an immutable ``include_regex`` attribute. Only files with
  paths matching the that regular expression will pass the check_is_included
  check.

  If other classes are mixed in which define a ``check_is_included`` method,
  this takes the conjunction, and only matches the filename if the other classes
  agree.
  """
  # TODO(b/120294113): rename to path_regex (or similar).
  #: Regex that must match the path name.
  include_regex = ''

  @cached_property.cached_property
  def _compiled_include_regex(self):
    return re.compile(self.include_regex)

  def check_is_included(self, path: str) -> None:
    super(FileRegexFilteredSearcher, self).check_is_included(path)
    if self._compiled_include_regex.search(path) is None:
      raise SkipFileError("path %r doesn't match %s" %
                          (path, self.include_regex))


ROOT_LABEL = '__root'


@attr.s(frozen=True)
class BaseRewritingSearcher(AbstractSearcher):
  """A base class for matchers which rewrite via templates.

  This is the normal case, and almost all searchers should be written as a
  :class`BaseRewritingSearcher`.

  The templates map matched spans to a template for the replacement. Every
  match must have a single root label defining the overall match, keyed by
  :data:`ROOT_LABEL`.

  For example, to replace the entire match with the empty string, equivalent
  to ``--sub=''`` on the command line, one might use::

      {ROOT_LABEL: formatting.ShTemplate('')}

  Whereas to only replace the 'a' span with the empty string, but leave the
  remainder untouched, like ``--named-sub=a=''``, one would instead use::

      {'a': formatting.ShTemplate('')}
  """

  templates = attr.ib(type=Optional[Dict[str, formatting.Template]])

  # TODO: Remove the rewriter class entirely and get rid of this
  # dynamic dispatch stuff.
  #
  # Rewriter classes don't really have a function anymore, and don't aid
  # extensibility or understandability. They just add more indirection.
  # Without Rewriter, one could still accomplish totally customized rewrites
  # using -- at worst -- a custom Template class.
  @cached_property.cached_property
  def rewriter(self) -> formatting.Rewriter:
    if self.templates is None:
      return formatting.NullRewriter()
    else:
      return formatting.TemplateRewriter(self.templates)

  def __attrs_post_init__(self):
    # A stub post-init so that subclasses can use super().
    pass

  @abc.abstractmethod
  def find_dicts_parsed(
      self, parsed: parsed_file.ParsedFile
  ) -> Iterable[Mapping[MatchKey, match.Match]]:
    """Finds all matches as an iterable of dict matches.

    Args:
      parsed: the return value of a call to parse()

    Returns:
      An iterable of matches, mapping labels to Span objects.
      :data:`ROOT_LABEL` must be included in every match.
    """
    del parsed  # unused
    return []

  def key_span_for_dict(
      self,
      parsed: parsed_file.ParsedFile,
      match_dict: Iterable[Mapping[MatchKey, match.Match]],
  ) -> Optional[Tuple[int, int]]:
    """Returns the ``key_span`` that the final ``Substitution`` will have."""
    return None


  def find_iter_parsed(
      self,
      parsed: matcher.PythonParsedFile) -> Iterable[substitution.Substitution]:
    for match_dict in self.find_dicts_parsed(parsed):
      try:
        replacements = self.rewriter.rewrite(parsed, match_dict)
      except formatting.RewriteError as e:
        # TODO: Forward this up somehow.
        print('Skipped rewrite:', e, file=sys.stderr)
        continue
      yield substitution.Substitution(
          matched_spans={
              label: s.span
              for label, s in match_dict.items()
              if s.span not in (None, (-1, -1))
          },
          replacements=replacements,
          primary_label=ROOT_LABEL,
          key_span=self.key_span_for_dict(parsed, match_dict))


@attr.s(frozen=True)
class RegexSearcher(BaseRewritingSearcher):
  """Searcher class using regular expressions.

  Args:
    compiled: A compiled regex.
  """
  _compiled = attr.ib()

  def __attrs_post_init__(self):
    super(RegexSearcher, self).__attrs_post_init__()
    pattern_labels = set(range(self._compiled.groups + 1))  # numeric groups
    pattern_labels.update(self._compiled.groupindex)  # named groups
    pattern_labels.add('__root')
    # NOTE: Pytype doesn't like the cached_property decoration on `labels` as it
    # returns conditional types and infers `Callable` instead of `Any`.
    missing_labels = set(self.rewriter.labels) - pattern_labels  # pytype: disable=wrong-arg-types
    if missing_labels:
      raise ValueError(
          'The substitution template(s) referenced groups not available in the regex (`{self._compiled.pattern}`): {groups}'
          .format(
              self=self,
              groups=', '.join(
                  '`{}`'.format(g) for g in sorted(map(str, missing_labels)))))

  @classmethod
  def from_pattern(cls, pattern: str,  templates: Optional[Dict[str, formatting.Template]]):
    return cls(compiled=default_compile_regex(pattern), templates=templates)

  def find_dicts_parsed(
      self, parsed: matcher.PythonParsedFile
  ) -> Iterable[Mapping[MatchKey, match.Match]]:
    for m in self._compiled.finditer(parsed.text):
      # TODO(b/118783544): Only string keys.
      matches = {(ROOT_LABEL if i == 0 else i): v for i, v in enumerate(
          match.SpanMatch.from_text(parsed.text, span) for span in m.regs)}
      # Also make named groups available to templates under their name (e.g.
      # \g<name>) not just their index (\1, \2, etc.).
      for named_group, i in self._compiled.groupindex.items():
        matches[named_group] = matches[i]
      yield matches

  def approximate_regex(self) -> str:
    return self._compiled.pattern


class BasePythonSearcher(AbstractSearcher):
  """Python searcher base class which defines parsing logic."""

  def parse(self, data: Text, filename: str):
    """Returns a :class:`refex.python.matcher.PythonParsedFile`."""
    try:
      return matcher.parse_ast(data, filename)
    except matcher.ParseError as e:
      # Probably Python 2. TODO: figure out how to handle this.
      raise SkipFileError(str(e))

  def approximate_regex(self):
    """Returns ``None`` (no approximation)."""
    return None


@attr.s(frozen=True)
class BasePythonRewritingSearcher(BasePythonSearcher, BaseRewritingSearcher):
  """Searcher class using :mod``refex.python.matchers``."""
  _matcher = attr.ib()

  def __attrs_post_init__(self):
    super(BasePythonRewritingSearcher, self).__attrs_post_init__()
    # NOTE: Pytype doesn't like the cached_property decoration on `labels` as it
    # returns conditional types and infers `Callable` instead of `Any`.
    missing_labels = set(self.rewriter.labels) - self._matcher.bind_variables  # pytype: disable=wrong-arg-types
    if missing_labels:
      raise ValueError(
          'The substitution template(s) referenced variables not matched in the Python matcher: {variables}'
          .format(variables=', '.join(
              '`{}`'.format(v) for v in sorted(missing_labels))))

  @classmethod
  def from_matcher(cls, matcher, templates: Optional[Dict[str, formatting.Template]]):
    """Creates a searcher from an evaluated matcher, and adds a root label."""
    # We wrap the evaluated matcher in a SystemBind() that is sort of like
    # "group 0" for regexes.
    return cls(
        matcher=base_matchers.SystemBind(ROOT_LABEL, matcher),
        templates=templates)

  def find_dicts_parsed(
      self, parsed: matcher.PythonParsedFile
  ) -> Iterable[Mapping[MatchKey, match.Match]]:
    for result in matcher.find_iter(self._matcher, parsed):
      yield {
          bound_name: match.value
          for bound_name, match in result.bindings.items()
      }

  def key_span_for_dict(self, parsed: matcher.PythonParsedFile,
                              match_dict: Dict[str, match.Match]):
    """Returns a grouping span for the containing simple AST node.

    Substitutions that lie within a simple statement or expression are
    grouped together and mapped to the span of the largest simple node they are
    a part of. Every other substitution is mapped to None.

    The idea here is that we want easy bite-sized chunks that are useful for
    quickly checking parseability, and for re-running the fixers over that
    chunk. Simple statements like import and return, as well as expressions
    that are part of larger statements, are perfect for this.

    Args:
      parsed: The ParsedFile for the same file.
      match_dict: The match dict.

    Returns:
      A grouping key, or None.
    """

    m = match_dict[ROOT_LABEL]
    if not isinstance(m, matcher.LexicalASTMatch):
      return None

    simple_node = parsed.nav.get_simple_node(m.matched)
    if simple_node is None:
      return None
    return (simple_node.first_token.startpos, simple_node.last_token.endpos)


class PyMatcherRewritingSearcher(BasePythonRewritingSearcher):
  """Parses the pattern as a ``--mode=py`` matcher."""

  @classmethod
  def from_pattern(cls, pattern: str,  templates: Optional[Dict[str, formatting.Template]]) -> "PyMatcherRewritingSearcher":
    """Creates a searcher from a ``--mode=py`` matcher."""
    return cls.from_matcher(
        evaluate.compile_matcher(pattern), templates=templates)


class PyExprRewritingSearcher(BasePythonRewritingSearcher):
  """Parses the pattern as a ``--mode=py.expr`` template."""

  @classmethod
  def from_pattern(cls, pattern: str,  templates: Optional[Dict[str, formatting.Template]]) -> "PyExprRewritingSearcher":
    """Creates a searcher from a ``--mode=py.expr`` template."""
    return cls.from_matcher(
        syntax_matchers.ExprPattern(pattern), templates=templates)


class PyStmtRewritingSearcher(BasePythonRewritingSearcher):
  """Parses the pattern as a ``--mode=py.stmt`` template."""

  @classmethod
  def from_pattern(cls, pattern: str,  templates: Optional[Dict[str, formatting.Template]]) -> "PyStmtRewritingSearcher":
    """Creates a searcher from a ``--mode=py.stmt`` template."""
    return cls.from_matcher(
        syntax_matchers.StmtPattern(pattern), templates=templates)

  def find_iter_parsed(
      self,
      parsed: matcher.PythonParsedFile) -> Iterable[substitution.Substitution]:
    # All node IDs that have been removed.
    removed_nodes = set([])
    # All node IDs that have been removed AND whose previous siblings have all
    # been removed, as well.
    removed_suite_prefix_nodes = set([])

    # TODO: Deduplicate this impl from the base find_iter_parsed.
    for match_dict in self.find_dicts_parsed(parsed):
      try:
        replacements = self.rewriter.rewrite(parsed, match_dict)
      except formatting.RewriteError as e:
        # TODO: Forward this up somehow.
        print('Skipped rewrite:', e, file=sys.stderr)
        continue

      sub = substitution.Substitution(
          matched_spans={
              label: s.span
              for label, s in match_dict.items()
              if s.span not in (None, (-1, -1))
          },
          replacements=replacements,
          primary_label=ROOT_LABEL,
      )
      yield self._sanitize_removed_stmt(
          parsed,
          match_dict,
          sub,
          removed_nodes,
          removed_suite_prefix_nodes,
      )

  def _sanitize_removed_stmt(
      self,
      parsed: matcher.PythonParsedFile,
      match_dict: Mapping[str, match.Match],
      sub: substitution.Substitution,
      removed_nodes: MutableSet[int],
      removed_suite_prefix_nodes: MutableSet[int],
  ) -> substitution.Substitution:
    """Ensure that a removed statement won't create syntax errors.

    Because of Python's whitespace-dependent structure, removing a statement can
    create a syntax error by leaving a suite (e.g. if-block) empty.

    Also, do our best to clean up the whitespace around the removal.

    Args:
      parsed: The file being parsed.
      match_dict: The match dict for this match.
      sub: The pre-sanitization Substitution.
      removed_nodes: IDs of AST statement nodes that have already be removed by
        previous iterations.
      removed_suite_prefix_nodes: IDs of AST statement nodes whose entire suites
        have been removed up to this point.

    Returns:
      A sanitized version of the Substitution.
    """
    if sub.replacements is None:
      return sub

    matched_spans = sub.matched_spans.copy()
    replacements = sub.replacements.copy()
    for metavar, replacement in replacements.items():
      match_ = match_dict[metavar]
      if not isinstance(match_, matcher.LexicalASTMatch):
        continue
      ast_match = match_.matched
      # TODO: Should a comment or another non-statement count?
      if replacement or not isinstance(ast_match, ast.stmt):
        continue
      if not isinstance(parsed.nav.get_parent(ast_match), list):
        raise formatting.RewriteError(
            'Bug in AST? Statement matched that isn\'t part of a "suite" '
            '(e.g. module, for-loop, etc.)')
      removed_nodes.add(id(ast_match))
      suite_node = parsed.nav.get_parent(parsed.nav.get_parent(ast_match))
      at_module_level = isinstance(suite_node, ast.Module)

      # TODO: Scan the intervening token range for comments, which
      # should not be deleted!
      next_ = parsed.nav.get_next_sibling(ast_match)
      prev = parsed.nav.get_prev_sibling(ast_match)
      if next_ is None and prev is None:
        # If this is the only statement in the suite, we only need to
        # add a placeholder to non-module suites to ensure valid syntax.
        if not at_module_level:
          replacements[metavar] = u'pass'
      elif next_ is not None:
        # If this statement occurs before the end of the suite, remove all
        # tokens until the next statement.
        if prev is None or id(prev) in removed_suite_prefix_nodes:
          removed_suite_prefix_nodes.add(id(ast_match))
        [start, _] = matched_spans[metavar]
        matched_spans[metavar] = (start, next_.first_token.startpos)
      else:  # prev is not None
        # If this statement is at the end of the suite, either handle the
        # case where all statements have been removed from the suite OR
        # try to remove tokens up to the *previous* statement. However, we
        # avoid removing tokens if the previous statement was removed since
        # this would create overlapping substitution spans.
        if id(prev) in removed_suite_prefix_nodes:
          if not at_module_level:
            replacements[metavar] = u'pass'
        elif id(prev) not in removed_nodes:
          [_, end] = matched_spans[metavar]
          matched_spans[metavar] = (prev.last_token.endpos, end)
        # Remove trailing semicolons to fix the (rare) case where the last
        # statement in a module is removed but leaves its semicolon
        # resulting in a syntax error.
        next_token = parsed.ast_tokens.next_token(ast_match.last_token)
        if next_token.string == ';':
          [start, _] = matched_spans[metavar]
          matched_spans[metavar] = (start, next_token.endpos)

    return substitution.Substitution(
        matched_spans=matched_spans,
        replacements=replacements,
        primary_label=sub.primary_label)


def rewrite_string(
    searcher: AbstractSearcher,
    source: Text,
    path: Text,
    max_iterations=1,
) -> Text:
  """Applies any replacements to the input source, and returns the result."""

  return formatting.apply_substitutions(
      source, find_iter(
          searcher,
          source,
          path,
          max_iterations=max_iterations,
      ))
