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
r"""Text-only string.Template wrapper for 2/3 straddling code.

In Python 2, string.Template is bytes-only. In Python 3, it is text-only. This
presents a migration hazard.

One way out: string.Template "technically" works for unicode in the basic case:

    $ python2
    >>> import string
    >>> string.Template(u'$x').substitute({u'x': u'\uffef'})
    u'\uffef'

But there are hairy edge cases:

    >>> class A(object):
    ...   def __unicode__(self): return u'unicode'
    ...   def __str__(self): return b'bytes'
    ...
    >>> string.Template(u'$x').substitute({u'x': A()})
    u'bytes'

In addition, pytype and mypy will claim that Python 2 string.Template doesn't
support unicode at _all_, resulting in errors at build time.

future_string.Template wraps string.Template in a way that eliminates the hairy
edge cases, and satisfies the type checkers:

    >>> from refex import future_string
    >>> future_string.Template(u'$x').substitute({u'x': A()})
    u'unicode'
"""
from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

import collections
import string
from typing import Any, Mapping, Text

import six

# For refex_doctest.py
# The examples are specific to Python 2.
DOCTEST_RUN = six.PY2


class Template(string.Template):
  """A text-only string.Template subclass.

  This doesn't support the full API of string.Template, but enough to get by.
  (In particular, the substitute methods don't accept **kwargs.)
  """

  def __init__(self, template: Text):
    super(Template, self).__init__(template)
    self.template = template  # override the type of .template.

  def substitute(self, variables: Mapping[Text, Any]) -> Text:
    return super(Template, self).substitute(_LazyTextDict(variables))

  def safe_substitute(self, variables: Mapping[Text, Any]) -> Text:
    return super(Template, self).safe_substitute(_LazyTextDict(variables))


class _LazyTextDict(collections.Mapping):
  """A dict wrapper which converts values to text when items are accessed."""

  def __init__(self, d: Mapping[Text, Any]):
    self._d = d

  def __getitem__(self, key: Text) -> Text:
    return six.text_type(self._d[key])

  def __len__(self):
    return len(self._d)

  def __iter__(self):
    return iter(self._d)
