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
"""Fixers for Python 3 portability issues."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals  # for convenience

import six

from refex import formatting
from refex.fix import fixer
from refex.python import syntactic_template
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers

SIMPLE_PYTHON_FIXERS = []  # Disabled except when running in Python 2.


def with_six(m):
  return syntax_matchers.WithTopLevelImport(m, 'six')


_HAS_KEY_FIXER = fixer.SimplePythonFixer(
    message='dict.has_key() was removed in Python 3.',
    matcher=syntax_matchers.ExprPattern('$a.has_key($b)'),
    replacement=syntactic_template.PythonExprTemplate('$b in $a'),
    url='https://docs.python.org/3.1/whatsnew/3.0.html#builtins',
    significant=True,
    category='refex.modernize.dict_has_key',
)


def _dict_iter_fixer(method_name):
  return fixer.SimplePythonFixer(
      message=('dict.{method} is deprecated and does not exist in Python 3. '
               'Instead, import six and use six.{method}').format(
                   method=method_name),
      matcher=with_six(
          syntax_matchers.ExprPattern(
              '$x.{}()'.format(method_name),
              {'x': base_matchers.Unless(syntax_matchers.ExprPattern('six'))
              }),),
      replacement=syntactic_template.PythonExprTemplate(
          'six.{}($x)'.format(method_name)),
      url='https://www.python.org/doc/sunset-python-2/',
      category='pylint.dict-iter-method',
      # Must define manually due to the extra restrictions on the pattern.
      example_fragment='import six; x.{}()'.format(method_name),
      example_replacement='import six; six.{}(x)'.format(method_name),
  )


if six.PY2:
  SIMPLE_PYTHON_FIXERS.extend([
      _HAS_KEY_FIXER,
      fixer.SimplePythonFixer(
          message=('long literals are deprecated and will not work in Python 3.'
                   ' Regular int literals without the L suffix will generally'
                   ' work just as well.'),
          matcher=base_matchers.MatchesRegex(r'(?P<num>.+)[lL]',
                                             ast_matchers.Num()),
          replacement=formatting.ShTemplate('$num'),
          url='https://www.python.org/doc/sunset-python-2/',
          category='pylint.long-suffix',
          example_fragment='42L',
          example_replacement='42',
      ),
      fixer.SimplePythonFixer(
          message=('Octal integer literals using 0NNN (with a leading 0) are'
                   ' deprecated and will not work in Python 3. Instead, use the'
                   ' 0oNNN syntax.'),
          # Have to be very careful here -- while 04 will not parse in Python 3,
          # expressions like 04.0 are valid in both 2 and 3 and not octal.
          matcher=base_matchers.MatchesRegex(r'(?P<prefix>[-+]?)0(?P<num>\d+)',
                                             ast_matchers.Num()),
          replacement=formatting.ShTemplate('${prefix}0o${num}'),
          url='https://www.python.org/doc/sunset-python-2/',
          category='pylint.old-octal-literal',
          example_fragment='042',
          example_replacement='0o42',
      ),
      fixer.SimplePythonFixer(
          message=('basestring is deprecated and does not exist in Python 3. '
                   'Instead, use six.text_type'),
          matcher=with_six(syntax_matchers.ExprPattern('basestring')),
          replacement=syntactic_template.PythonExprTemplate('six.string_types'),
          url='https://www.python.org/doc/sunset-python-2/',
          category='pylint.basestring-builtin',
          example_fragment='import six; isinstance(x, basestring)',
          example_replacement='import six; isinstance(x, six.string_types)',
      ),
      # TODO(b/117675566): implement classic integer division fixer.
      _dict_iter_fixer('iterkeys'),
      _dict_iter_fixer('itervalues'),
      _dict_iter_fixer('iteritems'),
  ])
