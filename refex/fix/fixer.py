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
"""Fixers to suggest substitutions for common issues."""


import abc
import string
from typing import Callable, List, Mapping, Optional, Text, TypeVar, Union

import attr
import cached_property

from refex import formatting
from refex import search
from refex.python import matcher
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers


class PythonFixer(metaclass=abc.ABCMeta):
  """Abstract base class for python-specific fixers operating via matchers."""

  # Test helper methods:

  @abc.abstractmethod
  def example_fragment(self):
    """Returns an example fragment that this fixer would match/replace."""

  @abc.abstractmethod
  def example_replacement(self):
    """Returns what replacement is expected for the example fragment."""

  @abc.abstractproperty
  def matcher_with_meta(self):
    """Returns a fully-decorated Matcher which attaches all substitution metadata."""


@attr.s(frozen=True)
class CombiningPythonFixer(search.FileRegexFilteredSearcher,
                           search.BasePythonRewritingSearcher):
  """Combining fixer for ``PythonFixer``, sharing common work.

  This combines all of the matchers (``matcher_with_meta``) into one big
  ``AnyOf``, allowing for optimized traversal.
  """
  fixers = attr.ib(type=List[PythonFixer])
  include_regex = attr.ib(default=r'.*[.]py$', type=str)

  @fixers.validator
  def _fixers_validator(self, attribute, fixers):
    for i, fixer in enumerate(fixers):
      if fixer.matcher_with_meta.type_filter is None:
        raise ValueError(
            f'Overbroad fixer (#{i}) will try to run on EVERY ast node, instead of a small set: {fixer}'
        )

  # Override _matcher definition, as it's now computed based on fixers.
  matcher = attr.ib(init=False, type=matcher.Matcher)

  @matcher.default
  def matcher_default(self):
    return base_matchers.AnyOf(
        *(fixer.matcher_with_meta for fixer in self.fixers))


@attr.s(frozen=True, eq=False)
class SimplePythonFixer(PythonFixer):
  r"""A simple find-replace fixer.

  All fixers must be able to be re-applied repeatedly, so that they can be
  combined with other fixers.

  Attributes:
    matcher: The matcher.
    replacement: The replacement template for the whole match, or a mapping
        from label to replacement template for that label.
    message: The message for all suggestions this gives.
    url: The suggestion URL for more information.
    category: A name to group fixes by.
    example_fragment: An example of a string this would match, for tests etc.
                      If none is provided, one can sometimes be generated
                      automatically in the event that the matcher is a simple
                      syntax_matchers template, by replacing $a -> a etc.
    example_replacement: What the replacement would be for the example
                         fragment. If example_fragment is autogenerated, a
                         corresponding example_replacement is as well.
    significant: Whether the suggestions are going to be significant.
  """
  _matcher = attr.ib(type=matcher.Matcher)
  _replacement = attr.ib(type=Union[formatting.Template,
                                    Mapping[Text, formatting.Template]])
  _message = attr.ib(default=None, type=Optional[str])
  _url = attr.ib(default=None, type=Optional[str])
  _category = attr.ib(default=None, type=str)
  _example_fragment = attr.ib(default=None, type=Optional[str])
  _example_replacement = attr.ib(default=None, type=Optional[str])
  _significant = attr.ib(default=True, type=bool)

  @cached_property.cached_property
  def matcher_with_meta(self):
    if isinstance(self._replacement, formatting.Template):
      replacements = {search.ROOT_LABEL: self._replacement}
    else:
      replacements = self._replacement

    if self._message is not None:
      replacements[search.MESSAGE_LABEL] = formatting.LiteralTemplate(
          self._message)
    if self._url is not None:
      replacements[search.URL_LABEL] = formatting.LiteralTemplate(self._url)
    if self._category is not None:
      replacements[search.CATEGORY_LABEL] = formatting.LiteralTemplate(
          self._category)
    if self._significant:
      replacements[search.SIGNIFICANT_LABEL] = formatting.LiteralTemplate(
          'HACK_TRUE')

    return base_matchers.WithReplacements(
        base_matchers.SystemBind(search.ROOT_LABEL, self._matcher),
        replacements)

  def example_fragment(self):
    if self._example_fragment is not None:
      return self._example_fragment
    if not isinstance(
        self._matcher,
        (syntax_matchers.ExprPattern, syntax_matchers.StmtPattern)):
      return None
    if self._matcher.restrictions:
      return None
    return string.Template(self._matcher.pattern).substitute(
        ImmutableDefaultDict(lambda k: k))

  def example_replacement(self):
    if self._example_fragment is not None:
      return self._example_replacement
    if self._example_replacement is not None:
      raise TypeError(
          'Cannot manually specify a replacement for an autogenerated fragment')
    if not isinstance(self._replacement, formatting.Template):
      raise TypeError(
          'Cannot autogenerate an example replacement unless the replacement'
          ' template applies to the whole match.')
    return string.Template(self._replacement.template).substitute(
        ImmutableDefaultDict(lambda k: k))


KeyType = TypeVar('KeyType')
ValueType = TypeVar('ValueType')


@attr.s(frozen=True)
class ImmutableDefaultDict(Mapping[KeyType, ValueType]):
  """Immutable mapping that returns factory(key) as a value, always."""
  _factory = attr.ib(type=Callable[[KeyType], ValueType])

  def __getitem__(self, key: KeyType) -> ValueType:
    return self._factory(key)

  def __len__(self):
    return 0

  def __iter__(self):
    return iter([])
