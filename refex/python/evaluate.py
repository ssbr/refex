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
:mod:`refex.python.evaluate`
============================

Build matchers from user-provided input.

For example, a user might give ``'base_matchers.Anything()'`` and this is
compiled to an actual ``base_matchers.Anything()``.

For convenience, these are also available without the module name (e.g. as
``Anything()``), but without any defined behavior if there is more than one
matcher with the same name.
"""

from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

import textwrap

from refex.python import error_strings
from refex.python import matcher
from refex.python import matchers
from refex.python import semiliteral_eval
# Actually collect all the matchers into the matchers module, so they can be
# enumerated.
import refex.python.matchers.ast_matchers  # pylint: disable=unused-import
import refex.python.matchers.base_matchers  # pylint: disable=unused-import
import refex.python.matchers.lexical_matchers  # pylint: disable=unused-import
import refex.python.matchers.syntax_matchers  # pylint: disable=unused-import


def _sorted_attributes(o):
  """Gets all attributes in sorted order. A replacement for vars(o).items()."""
  for a in sorted(dir(o)):
    yield a, getattr(o, a)


def _get_matcher_map():
  """Get the mapping from dotted-names to matcher constructors/callables."""
  mapping = {}
  for module_name, module in _sorted_attributes(matchers):
    for global_variable, value in _sorted_attributes(module):
      if not isinstance(value, type):
        continue
      if not matcher.is_safe_to_eval(value):
        continue
      mapping[global_variable] = value
      mapping['%s.%s' % (module_name, global_variable)] = value
  return mapping


_ALL_MATCHERS = _get_matcher_map()


def compile_matcher(user_input:str) -> matcher.Matcher:
  """Creates a :class:`~refex.python.matcher.Matcher` from a string."""
  user_input = textwrap.dedent(user_input).strip('\n')
  try:
    return semiliteral_eval.Eval(
        user_input,
        callables=_ALL_MATCHERS,
        constants=matcher.registered_constants)
  except SyntaxError as e:
    raise ValueError(error_strings.user_syntax_error(e, user_input))
