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
# pyformat: disable
"""
:mod:`refex.python.matcher`
===========================

Support for high-level AST matchers.

These return extended match objects that can carry syntactic and/or lexical
information about the match.

.. autofunction:: parse_ast
.. autofunction:: find_iter


Parsing
-------

.. autoexception:: ParseError
   :show-inheritance:

.. autoclass:: PythonParsedFile
   :show-inheritance:

.. autoclass:: MatchContext
   :show-inheritance:


Matches
-------

.. autoclass:: LexicalMatch
   :show-inheritance:

.. autoclass:: LexicalASTMatch
   :show-inheritance:

Bindings
--------

.. autoclass:: BoundValue
  :members:
.. autoclass:: BindMerge
.. autoclass:: BindConflict

Matchers
--------
.. autoexception:: MatchError

.. autoclass:: MatchInfo

.. autoclass:: Matcher

Concrete Matchers
.................

.. autoclass:: DebugLabeledMatcher

.. autoclass:: ImplicitEquals
"""
# pyformat: enable


import abc
import ast
import collections
from collections.abc import Sequence
import contextlib
import copy
import difflib
import enum
import functools
import itertools
import reprlib
import sys
import tokenize
from typing import Any, Dict, Hashable, Iterator, Optional, Set, Text, Union
import weakref

from absl import logging
import asttokens
import attr
import cached_property
from refex import formatting
from refex import match
from refex import parsed_file

_match = match  # when `match` is shadowed, e.g. class attributes.


class MatchError(Exception):
  """An error raised when something went wrong in the match.

  This exception represents a bug in the way a matcher was used, not a bug in
  the matcher implementation or in refex itself.
  """
  # TODO: Present this to the user in some helpful way:
  #  * give line/column information for where the match went wrong in the source
  #    code.
  #  * give structured and tested information about specific kinds of errors
  #    (e.g. bind conflicts)
  #  * collect multiple match errors together and give a readable resulting
  #    error.


_registered_eval_matchers = set()


def _fix_init(cls):
  """Converts error messages about __init__ to instead say cls.__name__."""

  # One option:

  # init = cls.__init__
  # if not isinstance(init, types.FunctionType):
  #   return
  #
  # code = init.__code__
  # if sys.version_info >= (3, 8):
  #   code = code.replace(co_name=cls.__name__)
  # elif sys.version_info >= (3, 6):
  #   code = types.CodeType(
  #       code.co_argcount,
  #       # code.co_posonlyargcount,  3.8-only, but we have replace() then.
  #       <...>
  #       # NOT: code.co_name,
  #       cls.__name__,
  #       <...>
  #   )
  #
  # # Unlike code objects, function objects are mutable.
  # # So we can just copy one and modify the interesting properties.
  # init = copy.copy(init)
  # init.__code__ = code
  # cls.__init__ = init
  # return cls

  # However, that seems like the sort of thing we look back on later and think,
  # "Ah yes, that's where it all started going wrong".
  # Instead, let's do something stupid but less foolish.
  old_init = cls.__init__
  def new_init(*args, **kwargs):
    try:
      old_init(*args, **kwargs)
    except TypeError as e:
      if len(e.args) == 1 and isinstance(e.args[0], str):
        if sys.version_info >= (3, 10):
          # In Python 3.10+, it contains `OriginClassName.__init__` instead of
          # simply `__init__`.
          origin_name = old_init.__qualname__
        else:
          origin_name = '__init__'
        e.args = (e.args[0].replace(origin_name, cls.__name__),)
      raise
  cls.__init__ = new_init
  return cls


def safe_to_eval(cls):
  """Makes a class available from evaluate.py, and cleans its errors for users."""
  cls = _fix_init(cls)
  _registered_eval_matchers.add(cls)
  return cls


def is_safe_to_eval(cls):
  """Returns whether or not a class is safe to eval in evaluate.py."""
  return cls in _registered_eval_matchers


# Constants for the semiliteral_eval in evaluate.py
# These will generally be enums and other constants that should be available
# in order to call into matchers.
registered_constants = {}


def register_enum(cls):
  """Registers an enum for use in evaluate.py."""
  for constant in cls:
    register_constant(str(constant), constant)
  return cls


def register_constant(name: str, constant: Any):
  """Registers a constant for use in evaluate.py."""
  if name in registered_constants:
    raise AssertionError('Two conflicting constants: %r, %r' % constant,
                         registered_constants[name])
  registered_constants[name] = constant


def coerce(value):  # Nobody uses coerce. pylint: disable=redefined-builtin
  """Returns the 'intended' matcher given by `value`.

  If `value` is already a matcher, then this is what is returned.

  If `value` is anything else, then coerce returns `ImplicitEquals(value)`.

  Args:
    value: Either a Matcher, or a value to compare for equality.
  """
  if isinstance(value, Matcher):
    return value
  else:
    return ImplicitEquals(value)


def _coerce_list(values):
  return [coerce(v) for v in values]


# TODO(b/199577701): drop the **kwargs: Any in the *_attrib functions.

_IS_SUBMATCHER_ATTRIB = __name__ + '._IS_SUBMATCHER_ATTRIB'
_IS_SUBMATCHER_LIST_ATTRIB = __name__ + '._IS_SUBMATCHER_LIST_ATTRIB'


def submatcher_attrib(*args, walk: bool = True, **kwargs: Any):
  """Creates an attr.ib that is marked as a submatcher.

  This will cause the matcher to be automatically walked as part of the
  computation of .bind_variables. Any submatcher that can introduce a binding
  must be listed as a submatcher_attrib or submatcher_list_attrib.

  Args:
    *args: Forwarded to attr.ib.
    walk: Whether or not to walk to accumulate .bind_variables.
    **kwargs: Forwarded to attr.ib.

  Returns:
    An attr.ib()
  """
  if walk:
    kwargs.setdefault('metadata', {})[_IS_SUBMATCHER_ATTRIB] = True
  kwargs.setdefault('converter', coerce)
  return attr.ib(*args, **kwargs)


def submatcher_list_attrib(*args, walk: bool = True, **kwargs: Any):
  """Creates an attr.ib that is marked as an iterable of submatchers.

  This will cause the matcher to be automatically walked as part of the
  computation of .bind_variables. Any submatcher that can introduce a binding
  must be listed as a submatcher_attrib or submatcher_list_attrib.

  Args:
    *args: Forwarded to attr.ib.
    walk: Whether or not to walk to accumulate .bind_variables.
    **kwargs: Forwarded to attr.ib.

  Returns:
    An attr.ib()
  """
  if walk:
    kwargs.setdefault('metadata', {})[_IS_SUBMATCHER_LIST_ATTRIB] = True
  kwargs.setdefault('converter', _coerce_list)
  return attr.ib(*args, **kwargs)


# TODO: make MatchObject, MatchInfo, and Matcher generic, parameterized
# by match type. Since pytype doesn't support generics yet, that's not an
# option, but it'd greatly clarify the API by allowing us to classify matchers
# by the kind of object they work on.


# We compare for equality during e.g. equivalence checks when combining multiple
# python searchers, but we cache the entire object, so equality being identity
# is fine.
@attr.s(frozen=True, eq=False)
class PythonParsedFile(parsed_file.ParsedFile):
  """Preprocessed file information, including the AST etc."""
  ast_tokens = attr.ib(type=asttokens.ASTTokens)
  tree = attr.ib(type=ast.Module)
  nav = attr.ib(type='AstNav')


@attr.s(frozen=True, eq=False)
class MatchContext:
  """Per-match and per-file context.

  One prototype ``MatchContext`` exists per file, containing shared data across
  all successful runs. A separate derived instance is made per top-level
  invocation of a matcher, which can be used to keep state across a match that
  shouldn't transfer to subsequent match attempts. (For example, a matcher that
  must match exactly the same string across all invocations inside a match, or
  similar.)
  """
  parsed_file = attr.ib(type=PythonParsedFile)

  _has_successful_run = attr.ib(type=Set[Hashable], factory=set)
  _has_match_run = attr.ib(type=Set[Hashable], factory=set)

  def new(self) -> 'MatchContext':
    """Returns a new context for the same file, sharing ``has_run`` state."""
    return attr.evolve(self, has_match_run=set())

  def has_run(self, key: Hashable) -> bool:
    """Returns if ``set_has_run`` was called in this or a prior successful match.

    Check ``has_run(key)`` before doing work that should be done once-per-file,
    and then call ``set_has_run(key)`` if that work completed successfully.

    For example, this can be used to add an import only on the first added use
    of that import.

    Args:
      key: Any unique object, but should be the matcher.

    Returns:
      ``True`` if ``set_has_run(key)`` was executed either in an earlier
      successful match attempt, or in the current match attempt.
      ``False`` otherwise.
    """
    return key in self._has_successful_run or key in self._has_match_run

  def set_has_run(self, key: Hashable):
    self._has_match_run.add(key)

  def update_success(self, successful_context: 'MatchContext'):
    """Update the match context based on a successful match."""
    self._has_successful_run.update(successful_context._has_match_run)


@attr.s(frozen=True)
class LexicalMatch(match.Match):
  """Lexical match with no AST information.

  .. attribute:: first_token

     The first token delimiting the matched lexical span.

  .. attribute:: last_token

     The last token delimiting the matched lexical span.

  .. attribute:: include_first

     Whether this starts before or after the first token.

  .. attribute:: include_last

     Whether this ends before or after the last token.

  .. attribute:: string

     The matched string.

  .. attribute:: span

     The matched span.
  """
  # TODO: allow you to specify more fine-grained token spans.
  # in particular, allow matches to start immediately after the end of a token
  # vs at the beginning of the next token. (This differs only by whitespace)
  _text = attr.ib(type=Text)
  first_token = attr.ib(type=asttokens.util.Token)
  last_token = attr.ib(type=asttokens.util.Token)

  # Useful for tweaking spans precisely.
  include_first = attr.ib(type=bool, default=True)
  include_last = attr.ib(type=bool, default=True)

  @cached_property.cached_property
  def string(self):
    start, end = self.span
    return self._text[start:end]

  @cached_property.cached_property
  def span(self):
    if self.include_first:
      start = self.first_token.startpos
    else:
      start = self.first_token.endpos
    if self.include_last:
      end = self.last_token.endpos
    else:
      end = self.last_token.startpos
    return start, end


@attr.s(frozen=True)
class LexicalASTMatch(match.ObjectMatch, LexicalMatch):
  """AST match with adjustable start/end tokens."""
  # Override for better type checking.
  matched: ast.AST = None


# TODO: describe create_match with overloads for more precise type checking.


def create_match(
    parsed: PythonParsedFile, matched: Any
) -> Union[LexicalASTMatch, match.StringMatch, match.ObjectMatch]:
  """Construct the most precise match for an object.

  This does a type check on `matched` to see if it has lexical information, but
  ideally this should be knowable at compile-time (if only Python had templates
  and template specialization).

  Args:
    parsed: A ParsedFile.
    matched: An arbitrary matched object.

  Returns:
    A LexicalASTMatch if obj is an AST node with lexical information,
    a match.StringMatch if matched is a string, or a match.ObjectMatch
    otherwise.
  """

  if _is_lexical_match(matched):
    return LexicalASTMatch(matched, parsed.text, matched.first_token,
                           matched.last_token)
  elif isinstance(matched, str):
    return match.StringMatch(string=matched)
  else:
    return match.ObjectMatch(matched)


def _is_lexical_match(matched: Any) -> bool:
  """Returns whether the match can be a lexical one.

  Its not well documented what ast objects return token information and
  which ones don't, and there are known instances of the token information
  being wrong in certain cases.

  Args:
    matched: the matched object.

  Returns:
    whether it can be a LexicalASTMatch or not.
  """
  first_token = getattr(matched, 'first_token', None)
  last_token = getattr(matched, 'last_token', None)
  if not (first_token and last_token):
    return False

  if isinstance(matched, ast.arguments):
    # When there are no args, then the offsets are wrong.
    return bool(matched.args)
  if isinstance(matched, ast.alias):
    # The offsets correspond to the "import" keyword instead of the alias name.
    return False
  return True


def ast_equivalent(ast1, ast2):
  """Returns whether ast1 and ast2 are structurally equal ASTs.

  Two ASTs are considered equivalent if:
    1) they are the same type and all their submembers are also equivalent, or
    2) they are both expression contexts.

  Expression contexts are ignored for equivalence checking to allow identifying
  the repetition in e.g. "a = a". The ASTs are different, but not in a way that
  matters, because we don't care about load vs store.

  Args:
    ast1: One AST to compare.
    ast2: Another AST to compare.

  Returns:
    True if equivalent, False if not.
  """
  if ast1 is ast2:
    # short circuit in the easy case that these are literally the same AST node.
    return True

  pairs_to_compare = [(ast1, ast2)]
  while pairs_to_compare:
    lhs, rhs = pairs_to_compare.pop()
    if not isinstance(lhs, ast.AST) or not isinstance(rhs, ast.AST):
      if lhs != rhs:
        return False
      continue

    lhs_type = type(lhs)
    rhs_type = type(rhs)
    if lhs_type != rhs_type:
      # Only count these as equal if they're differing expr_contexts, as
      # discussed in the docstring.
      return (isinstance(lhs, ast.expr_context) and
              isinstance(rhs, ast.expr_context))

    for a in lhs_type._fields[::-1]:
      # Reversing the fields so that the stack pop order is a traditional
      # left to right DFS.
      pairs_to_compare.append((getattr(lhs, a, None), getattr(rhs, a, None)))
  return True


@attr.s(frozen=True)
class _CallableVariant:
  """Decorator for a callable enum variant."""
  _f = attr.ib()

  def __call__(self, *args, **kwargs):
    return self._f(*args, **kwargs)


@register_enum
class BindConflict(enum.Enum):
  """What to do if two bindings share the same name.

  Each of these is a value that can be passed as the ``merge`` parameter to
  :class:`BoundValue`, or the ``on_conflict`` parameter to
  :class:`base_matchers.Bind <refex.python.matchers.base_matchers.Bind>`.

  .. attribute:: MERGE

     Merge the two bindings (using the chosen :class:`BindMerge` strategy).

  .. attribute:: SKIP

     Fail this match.

  .. attribute:: ERROR

     Raise a :exc:`MatchError`

  .. attribute:: MERGE_IDENTICAL

     Merge if the values are equal, otherwise ``SKIP``.

  .. attribute:: MERGE_IDENTICAL_OR_ERROR

     Merge if the values are equal, otherwise ``ERROR``.

  .. attribute:: MERGE_EQUIVALENT_AST

     Merge if the values are "equivalent" ASTs, otherwise ``SKIP``.

     Two ASTs are equivalent if they are structurally identical, modulo
     lvalue/rvalue distinctions. (Variables are considered equivalent if
     they have the same name, even if one is used for a load and the other
     is used for a store.)

  .. attribute:: MERGE_EQUIVALENT_AST_OR_ERROR

     Merge if the values are "equivalent" ASTs, otherwise ``ERROR``.
  """

  # The functions in this class are transformed into enum values by
  # @_function_dispatch_enum.
  # pylint: disable=no-self-argument,invalid-name

  # How conflict resolver functions work:
  #  If they return False, merge_bindings will return None
  #  If they return True, merge_bindings will use the chosen BindMerge strategy.
  #  If they raise an exception, merge_bindings will raise that exception.

  @_CallableVariant
  def MERGE(metavar, bind1, bind2):
    del metavar, bind1, bind2  # unused
    return True

  @_CallableVariant
  def SKIP(metavar, bind1, bind2):
    del metavar, bind1, bind2  # unused
    return False

  @_CallableVariant
  def ERROR(metavar, bind1, bind2):
    raise MatchError('Conflicting binds for {metavar}:'
                     ' values were: {bind1.value!r}, {bind2.value!r}'.format(
                         metavar=metavar, bind1=bind1, bind2=bind2))

  @_CallableVariant
  def MERGE_IDENTICAL(metavar, bind1, bind2):
    del metavar  # unused
    return bind1 == bind2

  @_CallableVariant
  def MERGE_IDENTICAL_OR_ERROR(metavar, bind1, bind2, ERROR=ERROR):
    return bind1 == bind2 or ERROR(metavar, bind1, bind2)

  @_CallableVariant
  def MERGE_EQUIVALENT_AST(metavar, bind1, bind2):
    match1 = bind1.value
    match2 = bind2.value
    if not isinstance(match1, match.ObjectMatch):
      return None
    if not isinstance(match2, match.ObjectMatch):
      return None
    return ast_equivalent(match1.matched, match2.matched)

  @_CallableVariant
  def MERGE_EQUIVALENT_AST_OR_ERROR(metavar,
                                    bind1,
                                    bind2,
                                    MERGE_EQUIVALENT_AST=MERGE_EQUIVALENT_AST,
                                    ERROR=ERROR):
    return (MERGE_EQUIVALENT_AST(metavar, bind1, bind2) or
            ERROR(metavar, bind1, bind2))


@register_enum
class BindMerge(enum.Enum):
  """Bind conflict merge strategies.

  If a conflict is considered mergeable by the :class:`BindConflict` parameter,
  this says how to merge the two.

  .. attribute:: KEEP_FIRST

  .. attribute:: KEEP_LAST
  """

  # The functions in this class are transformed into enum values by
  # @_function_dispatch_enum.
  # pylint: disable=no-self-argument,invalid-name

  # How merge functions work:
  # Given bind1, bind2, return a merged bind.

  @_CallableVariant
  def KEEP_FIRST(bind1, bind2):
    del bind2  # unused
    return bind1

  @_CallableVariant
  def KEEP_LAST(bind1, bind2):
    del bind1  # unused
    return bind2


@attr.s(frozen=True)
class BoundValue:
  """Mergeable bound values.

  Two :class:`BoundValue` objects will only be merged if they have equal merge
  attributes -- i.e. if they both agree on how to merge with each other.
  Anything else results in a :exc:`MatchError`.

  Attributes:
    value: A value that has a bound name somewhere.
    on_conflict: A strategy from :class:`BindConflict` for merging two bound
      values. Defaults to ``MERGE``.
    on_merge: A strategy from :class:`BindMerge` for how to merge. Defaults to
      ``KEEP_LAST``.
  """

  value = attr.ib(type=Any)
  on_conflict = attr.ib(
      default=None,
      converter=attr.converters.default_if_none(BindConflict.MERGE),
      type=BindConflict)
  on_merge = attr.ib(
      default=None,
      converter=attr.converters.default_if_none(BindMerge.KEEP_LAST),
      type=BindMerge)

  def rebind(self, on_conflict=None, on_merge=None):
    """Returns a new BoundValue with different merge settings.

    Args:
      on_conflict: if not ``None``, a new value for ``on_conflict``.
      on_merge: if not ``None``, a new value for ``on_merge``.

    Returns:
      A new :class:`BoundValue` with the same ``value``, and the updated merge
      settings.
    """
    if on_conflict is None:
      on_conflict = self.on_conflict
    if on_merge is None:
      on_merge = self.on_merge
    return attr.evolve(self, on_conflict=on_conflict, on_merge=on_merge)


def merge_bindings(lhs, rhs):
  """Merges two binding dicts and return the result.

  Args:
    lhs: A dict from labels to BoundValues.
    rhs: Another dict from labels to BoundValues.

  Raises:
    MatchError: the variables could not be merged due to an error in how the
        matchers were used.

  Returns:
    None if the match cannot succeed due to a failed merge, or else a new dict
    mapping labels to merged BoundValues.
  """
  lhs_keys = lhs.keys()
  rhs_keys = rhs.keys()

  merged_bindings = {}

  # We try to merge _all_ matches to find errors, even if we've already
  # determined that the match should be skipped for non-error reasons.
  # If skip_result is True, then we encountered a non-error skip reason and
  # should return None at the end.
  skip_result = False

  for key in lhs_keys & rhs_keys:
    lhs_value = lhs[key]
    rhs_value = rhs[key]
    # Using a weird type check here because we are secretly actually doing a
    # multidispatch on the types of both the LHS and RHS. For simplicity, we
    # require them both to be the same type.
    # (It would be unfortunate if a matcher of one type could accidentally
    #  override the behavor of UniqueBoundValue, or other things like that.)
    if lhs_value.on_conflict != rhs_value.on_conflict:
      raise MatchError(
          'Conflicting binds for {metavar}:'
          " can't merge bindings with two different conflict resolution"
          ' strategies {lhs_value.on_conflict} != {rhs_value.on_conflict};'
          ' values were: {lhs_value.value!r}, {rhs_value.value!r}'.format(
              metavar=key, lhs_value=lhs_value, rhs_value=rhs_value))
    if lhs_value.on_merge != rhs_value.on_merge:
      raise MatchError(
          'Conflicting binds for {metavar}:'
          " can't merge bindings with two different merge strategies"
          ' {lhs_value.on_conflict} != {rhs_value.on_conflict};'
          ' values were: {lhs_value.value!r}, {rhs_value.value!r}'.format(
              metavar=key, lhs_value=lhs_value, rhs_value=rhs_value))
    on_conflict = lhs_value.on_conflict.value
    if on_conflict(key, lhs_value, rhs_value):
      on_merge = lhs_value.on_merge.value
      merged_bindings[key] = on_merge(lhs_value, rhs_value)
    else:
      # We'll return None at the end, but let's keep going to see if any errors
      # crop up
      skip_result = True

  if skip_result:
    return None

  merged_bindings.update((k, lhs[k]) for k in lhs_keys - rhs_keys)
  merged_bindings.update((k, rhs[k]) for k in rhs_keys - lhs_keys)
  return merged_bindings


def merge_replacements(lhs, rhs):
  conflicts = lhs.keys() & rhs.keys()
  if conflicts:
    raise MatchError(f'Conflicting replacements: {conflicts}')
  merged = {}
  merged.update(lhs)
  merged.update(rhs)
  return merged


@attr.s(frozen=True)
class MatchInfo:
  """A result object containing a successful match.

  Attributes:
    match: The match for the top-level matcher.
    replacement: the replacement for the match, if any.
    bindings: A dict of bound matches for later reuse.
    replacements: A dict of replacements for given bindings.
  """
  match = attr.ib(type=_match.Match)
  # TODO: also add a top-level `replacement` variable, replacing the magic root.
  bindings = attr.ib(factory=dict, type=Dict[str, BoundValue])
  replacements = attr.ib(factory=dict, type=Dict[str, formatting.Template])

  @classmethod
  def from_diff(
      cls,
      metavariable_prefix: str,
      before: str,
      after: str,
      match=_match.Match(),
  ) -> 'MatchInfo':
    """Returns a minimized ``MatchInfo`` for the diff of before/after.

    Args:
      metavariable_prefix: the prefix for the named bindings/replacements.
      before: the entire file, before.
      after: the entire file, after.
      match: The match for the MatchInfo.

    Returns:
      A minimized ``MatchInfo`` for that diff.
    """
    diffs = difflib.Differ().compare(
        before.splitlines(True),
        after.splitlines(True),
    )
    # change the diffs to always end with an "unchanged" line, triggering
    # an append to `replacements`.
    diffs = itertools.chain(diffs, ['  '])
    start_offset = 0
    end_offset = 0
    replacement = []
    replacements = []
    for line in diffs:
      prefix = line[:2]
      line = line[2:]
      if prefix == '  ':
        if replacement or start_offset != end_offset:
          replacements.append((start_offset, end_offset, replacement))
          replacement = []
        end_offset += len(line)
        start_offset = end_offset
      elif prefix == '+ ':
        replacement.append(line)
      elif prefix == '- ':
        end_offset += len(line)
      elif prefix == '? ':
        pass
      else:
        raise AssertionError(f'Unknown diff prefix: {prefix!r}')

    assert not replacement

    match_bindings = {}
    match_replacements = {}
    for i, (start, end, added_strings) in enumerate(replacements):
      metavar = f'{metavariable_prefix}.{i}'
      match_bindings[metavar] = BoundValue(
          _match.SpanMatch.from_text(before, (start, end)))
      match_replacements[metavar] = formatting.LiteralTemplate(
          ''.join(added_strings))
    return cls(match, match_bindings, match_replacements)


def _stringify_candidate(context, candidate):
  """Returns a debug string suitable for logging information about `candidate` in `context`."""
  if not context:
    return '<No context for %r>' % (candidate,)
  if isinstance(candidate, ast.AST):
    return 'line %s: %r' % (getattr(candidate, 'lineno', '??'),
                            context.parsed_file.ast_tokens.get_text(candidate))
  elif isinstance(candidate, Sequence) and not isinstance(candidate, str):
    return reprlib.repr([
        _stringify_candidate(context, subcandidate)
        for subcandidate in candidate
    ])
  else:
    return reprlib.repr(candidate)


@attr.s(frozen=True)
class Matcher(metaclass=abc.ABCMeta):
  """An immutable AST node matcher.

  Reusable subclasses are in :mod:`refex.python.matchers`.

  .. automethod:: match
  """

  def match(self, context: MatchContext, candidate: Any) -> Optional[MatchInfo]:
    """Matches a candidate value.

    Args:
      context: A :class:`MatchContext` object with additional metadata.
      candidate: A candidate object to be matched against.

    Returns:
      A :class:`MatchInfo` object, or ``None`` if the match failed.
    """
    matched = self._match(context, candidate)
    if logging.vlog_is_on(self._log_level):
      self._log_match(context, candidate, matched)
    return matched

  def _log_match(self, context, candidate, matched):
    if not matched:
      logging.vlog(self._log_level + 1, 'No match for %s on candidate %r (%s)',
                   self, candidate, _stringify_candidate(context, candidate))
    else:
      logging.vlog(self._log_level,
                   'Found match (%r) for %s on candidate %r (%s)', matched,
                   self, candidate, _stringify_candidate(context, candidate))

  @property
  def _log_level(self):
    """Minimum logging level used for any verbose logs generated by this matcher."""
    return logging.DEBUG + 1

  @abc.abstractmethod
  def _match(self, context, candidate):
    """Per-matcher implementation of `match`."""
    return None

  def _submatchers(self):
    """Yields the submatchers that are direct children of this matcher.

    Any node that introduces a binding _must_ be available as a submatcher
    attribute, so that .bind_variables is accurate.
    """
    for attribute in attr.fields(type(self)):
      if attribute.metadata.get(_IS_SUBMATCHER_ATTRIB, False):
        yield getattr(self, attribute.name)
      elif attribute.metadata.get(_IS_SUBMATCHER_LIST_ATTRIB, False):
        for submatcher in getattr(self, attribute.name):
          yield submatcher

  @cached_property.cached_property
  def bind_variables(self):
    """Returns the set of variables that _may_ be bound in a match.

    A variable being in this set is not a guarantee that it will be bound.
    """
    bindings = set()
    for matcher in self._submatchers():
      bindings |= matcher.bind_variables
    return frozenset(bindings)

  #: The types of objects that may be matched, as a frozenset.
  #:
  #: None if any type is eligible for matching.
  type_filter = None


def accumulating_matcher(f):
  """Creates a matcher from boolean-and-ing a generator of match results.

  A function that is decorated with this is expected to yield up match results.
  If the match is None (a failure), or its bindings fail to merge with
  previously yielded matches, then the generator is halted and the match fails.
  Otherwise, the generator is passed the MatchInfo.match, and continues.

  When the generator terminates, a match is returned with the `candidate` as the
  matched object, and the merged submatcher bindings as the bindings.

  For an example of basic usage:

      @matcher.accumulating_matcher
      def _match(self, context, candidate):
        "Matches iff both self._submatcher_1 and self._submatcher_2 match."
        yield self._submatcher_1.match(context, candidate)
        yield self._submatcher_2.match(context, candidate)

  This is equivalent to:

      def _match(self, context, candidate):
        result_1 = self._submatcher_1.match(context, candidate)
        if result_1 is None: return None

        result_2 = self._submatcher_2.match(context, candidate)
        if result_2 is None: return None

        merged_bindings = matcher.merge_bindings(result_1.bindings,
                                                 result_2.bindings)
        if merged_bindings is None: return None

        return matcher.MatchInfo(matcher.create_match(context.parsed_file,
                                                      candidate),
                                 bindings)

  Args:
    f: a generator function as described above, taking (self, context,
      candidate).

  Returns:
    a _match function.
  """

  @functools.wraps(f)
  def wrapped(self, context, candidate):
    """Documented above."""
    bindings = {}
    replacements = {}
    with contextlib.closing(f(self, context, candidate)) as coro_gen:
      try:
        mi = next(coro_gen)
        while True:
          if mi is None:
            return None
          bindings = merge_bindings(bindings, mi.bindings)
          if bindings is None:
            return None
          replacements = merge_replacements(replacements, mi.replacements)
          mi = coro_gen.send(mi.match)
      except StopIteration:
        pass

    return MatchInfo(
        create_match(context.parsed_file, candidate),
        bindings=bindings,
        replacements=replacements)

  return wrapped


@attr.s(frozen=True)
class ImplicitEquals(Matcher):
  """Matches a candidate iff it equals the provided value.

  This is implicitly created whenever a matcher was expected, but a non-matcher
  value was provided. For example, ``Contains(3)`` creates the matcher
  ``Contains(ImplicitEquals(3))``.

  To explicitly compare for equality, use
  :class:`base_matchers.Equals <refex.python.matchers.base_matchers.Equals>`.
  :class:`ImplicitEquals` should never be used explicitly (but is fine to use
  implicitly).
  """

  _value = attr.ib(type=Any)

  def _match(self, context, candidate):
    if candidate == self._value:
      return MatchInfo(create_match(context.parsed_file, candidate))
    else:
      return None


class ParseError(Exception):
  """Exception raised if input failed to parse.

  The stringified exception specifies all the necessary/available debug
  information about the error, location, etc., but does not include the
  filename.
  """


@attr.s(frozen=True)
class _CompareById:
  """Wrapper object to compare things by identity."""
  value = attr.ib(eq=False)
  _id = attr.ib(init=False)

  @_id.default
  def _id_default(self):
    return id(self.value)


@enum.unique
class _BreadcrumbType(enum.Enum):
  ATTR = 0
  ITEM = 1


@attr.s(frozen=True)
class AstNav:
  """AST graph navigation.

  AstNav gives the parent and sibling relationships of an AST node. It is used
  directly by matchers who can query the graph via the public API, but is not
  used by end-users of Refex itself.

  The passed in AST must not be mutated or it will invalidate the AstNav.

  Note that ASTs often involve reference reuse. For example, a single ast.Add()
  object is used for all addition BinOps. The tree passed in to AstNav must be
  preprocessed to eliminate reference reuse.
  """
  _tree = attr.ib()

  @cached_property.cached_property
  def _parent_breadcrumb(self):
    """Gets a dict from AST to its parent, and how to get from the parent back.

    Specifically the dict is from child to (parent, type, key), where the
    tuple can have only these combinations of values:

        If all three are None, there is no parent.
        If type == _BreadcrumbType.ATTR, then getattr(parent, key) is child
        If type == _BreadcrumbType.ITEM, then parent[key] is child

    _parent_breadcrumb is computed lazily because most matchers are not
    interested in this information.

    Returns:
      The parent breadcrumb dict.
    """
    nodes = [self._tree]
    parents = {_CompareById(self._tree): (None, None, None)}
    while nodes:
      node = nodes.pop()
      if isinstance(node, ast.AST):
        for attribute in node._fields:
          attr_value = getattr(node, attribute, None)
          if attr_value is None:
            continue
          parents[_CompareById(attr_value)] = (node, _BreadcrumbType.ATTR,
                                               attribute)
          nodes.append(attr_value)
      elif isinstance(node, list):
        for i, subnode in enumerate(node):
          parents[_CompareById(subnode)] = (node, _BreadcrumbType.ITEM, i)
          nodes.append(subnode)
      else:
        # A string attribute, something along those lines.
        continue
    return parents

  def _get_breadcrumb(self, child):
    child = _CompareById(child)
    # TODO(b/133340847): Investigate and remove this pylint suppression.
    if child not in self._parent_breadcrumb:  # pylint: disable=unsupported-membership-test
      # It may seem tempting to raise here, but it's generally useful to do
      # things like "match x if its parent is Y", and apply this in a tree
      # search blindly.
      return None, None, None
    return self._parent_breadcrumb[child]

  def get_parent(self, node):
    """Gets the parent of this node.

    Args:
      node: an AST node.

    Returns:
      The parent, if the node has a parent. If the node is the root of the tree,
      returns None.
    """
    parent, _, _ = self._get_breadcrumb(node)
    return parent

  def get_prev_sibling(self, node):
    """Gets the previous node in the list this is a part of, if any.

    Args:
      node: an AST node.

    Returns:
      None if this is not in a node list (e.g. stmt suite), or if there is no
      previous sibling. Otherwise, returns the sibling.
    """
    parent, crumb_type, key = self._get_breadcrumb(node)
    if parent is None or crumb_type == _BreadcrumbType.ATTR or key == 0:
      return None
    return parent[key - 1]

  def get_next_sibling(self, node):
    """Gets the next node in the list this is a part of, if any.

    Args:
      node: an AST node.

    Returns:
      None if this is not in a node list (e.g. stmt suite), or if there is no
      next sibling. Otherwise, returns the sibling.
    """
    parent, crumb_type, key = self._get_breadcrumb(node)
    if parent is None or crumb_type == _BreadcrumbType.ATTR:
      return None
    new_index = key + 1
    if new_index == len(parent):
      return None
    return parent[new_index]

  def get_simple_node(self, node: ast.AST):
    """Finds the 'simple' node that contains this one.

    A simple node is either a simple statement node, or an expression node
    whose parent is not a simple node.

    Args:
      node: The AST node that must be covered.

    Returns:
      A simple node, if the span covers exactly one simple node, or None
      otherwise.
    """
    last_node = None
    while True:
      # Guaranteed to terminate as eventually we reach the module body.
      # hasattr case will only be reached if that is the original argument.
      if hasattr(node, 'body'):
        return last_node
      if not isinstance(node, list):
        # the node.body is not the simple node, the thing inside it was.
        last_node = node
      node = self.get_parent(node)


def _uniqueify_distinct_ast(tree):
  """Returns a version of tree where all nodes have a unique identity.

  i.e. if a given node is in a different position in the tree, it will be given
  a different identity, even if it is equal on every attribute.

  Args:
    tree: An AST node. This is potentially mutated.

  Returns:
    An uniqueified version of tree.
  """

  # Only copy when a duplicate is found, to avoid the O(n^2) worst algorithm.
  seen_ids = set()

  class CopyTransformer(ast.NodeTransformer):

    def visit(self, node):
      node = self.generic_visit(node)
      if id(node) in seen_ids:
        return copy.copy(node)
      else:
        seen_ids.add(id(node))
        return node

  return CopyTransformer().visit(tree)


_FORMATTING_TOKENS = {
    tokenize.NL,
    tokenize.COMMENT,
}


def _indents(tokens):
  """Yields the offsets of the start of each indented block.

  This works around a feature in the lexical token stream where comments
  are not considered indented, because the indent token is emitted before the
  first _logical_ line.

  Args:
    tokens: An ASTTokens-provided token stream.

  Yields:
    The "true" offset of an indented block (the startpos of the first NEWLINE).
  """
  # The first newline in a set of "not-important" tokens.
  # This is always a NEWLINE (it's the definition of NEWLINE vs NL).
  newline_start = None
  for token in tokens:
    if token.type in _FORMATTING_TOKENS:
      pass
    elif token.type == tokenize.NEWLINE:
      newline_start = token.endpos
    elif token.type == tokenize.INDENT:
      if newline_start is None:
        # "This shouldn't happen." Give up, use INDENT after all.
        yield token.startpos
      else:
        yield newline_start
    else:
      newline_start = None


def _pragmas(tokens):
  """Yields all pragmas from the comments in the Python source file."""
  # Whether or not this is the start of a new line.
  # If it is, then a pragma applies for the rest of the current block.
  fresh_line = True
  # The location of the start of the current line.
  # On non-fresh lines, this is where a pragma's effect starts.
  line_start = 0
  # Number of indents. We use this to decide when a block ends.
  indents = 0
  # Mapping of indents to not-yet-complete pragmas and their starts.
  incomplete_pragmas = collections.defaultdict(list)
  # Set of indents we haven't seen yet.
  # We don't use INDENT tokens directly for the reasons described
  # in the docstring for _indents.
  indent_starts = set(_indents(tokens))
  for token in tokens:
    if token.type == tokenize.NEWLINE or token.type == tokenize.NL:
      fresh_line = True
      line_start = token.endpos
      if line_start in indent_starts:
        indents += 1
        # Remove from indent_starts so that we can't possibly indent twice for
        # the same marker.
        indent_starts.remove(line_start)
    elif token.type == tokenize.DEDENT or token.type == tokenize.ENDMARKER:
      # This is the end of a block. (We count module scope as a block, too.)
      for string, startpos in incomplete_pragmas[indents]:
        pragma = parsed_file.Pragma.from_text(
            string,
            startpos,
            token.startpos,
        )
        if pragma is not None:
          yield pragma
      del incomplete_pragmas[indents]
      indents -= 1
    elif token.type == tokenize.COMMENT:
      if fresh_line:
        # This pragma applies to the whole block.
        # It probably doesn't really matter whether we pick line_start or
        # token.start, so for consistency we pick line_start.
        incomplete_pragmas[indents].append((token.string, line_start))
      else:
        pragma = parsed_file.Pragma.from_text(
            token.string,
            line_start,
            token.endpos,
        )
        if pragma is not None:
          yield pragma
    else:
      # Any other token means that this line is not just a comment line,
      # and therefore any pragmas are just for this line.
      fresh_line = False


_parsed_ast_cache = weakref.WeakValueDictionary()


def parse_ast(source_code: str, filename: str = '<string>') -> PythonParsedFile:
  """Parses an AST in a way that supports the built-in matchers.

  This includes auxiliary information / post-processing / etc. which are not
  provided by :func:`ast.parse()`.

  Args:
    source_code: Python source code.
    filename: file name (for reporting syntax errors and the like).

  Returns:
    The resulting :class:`PythonParsedFile`

  Raises:
    ParseError: The file failed to parse.
  """
  cache_key = (_CompareById(source_code), filename)
  if cache_key in _parsed_ast_cache:
    return _parsed_ast_cache[cache_key]

  # TODO(b/64560910): Pre/post-process using pasta here.
  # Right now pasta's preprocessing does not preserve byte offsets, and we don't
  # yet have a use for the postprocessing. But, soon!
  try:
    astt = asttokens.ASTTokens(
        source_code,
        tree=_uniqueify_distinct_ast(ast.parse(source_code, filename)))
  except SyntaxError as e:
    raise ParseError('SyntaxError: {}'.format(e))
  except UnicodeDecodeError as e:
    # UnicodeDecodeError is also a ValueError subclass, so we want to catch
    # it specially.
    raise ParseError('UnicodeDecodeError: {}'.format(e))
  parsed = PythonParsedFile(
      text=source_code,
      path=filename,
      pragmas=tuple(sorted(_pragmas(astt.tokens), key=lambda p: p.start)),
      ast_tokens=astt,
      tree=astt.tree,
      nav=AstNav(astt.tree),
  )
  _parsed_ast_cache[cache_key] = parsed
  return parsed


def find_iter(matcher: Matcher,
              parsed: PythonParsedFile) -> Iterator[MatchInfo]:
  """Finds all matches in an AST.

  This is analogous to :func:`re.finditer`. If a node is matched, then any
  sub-nodes are skipped. Otherwise, :func:`find_iter` recurses inside of the
  node to find matches inside of it.

  Args:
    matcher: a :class:`Matcher`.
    parsed: A :class:`PythonParsedFile` as returned by :func:`parse_ast`.

  Yields:
    The successful results of ``matcher.match()`` (:class:`MatchInfo`).
  """
  context = MatchContext(parsed)
  stack = [parsed.tree]
  while stack:
    next_node = stack.pop()
    new_context = context.new()
    try:
      if matcher.type_filter is None or type(next_node) in matcher.type_filter:
        match_info = matcher.match(new_context, next_node)
      else:
        match_info = None
    except MatchError as e:
      print('Matcher failed: {}'.format(e), file=sys.stderr)
      continue
    if match_info is not None:
      context.update_success(new_context)
      yield match_info
      # Don't recurse inside: matches should be non-overlapping.
      continue

    # Recurse down the AST:
    if isinstance(next_node, ast.AST):
      stack.extend(
          reversed(
              [child for unused_field, child in ast.iter_fields(next_node)]))
    elif isinstance(next_node, list):
      stack.extend(reversed(next_node))
