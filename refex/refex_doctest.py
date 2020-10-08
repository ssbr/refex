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

# python2 python3
"""Run doctests for all of refex's libraries."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys

from absl.testing import absltest

import refex.python.matcher_test_util  # so that it's found by _submodules: pylint: disable=unused-import
import refex.search

# isort: split
# We put doctest after absltest so that it picks up the unittest monkeypatch.
# Otherwise doctest tests aren't runnable at all with Bazel.

import doctest


def _submodules(package_module):
  """Gets submodules in a package.

  Args:
    package_module: The package itself.

  Yields:
    module objects for all modules in the package, including the root.
  """
  package_prefix = package_module.__name__ + '.'
  yield package_module
  for name, mod in sys.modules.items():
    if name.startswith(package_prefix):
      yield mod


_REFEX_SUBMODULES = frozenset(_submodules(refex))


class SubmodulesTest(absltest.TestCase):

  def test_submodules(self):
    """_submodules should find some submodules."""
    self.assertIn(refex, _REFEX_SUBMODULES)
    self.assertIn(refex.search, _REFEX_SUBMODULES)


def load_tests(loader, tests, ignore):
  del loader, ignore  # unused
  suite = absltest.unittest.TestSuite(tests)
  for module in _REFEX_SUBMODULES:
    if getattr(module, 'DOCTEST_RUN', True):
      suite.addTest(
          doctest.DocTestSuite(
              module,
              test_finder=doctest.DocTestFinder(exclude_empty=False),
              optionflags=(doctest.ELLIPSIS | doctest.DONT_ACCEPT_TRUE_FOR_1)))
  return suite


if __name__ == '__main__':
  absltest.main()
