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
:mod:`~refex.python.matchers.base_matchers`
-------------------------------------------

Logical Matchers
~~~~~~~~~~~~~~~~

.. autoclass:: Anything

.. autoclass:: Unless

.. autoclass:: AllOf

.. autoclass:: AnyOf

.. autoclass:: Bind

Examples
........

These matchers will match anything::

    Anything()
    Unless(Unless(Anything()))
    AllOf(Anything(), Anything())
    AllOf(Anything())
    AllOf()

These matchers will match nothing::

    Unless(Anything())
    AllOf(Unless(Anything()))
    AnyOf()

Python Data Structure Matchers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: Equals

.. autoclass:: Contains

.. autoclass:: HasItem

.. autoclass:: ItemsAre

File Content Matchers
~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: MatchesRegex

.. autoclass:: FileMatchesRegex

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import re
from typing import Container, List
import weakref

import attr
import cached_property

from refex import match
from refex.python import matcher


@matcher.safe_to_eval
@attr.s(frozen=True)
class Anything(matcher.Matcher):
  """Matches anything, similar to the regex ``.``.

  Also available as ``_`` in ``--mode=py``.
  """

  def _match(self, context, candidate):
    return matcher.MatchInfo(
        matcher.create_match(context.parsed_file, candidate))


matcher.register_constant('_', Anything())


class TestOnlyRaisedError(Exception):
  """An exception raised in tests for error-handling behavior."""
  pass


@matcher.safe_to_eval
@attr.s(frozen=True)
class TestOnlyRaise(matcher.Matcher):
  """Raises an exception in match. Intended to test error-handling behavior."""

  message = attr.ib()

  def _match(self, context, candidate):
    del context  # unused
    del candidate  # unused
    raise TestOnlyRaisedError(self.message)


@attr.s(init=False, frozen=True)
class _NAryMatcher(matcher.Matcher):
  """Base class for matchers which take arbitrarily many submatchers in init."""

  _matchers = matcher.submatcher_list_attrib()

  def __init__(self, *matchers):
    super(_NAryMatcher, self).__init__()
    self.__dict__['_matchers'] = matchers


@matcher.safe_to_eval
class AllOf(_NAryMatcher):
  """Matches if and only if all submatchers do, and merges the results."""

  @matcher.accumulating_matcher
  def _match(self, context, candidate):
    for submatcher in self._matchers:
      yield submatcher.match(context, candidate)


@matcher.safe_to_eval
class AnyOf(_NAryMatcher):
  """Matches if at least one submatcher does, and returns the first result."""

  def _match(self, context, candidate):
    for submatcher in self._matchers:
      extra = submatcher.match(context, candidate)
      if extra is not None:
        return extra
    return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class Unless(matcher.Matcher):
  """Inverts a matcher and discard its bindings."""

  _submatcher = matcher.submatcher_attrib(walk=False)

  def _match(self, context, candidate):
    if self._submatcher.match(context, candidate) is None:
      return matcher.MatchInfo(
          matcher.create_match(context.parsed_file, candidate))
    else:
      return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class Bind(matcher.Matcher):
  """Binds an AST-matcher expression to a name in the result.

  Args:
    name: The name to bind to. Valid names must be words that don't begin with a
      double-underscore (``__``).
    submatcher: The matcher whose result will be bound to ``name``.
    on_conflict: A conflict resolution strategy. Must be a member of
      :class:`matcher.BindConflict <refex.python.matcher.BindConflict>`, or
      ``None`` for the default strategy (``ACCEPT``).
    on_merge: A merge strategy. Must be a member of
      :class:`matcher.BindMerge <refex.python.matcher.BindMerge>`,
      or None for the default strategy (``KEEP_LAST``).
  """
  _NAME_REGEX = re.compile(r'\A(?!__)[a-zA-Z_]\w*\Z')

  name = attr.ib()
  _submatcher = matcher.submatcher_attrib(default=Anything())
  _on_conflict = attr.ib(
      default=None,
      validator=attr.validators.in_(frozenset(matcher.BindConflict) | {None}))
  _on_merge = attr.ib(
      default=None,
      validator=attr.validators.in_(frozenset(matcher.BindMerge) | {None}))

  @name.validator
  def _name_validator(self, attribute, value):
    if not self._NAME_REGEX.match(value):
      raise ValueError(
          "invalid bind name: {value!r} doesn't match {regex}".format(
              value=value, regex=self._NAME_REGEX))

  def _match(self, context, candidate):
    """Returns the submatcher's match, with a binding introduced by this Bind.

    Args:
      context: The match context.
      candidate: The candidate node to be matched.

    Returns:
      An extended :class:`~refex.python.matcher.MatchInfo` with the new binding
      specified in the constructor. Conflicts are merged according to
      ``on_conflict``. If there was no match, or on_conflict result in a skip,
      then this returns ``None``.

      See matcher.merge_bindings for more details.
    """
    result = self._submatcher.match(context, candidate)
    if result is None:
      return None

    bindings = matcher.merge_bindings(
        result.bindings, {
            self.name:
                matcher.BoundValue(
                    result.match,
                    on_conflict=self._on_conflict,
                    on_merge=self._on_merge)
        })
    if bindings is None:
      return None
    return attr.evolve(result, bindings=bindings)

  @cached_property.cached_property
  def bind_variables(self):
    return frozenset([self.name]) | self._submatcher.bind_variables


# NOT safe_to_eval!
class SystemBind(Bind):
  """Internal variable-binding that is allowed to use a leading ``__``.

  This is used internally by Refex with a set of globally-known match names,
  like ``__root`` for the root binding.
  """
  _NAME_REGEX = re.compile(r'\A__\w+\Z')


@matcher.safe_to_eval
@attr.s(frozen=True)
class Rebind(matcher.Matcher):
  """Change the binding settings for all bindings in a submatcher.

  For example, one might want bindings in one part of the AST matcher to merge
  with each other, but then want it to be an error if these conflict anywhere
  else.

  Args:
    submatcher: The matcher whose bindings to rewrite.
    on_conflict: A conflict resolution strategy. Must be a member of
        :class:`matcher.BindConflict <refex.python.matcher.BindConflict>`, or
        ``None`` if ``on_conflict`` is not to be changed.
    on_merge: A merge strategy. Must be a member of
        :class:`matcher.BindMerge <refex.python.matcher.BindMerge>`, or ``None``
        if ``on_merge`` is not to be changed.
  """

  _submatcher = matcher.submatcher_attrib(default=Anything())
  _on_conflict = attr.ib(
      default=None,
      validator=attr.validators.in_(frozenset(matcher.BindConflict) | {None}))
  _on_merge = attr.ib(
      default=None,
      validator=attr.validators.in_(frozenset(matcher.BindMerge) | {None}))

  def _match(self, context, candidate):
    result = self._submatcher.match(context, candidate)
    if result is None:
      return None

    return attr.evolve(
        result,
        bindings={
            metavar: bind.rebind(
                on_conflict=self._on_conflict, on_merge=self._on_merge)
            for metavar, bind in result.bindings.items()
        })


######################
# Recursive matchers #
######################

# TODO: Finalize the API here.
# There is still some ugliness around lambdas and the semantics of recursion
# barrier equality.


@attr.s(repr=False, frozen=True)
class _Recurse(matcher.Matcher):
  """Recursion barrier for RecursivelyWrapped which avoids infinite loops."""
  # Deliberately removing from equality checks, since it will only ever point
  # to the RecursivelyWrapped node at a similar location. The assumption
  # is that they can only ever be created from a RecursivelyWrapped and the tie
  # to their parent is "hidden".
  # We also remove from .bind_variables walking to avoid infinite recursion.
  _recurse_to = matcher.submatcher_attrib(eq=False, order=False, walk=False)

  def _match(self, *args, **kwargs):
    return self._recurse_to.match(*args, **kwargs)

  def __repr__(self):
    return '%s(...)' % type(self).__name__


@matcher.safe_to_eval
class MaybeWrapped(AnyOf):
  """Matches the first arg possibly within the second arg.

  As an example, to match `X` or `X()`, one could write
  MaybeWrapped(Name(id='X'), lambda name: Call(func=name)).

  This is equivalent to AnyOf(Name(id='X'), Call(func=Name(id='X'))).
  """

  def __init__(self, inner, wrapper):
    super(MaybeWrapped, self).__init__(inner, wrapper(inner))


@matcher.safe_to_eval
class RecursivelyWrapped(AnyOf):
  """Matches the first arg wrapped by the second arg any number of times.

  As an example, to match ``X`` or ``X.a`` or ``X.a.b``, one could write
  ``RecursivelyWrapped(Name(id='X'), lambda name: Attribute(value=name))``.

  This is roughly equivalent to::

      AnyOf(
          Name(id='X'),
          Attribute(value=Name(id='X')),
          Attribute(value=Attribute(value=Name(id='X'))),
          ...,
      )

  Where ``...`` contains the infinite set of arbitrarily nested
  ``Attribute``-wrapped ``Name`` matchers.

  """

  def __init__(self, inner, wrapper):
    # This is the darkest, most evil thing I think I've ever done.
    super(RecursivelyWrapped, self).__init__(inner, wrapper(_Recurse(self)))

###################
# Python Matchers #
###################


@matcher.safe_to_eval
class Equals(matcher.ImplicitEquals):
  """Matches a candidate iff it equals ``value``."""
  pass


def _re_match_to_bindings(compiled_regex, text, m):
  """Converts an ``re.Match`` to a bindings dict."""
  return {
      bind_name:
      matcher.BoundValue(match.SpanMatch.from_text(text, m.regs[match_index]))
      for bind_name, match_index in compiled_regex.groupindex.items()
  }


@matcher.safe_to_eval
@attr.s(frozen=True)
class MatchesRegex(matcher.Matcher):
  """Matches a candidate iff it matches the ``regex``.

  The match must be complete -- the regex must match the full AST, not
  just a substring of it. (i.e. this has ``re.fullmatch`` semantics.)

  Any named groups are added to the bindings -- e.g. ``(xyz)`` does not add
  anything to the bindings, but ``(?P<name>xyz)`` will bind ``name`` to the
  subspan ``'xyz'``.

  The bound matches are neither lexical nor syntactic, but purely on codepoint
  spans.
  """
  _regex = attr.ib()  # type: str
  _subpattern = matcher.submatcher_attrib(default=Anything())  # type: matcher.Matcher

  @cached_property.cached_property
  def _wrapped_regex(self):
    """Wrapped regex with fullmatch semantics on match()."""
    # fullmatch is anchored to both the start and end of the attempted span.
    # since match is anchored at the start, we only need to anchor the end.
    # $ works for this. (Interestingly, ^ wouldn't work for anchoring at the
    # start of the span.)
    # This is a hack to maintain Python 2 compatibility until this can be
    # 3-only.
    return re.compile('(?:%s)$' % self._regex)

  def _match(self, context, candidate):
    matchinfo = self._subpattern.match(context, candidate)
    if matchinfo is None:
      return None

    span = matchinfo.match.span
    if span is None:
      return None  # can't search within this AST node.
    try:
      m = self._wrapped_regex.match(context.parsed_file.text, *span)
    except TypeError:
      return None
    if m is None:
      return None

    # TODO(b/118507248): Allow choosing a different binding type.
    bindings = matcher.merge_bindings(
        _re_match_to_bindings(self._wrapped_regex, context.parsed_file.text, m),
        matchinfo.bindings)

    if bindings is None:
      return None

    return matcher.MatchInfo(matchinfo.match, bindings)

  @cached_property.cached_property
  def bind_variables(self):
    return frozenset(
        self._wrapped_regex.groupindex) | self._subpattern.bind_variables


_file_matches_regex = weakref.WeakKeyDictionary()


@matcher.safe_to_eval
@attr.s(frozen=True)
class FileMatchesRegex(matcher.Matcher):
  """Matches iff ``regex`` matches anywhere in the candidate's file."""
  _regex = attr.ib()  # type: str

  @cached_property.cached_property
  def _compiled(self):
    return re.compile(self._regex)

  def _match(self, context, candidate):
    del candidate  # unused
    matches = _file_matches_regex.setdefault(context.parsed_file, {})
    if self._compiled not in matches:
      matches[self._compiled] = self._compiled.search(context.parsed_file.text)

    m = matches[self._compiled]
    if m is None:
      return None

    return matcher.MatchInfo(
        match.Match(),
        _re_match_to_bindings(self._compiled, context.parsed_file.text, m))

  @cached_property.cached_property
  def bind_variables(self):
    return frozenset(self._compiled.groupindex)


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasItem(matcher.Matcher):
  """Matches a container iff ``submatcher`` matches ``container[index]``.

  Fails the match if the container doesn't contain the key, or if the candidate
  node is not a container at all.
  """
  _index = attr.ib()
  _submatcher = matcher.submatcher_attrib(default=Anything())

  def _match(self, context, candidate):
    try:
      sub_candidate = candidate[self._index]
    except (LookupError, TypeError):
      return None
    else:
      m = self._submatcher.match(context, sub_candidate)
      if m is None:
        return None
      return matcher.MatchInfo(
          matcher.create_match(context.parsed_file, candidate), m.bindings)


@matcher.safe_to_eval
@attr.s(frozen=True)
class ItemsAre(matcher.Matcher):
  """Matches a sequence with an exact set of elements.

  The matched sequence must have exactly the same number of elements
  (support ``len()``) and each element will be matched against the corresponding
  matcher in ``matchers``.

  For example, this will create a matcher to match ``[1, 2]``, with ``a=1`` and
  ``b=2``:

      >>> m = ItemsAre([Bind('a'), Bind('b')])

  """

  # store the init parameters for a pretty repr and .bind_variables
  _matchers = matcher.submatcher_list_attrib()  # type: List[matcher.Matcher]

  @matcher.accumulating_matcher
  def _match(self, context, candidate):
    yield Unless(HasItem(len(self._matchers))).match(context, candidate)
    for i, m in enumerate(self._matchers):
      yield HasItem(i, m).match(context, candidate)


@matcher.safe_to_eval
@attr.s(frozen=True)
class Contains(matcher.Matcher):
  """Matches a collection if any item matches the given matcher.

  Fails the match if the candidate is not iterable.
  """

  _submatcher = matcher.submatcher_attrib()

  def _match(self, context, candidate):
    try:
      items = iter(candidate)
    except TypeError:
      return None
    for can in items:
      m = self._submatcher.match(context, can)
      if m is not None:
        return matcher.MatchInfo(
            matcher.create_match(context.parsed_file, candidate), m.bindings)
    return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class InLines(matcher.Matcher):
  """Matches an expression or statement that appears in the given lines.

  ``lines`` must be passed as a Sequence, not an iterable. It will be reused.

  Lines index from *1*, not from 0. So for a file::

      a = 1
      b = 2
      c = 3


  the matcher ``InLines([2])`` will return ``['b = 2']``, not ``['c = 3']``.
  """

  # Lines should normally be either a set or for contiguous sequences, a `range`
  # object produced by calling `range(x, y)`
  lines = attr.ib()  # type: Container[int]

  def _match(self, context, candidate):

    # Not all ast-nodes have the lineno attr, only expressions and statements
    # (so modules and some other weird ones don't).
    if getattr(candidate, 'lineno', None) in self.lines:
      return matcher.MatchInfo(
          matcher.create_match(context.parsed_file, candidate))
    else:
      return None
