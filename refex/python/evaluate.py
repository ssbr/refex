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


import textwrap

from refex.python import error_strings
from refex.python import matcher
from refex.python import semiliteral_eval
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from refex.python.matchers import lexical_matchers
from refex.python.matchers import syntax_matchers


def _sorted_attributes(o):
  """Gets all attributes in sorted order. A replacement for vars(o).items()."""
  for a in sorted(dir(o)):
    yield a, getattr(o, a)


# TODO: remove overwrite param


def add_module(module, overwrite=False):
  """Adds a non-builtin matcher module to be available for compile_matcher."""
  for global_variable, value in _sorted_attributes(module):
    if not isinstance(value, type):
      continue
    if not matcher.is_safe_to_eval(value):
      continue

    is_mutated = False
    module_name = module.__name__.rsplit('.', 1)[-1]
    for name in global_variable, f'{module_name}.{global_variable}':
      if overwrite or name not in _ALL_MATCHERS:
        _ALL_MATCHERS[name] = value
        is_mutated = True
    if not is_mutated:
      raise ValueError(f'Could not add matcher: f{value!r}')


_ALL_MATCHERS = {}
add_module(ast_matchers, overwrite=True)
add_module(base_matchers, overwrite=True)
add_module(lexical_matchers, overwrite=True)
add_module(syntax_matchers, overwrite=True)


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
