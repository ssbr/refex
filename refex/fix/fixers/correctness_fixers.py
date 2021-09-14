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
"""Fixers for correctness issues.

* Identity checks against literals are always a bug, and should be replaced by
  equality checks. This is a behavior change -- tests may stop passing after the
  fix is applied -- but the new behavior will be correct, and that's what
  matters.
* ``yaml.load()`` includes security traps.
"""

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

# Python 2 compatibility hack to be able to get b'...' and '...'.
if six.PY2:
  _STRING_LITERAL = ast_matchers.Str()
else:
  _STRING_LITERAL = base_matchers.AnyOf(ast_matchers.Str(),
                                        ast_matchers.Bytes())

# A "literal" for the purposes of buggy is/is not checks.
_LITERAL = base_matchers.AnyOf(ast_matchers.Num(), _STRING_LITERAL)

_YAML_MESSAGE = (
    'yaml.{function} can execute arbitrary Python code contained in the input. '
    'Use yaml.safe_load instead. This may require changing dumps to use '
    'yaml.safe_dump.')


def _attrib_mutable_default_fixer(default, keyword_replacement):
  """Replaces an attr.ib(default=<default>) call where the default is mutable.

  For example, this will replace 'default=[]' with 'default=()' in an attr.ib():

      _attrib_factory_fixer('[]', 'default=()')

  However, most of the time, it should be replaced with factory=... to get as
  close to the original semantics as possible, while fixing the bug. (In
  particular, the user may want to mutate the object.)

  Args:
    default: The literal text of the default to match (e.g. '[]').
    keyword_replacement: A replacement string. Note that it isn't a template.
      (It is not a full Python expression/statement, and so safe substitution is
      hard to guarantee.)

  Returns:
    A SimplePythonFixer for this fix.
  """

  return fixer.SimplePythonFixer(
      message=(
          'The default in an attr.ib() call is shared across all instances.'
          ' Mutable defaults should instead use factory=..., to get a unique'
          ' value.'),
      matcher=ast_matchers.Call(
          func=syntax_matchers.ExprPattern('attr.ib'),
          keywords=base_matchers.Contains(
              base_matchers.Bind(
                  'keyword',
                  ast_matchers.keyword(
                      arg=base_matchers.Equals('default'),
                      value=syntax_matchers.ExprPattern(default))))),
      replacement={'keyword': formatting.ShTemplate(keyword_replacement)},
      url='https://refex.readthedocs.io/en/latest/guide/fixers/attrib_default.html',
      category='refex.correctness.attrib-default',
      example_fragment='attr.ib(default=%s)' % default,
      example_replacement='attr.ib(%s)' % keyword_replacement,
  )


SIMPLE_PYTHON_FIXERS = [
    # is/== literal
    fixer.SimplePythonFixer(
        message=('`is` only sometimes works for comparing equality with'
                 ' literals.  This is a bug that will manifest in subtle ways.'
                 ' == is more appropriate.'),
        matcher=syntax_matchers.ExprPattern('$lhs is $rhs', {'rhs': _LITERAL}),
        replacement=syntactic_template.PythonExprTemplate('$lhs == $rhs'),
        url='https://refex.readthedocs.io/en/latest/guide/fixers/literal_comparison.html',
        category='pylint.literal-comparison',
        example_fragment='lhs is 42',
        example_replacement='lhs == 42',
    ),
    fixer.SimplePythonFixer(
        message=('`is not` only sometimes works for comparing inequality with'
                 ' literals. This is a bug that will manifest in subtle ways.'
                 ' != is more appropriate.'),
        matcher=syntax_matchers.ExprPattern('$lhs is not $rhs',
                                            {'rhs': _LITERAL}),
        replacement=syntactic_template.PythonExprTemplate('$lhs != $rhs'),
        url='https://refex.readthedocs.io/en/latest/guide/fixers/literal_comparison.html',
        category='pylint.literal-comparison',
        example_fragment='lhs is not 42',
        example_replacement='lhs != 42',
    ),
    # YAML load/safe_load
    fixer.SimplePythonFixer(
        message=_YAML_MESSAGE.format(function='load'),
        matcher=syntax_matchers.WithTopLevelImport(
            syntax_matchers.ExprPattern('yaml.load($s)'), 'yaml'),
        replacement=syntactic_template.PythonExprTemplate('yaml.safe_load($s)'),
        url='https://msg.pyyaml.org/load',
        category='refex.security.yaml_safe_load',

        # test / documentation data
        example_fragment='import yaml; yaml.load(x)',
        example_replacement='import yaml; yaml.safe_load(x)',
    ),
    fixer.SimplePythonFixer(
        message=_YAML_MESSAGE.format(function='load_all'),
        matcher=syntax_matchers.WithTopLevelImport(
            syntax_matchers.ExprPattern('yaml.load_all($s)'), 'yaml'),
        replacement=syntactic_template.PythonExprTemplate(
            'yaml.safe_load_all($s)'),
        url='https://msg.pyyaml.org/load',
        category='refex.security.yaml_safe_load',

        # test / documentation data
        example_fragment='import yaml; yaml.load_all(x)',
        example_replacement='import yaml; yaml.safe_load_all(x)',
    ),
    fixer.SimplePythonFixer(
        message='Parentheses around a single variable have no effect. Did you mean to format with a tuple?',
        matcher=base_matchers.AllOf(
            # For a line like 'a % (b)', asttokens won't include the parens
            # around b in its token span. So to find something like that, we
            # look for a '%' BinOp where the left side is a literal string, the
            # right side of the BinOp is a name and the entire op ends with a
            # paren but doesn't start with one.  Since the name itself cannot
            # include a ')', the only place the close-paren could come from is
            # if the name were surrounded in superfluous parens. It is possible
            # that $b is wrapped in parens as a hint to pyformat to break the
            # line, but we anyway skip any case where $b extends over multiple
            # lines because the `MatchesRegex` doesn't use re.DOTALL
            # There's still a chance $b is a variable holding a tuple that's
            # wrapped in parens, but that should be very rare. (And even if it
            # occurs, although the suggested fix would be wrong, we're still
            # pointing out an un-idiomatic pattern).
            syntax_matchers.ExprPattern(
                '$a % $b',
                dict(
                    a=_STRING_LITERAL,
                    b=base_matchers.AllOf(
                        base_matchers.AnyOf(ast_matchers.Attribute(),
                                            ast_matchers.Name())))),
            base_matchers.MatchesRegex(r'[^(].+\)'),
        ),
        replacement=syntactic_template.PythonExprTemplate('$a % ($b,)'),
        url='https://refex.readthedocs.io/en/latest/guide/fixers/superfluous_parens.html',
        category='refex.correctness.formatting',
        # test / documentation data
        example_fragment='x = "hello %s" % (world)',
        example_replacement='x = "hello %s" % (world,)',
    ),
    # attr.ib mutable defaults
    # TODO: It Would Be Nice to handle non-empty lists/etc. and replace
    # with a factory=lambda: <...>, but those are uncommon and the replacement
    # logic is a little tricky.
    # Similarly, we could handle the many other cases like time.time() or flags,
    # but they are also rare.
    _attrib_mutable_default_fixer(
        default='[]', keyword_replacement='factory=list'),
    _attrib_mutable_default_fixer(
        default='{}', keyword_replacement='factory=dict'),
    _attrib_mutable_default_fixer(
        default='set()', keyword_replacement='factory=set'),
]
