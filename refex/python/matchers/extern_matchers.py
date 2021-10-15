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
# pyformat: disable
"""
:mod:`~refex.python.matchers.extern_matchers`
---------------------------------------------

Matchers for integrating with external tooling.

.. autoclass:: RewriteFile
.. autoclass:: ExternalCommand
"""
# pyformat: enable

import abc
import subprocess
from typing import Union, Sequence, Optional

import attr

from refex.python import matcher


@attr.s(frozen=True)
class RewriteFile(matcher.Matcher):
  """Base class for whole-file rewrites."""
  _metavariable_prefix = attr.ib(type=str)

  def _match(self, context, candidate):
    rewritten = self.rewrite(context, candidate)
    if rewritten is None:
      return None
    else:
      return matcher.MatchInfo.from_diff(
          self._metavariable_prefix,
          context.parsed_file.text,
          rewritten,
          match=matcher.create_match(context.parsed_file, candidate))

  type_filter = None

  @abc.abstractmethod
  def rewrite(self, context: matcher.PythonParsedFile,
              candidate) -> Optional[str]:
    pass


@attr.s(frozen=True)
class ExternalCommand(RewriteFile):
  """Runs an external command to modify a file."""

  #: The command to run, which takes the input as stdin, and returns the
  #: replacement by printing to stdout.
  _command = attr.ib(type=Union[str, Sequence[str]])

  #: Whether to run via the shell. Unsafe.
  _shell = attr.ib(type=bool, default=False)

  def rewrite(self, context, candidate):
    out = subprocess.run(
        self._command,
        check=True,
        stdout=subprocess.PIPE,
        input=context.parsed_file.text,
        encoding='utf-8',
        shell=self._shell,
    )
    return out.stdout
