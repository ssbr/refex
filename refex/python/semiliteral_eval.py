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
"""Evaluates simple literal data and limited function calls.

This provides an Eval() function that's similar in concept to ast.literal_eval.
Like ast.literal_eval, it can parse its input of literal data such as string,
numbers, lists, etc.  Unlike ast.literal_eval, Eval also permits the use of
function calls, as long as the callable is present in the provided dict.

This is intended to replace uses of the standard library's eval() in places
where it is too powerful for the intended use case.
"""
# NOTE: this file is a vendored copy of semiliteral_eval from Google's internal
# source code.
# TODO: open-source semiliteral_eval properly, and delete this copy.
import ast


def _HasStarArgs(node):
  """Returns True if the callable node has *args or **kwargs."""
  try:
    # Python 2.
    return node.starargs or node.kwargs
  except AttributeError:
    # Python 3.
    return (any(isinstance(arg, ast.Starred) for arg in node.args) or
            any(kw.arg is None for kw in node.keywords))


def Eval(s, callables=None, constants=None):
  """Evaluates Python strings with literals and provided callables/constants.

  Like ast.literal_eval, this parses its input of literal data for strings,
  bytes, numbers, lists, tuples, dictionaries, the constant names True, False,
  and None.  It also supports set literals.

  Most importantly, this supports a dict of safe callables.  A callable is
  restricted to be a dotted name in s, and only present in callable position.
  Its value must be bound in the 'callables' dictionary.

  Args:
    s: a string
    callables: an optional dictionary mapping a dotted name to a function.  For
        example, the dictionary {'set': set} will allow the evaluator to call
          the 'set' function where it occurs in s.  If you use this, we
          recommend you explicitly pass it as a keyword argument for readability
          and to avoid confusion with 'constants'.  If not provided, defaults to
          {}.
    constants: an optional dictionary mapping names to constant values.  If you
      use this, we recommend you explicitly pass it as a keyword argument for
      readability and to avoid confusion with 'callables'.
        If not provided, defaults to:
        {'None': None, 'True': True, 'False': False}

  Returns:
    The evaluation of s.

  Raises:
    SyntaxError: Occurs if s does not look like valid Python literal syntax or
        if it refers to an unknown constant or callable.
  """
  if callables is None:
    callables = {}
  if constants is None:
    constants = {'None': None, 'True': True, 'False': False}
  assert isinstance(callables, dict)
  assert isinstance(constants, dict)

  node = ast.parse(s, mode='eval')
  if isinstance(node, ast.Expression):
    node = node.body

  ast_bytes = ast.Bytes if hasattr(ast, 'Bytes') else ast.Str

  def _Convert(node):
    """Convert the literal data in the node."""
    if isinstance(node, (ast.Str, ast_bytes)):
      return node.s
    if isinstance(node, ast.Num):
      return node.n
    if isinstance(node, ast.UnaryOp):
      if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Num):
        return 0 - _Convert(node.operand)
    if isinstance(node, ast.Tuple):
      return tuple([_Convert(elt) for elt in node.elts])
    if isinstance(node, ast.List):
      return [_Convert(elt) for elt in node.elts]
    if isinstance(node, ast.Dict):
      return {_Convert(k): _Convert(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Set):
      return {_Convert(elt) for elt in node.elts}
    # The following case supports calls to callable functions, supporting
    # positional and named arguments, but not *args or **kwargs:
    if isinstance(node, ast.Call) and not _HasStarArgs(node):
      callable_name = _GetDottedName(node.func)
      if callable_name is None:
        raise SyntaxError('malformed string: %r' % s)
      if callable_name not in callables:
        raise SyntaxError('unknown callable: %r' % callable_name)
      return callables[callable_name](
          *[_Convert(arg) for arg in node.args],
          **{kw.arg: _Convert(kw.value)
             for kw in node.keywords})
    # Try and see if it's a dotted-name constant.
    name = _GetDottedName(node)
    if name is not None:
      if name in constants:
        return constants[name]
      raise SyntaxError('unknown constant: %s' % name)

    raise SyntaxError('malformed string: %r' % s)

  def _GetDottedName(node):
    """Get the dotted name in the node."""
    if isinstance(node, ast.Name):
      return node.id
    if hasattr(ast, 'NameConstant') and isinstance(node, ast.NameConstant):
      # True/False/None on Python 3.
      return str(node.value)
    if isinstance(node, ast.Attribute):
      lhs = _GetDottedName(node.value)
      return lhs + '.' + node.attr
    return None

  return _Convert(node)
