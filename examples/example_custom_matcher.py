# Copyright 2021 Google LLC
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
"""A matcher which matches an AST for a sum expression, and the sum itself.

For example, replacing SumMatcher() with "$sum" will replace
``1 + 2 + 3`` with ``6``.
"""

import ast

import attr

from refex.python import matcher
from refex.python.matchers import base_matchers
from refex import search
from refex import match


@attr.s(frozen=True)
class SumMatcher(matcher.Matcher):
  bind_variables = frozenset({"sum"})

  def _match(self, context, candidate):
    if not isinstance(candidate, ast.AST):
      return None

    # Walk the AST to collect the answer:
    values = []
    for node in ast.walk(candidate):
      # Every node must either be a Constant/Num or an addition node.
      if isinstance(node, ast.Constant):
        values.append(node.value)
      elif isinstance(node, ast.Num):  # older pythons
        values.append(node.n)
      elif isinstance(node, ast.BinOp) or isinstance(node, ast.Add):
        # Binary operator nodes are allowed, but only if they have an Add() op.
        pass
      else:
        return None  # not a +, not a constant

      # For more complex tasks, or for tasks which integrate into how Refex
      # builds results and bindings, it can be helpful to defer work into a
      # submatcher, such as by running BinOp(op=Add()).match(context, candidate)

    # Having walked the AST, we have determined that the whole tree is addition
    # of constants, and have collected all of those constants in a list.
    if len(values) <= 1:
      # Don't bother emitting a replacement for e.g. 7 with itself.
      return None
    result = str(sum(values))

    # Finally, we want to return the answer to Refex:
    # 1) bind the result to a variable
    # 2) return the tree itself as the matched value

    # We can do this by deferring to a matcher that does the right thing.
    # StringMatch() will produce a string literal match, and AllOf will retarget
    # the returned binding to the AST node which was passed in.
    submatcher = base_matchers.AllOf(
        base_matchers.Bind("sum", base_matchers.StringMatch(result)))
    return submatcher.match(context, candidate)
