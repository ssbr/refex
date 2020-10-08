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
:mod:`refex.parsed_file`
------------------------
"""

# No portable raw unicode literal exists without unicode_literals.
# see https://stackoverflow.com/questions/33027281
from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function
from __future__ import unicode_literals

import re
from typing import Iterable, Mapping, Optional, Text

import asttokens
import attr
import cached_property


@attr.s(frozen=True, eq=True, order=False)
class ParsedFile(object):
  """A wrapper for a file after preprocessing.

  May be subclassed.

  The base class contains common metadata and does not in fact represent the
  result of any parsing. Individual subclasses may contain detailed data about
  the structure of a file. (See, for example,
  :class:`refex.python.matcher.PythonParsedFile`)

  Attributes:
    text: The unparsed file contents.
    path: The path to the file.
    pragmas: The pragmas for this file, in file order.
    line_numbers: A cache for line number <-> codepoint offset conversion.
  """

  text = attr.ib(type=Text)
  path = attr.ib(type=str)
  pragmas = attr.ib(type=Iterable["Pragma"])

  @cached_property.cached_property
  def line_numbers(self):
    return asttokens.LineNumbers(self.text)

# Matches a trailing pragma in a piece of text in an re.search.
_PRAGMA_RE = re.compile(
    r"""
        # Match only at the boundary (like \b) for words-including-dashes.
        # We'd use lookbehind, but this isn't a fixed-width pattern.
        (?:[^-\w]|\A)
        (?P<tag>[-\w]+)\s*
        :
        \s*
        (?P<data>
            [-\w]+\s*=\s*[-\w.]+\s*  # key=value
            (?:,\s* [-\w]+ \s* = \s* [-\w.]+ \s*)*
        )
        (?:,\s*)?  # trailing comma allowed, to try to be maximally permissive.
        \Z
    """, re.VERBOSE)


@attr.s(frozen=True)
class Pragma(object):
  """A pragma / directive for Refex to alter how it handles files.

  Attributes:
    tag: The pragma namespace. This should be ``"refex"`` unless the pragma is
      actually parsed from a comment that targets another system (e.g. pylint.)
    data: The pragma payload, a set of key-value pairs.
    start: The start (codepoint offset) of the pragma in the file. Inclusive.
    end: The end (codepoint offset) of the pragma in the file. Exclusive.
  """
  tag = attr.ib(type=Text)
  data = attr.ib(type=Mapping[Text, Text])
  start = attr.ib(type=int)
  end = attr.ib(type=int)

  @classmethod
  def from_text(cls, text, start, end) -> Optional["Pragma"]:
    """Parses pragmas from the standard format: ``tag: key=value, ...``.

    For example, ``refex: disable=foo`` becomes
    ``Pragma(tag=refex, data={"disable": "foo"}, ...)``

    The pragma must end the string, although arbitrary leading text (usually an
    explanation for why the pragma was used) is allowed.

    Args:
      text: The candidate pragma text.
      start: The start offset for the pragma.
      end: The end offset for the pragma.

    Returns:
      A :class:`Pragma` if text[start:end] parses as a pragma, otherwise
      ``None``.
    """
    m = _PRAGMA_RE.search(text)
    if m is None:
      return None
    data = {}
    for declaration in m.group('data').split(','):
      key, _, value = declaration.partition('=')
      data[key.strip()] = value.strip()
    return cls(tag=m.group('tag'), data=data, start=start, end=end)
