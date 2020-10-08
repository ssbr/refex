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
"""Tests for refex.fix.generate_example."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast

from absl.testing import absltest

from refex.fix import generate_example


class GenerateExampleTest(absltest.TestCase):

  def test_example_source(self):
    """As a smoke test of the smoke test, check that the example parses."""
    ast.parse(generate_example.example_source(), '<string>')


if __name__ == '__main__':
  absltest.main()
