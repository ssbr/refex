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
"""Utilities to load fixers from the built-in database.

Fixers can be found in refex/fix/fixers.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections

from refex.fix import fixer
from refex.fix.fixers import correctness_fixers
from refex.fix.fixers import idiom_fixers
from refex.fix.fixers import modern_python_fixers
from refex.fix.fixers import unittest_fixers

_default_fixers = []
# Using OrderedDict instead of dict so that keeps the fixer order consistent
# across runs for '*', and so we can tune the display order.
_extra_fixers = collections.OrderedDict([('*', _default_fixers)])

def register_default_fixers(fixers):
  """Registers a fixer list to be included in from_pattern('*')."""
  _default_fixers.extend(fixers)

def register_fixers(name, fixers):
  """Registers a fixer list to be returned by from_pattern(name)."""
  if name in _extra_fixers:
    raise ValueError('Name already registered: %r', name)
  _extra_fixers[name] = fixers


def _register_builtins():
  """Registers the built-in set of fixers. Invoked at import-time."""
  register_fixers('correctness', correctness_fixers.SIMPLE_PYTHON_FIXERS)
  register_fixers('idiom', idiom_fixers.SIMPLE_PYTHON_FIXERS)
  register_fixers('modern_python', modern_python_fixers.SIMPLE_PYTHON_FIXERS)
  register_fixers('unittest', unittest_fixers.SIMPLE_PYTHON_FIXERS)

  for fixers in _extra_fixers.values():
    register_default_fixers(fixers)

_register_builtins()


def from_pattern(fixer_pattern):
  """Provide a fixer that combines all the fixers specified in `fixer_pattern`.

  To get all the default fixers, pass '*'. Otherwise, to get a group of fixers
  by name, specify that name. (See _default_fixers & _extra_fixers).

  Args:
    fixer_pattern: The pattern of fixers to load.

  Returns:
    A PythonFixer.

  Raises:
    ValueError: The fixer pattern was not recognized.
  """
  # TODO: Allow you to do set operations like '*,-FixerNameHere', etc.
  # or something along those lines.
  if fixer_pattern in _extra_fixers:
    return fixer.CombiningPythonFixer(_extra_fixers[fixer_pattern])
  else:
    raise ValueError(
        'Unknown fixer pattern %r: must provide one of: %s' %
        (fixer_pattern, ', '.join(_extra_fixers.keys())))
