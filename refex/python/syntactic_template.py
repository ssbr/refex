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
:mod:`refex.python.syntactic_template`
--------------------------------------

Syntax-aware Python substitution templates, as described in
:doc:`/guide/patterns_templates`.

The core problem with lexical or textual substitution of Python code, as with
e.g. :class:`refex.formatting.ShTemplate`, is that the substitution can be
unintentionally wrong. For example:

If you replace ``f($x)`` with ``$x``, what if ``$x`` contains a newline?

If you replace ``$a`` with ``$a * 2``, what if ``$a`` is ``1 + 2``?

The template classes here aim to make replacements that match the intended
syntax -- i.e. the structure of the template -- and will parenthesize as
necessary.

.. autoclass:: PythonExprTemplate
.. autoclass:: PythonStmtTemplate

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import tokenize
from typing import Text

from absl import logging
import attr
import cached_property
import six

from refex import formatting
from refex.python import matcher
from refex.python import python_pattern
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers


@attr.s(frozen=True)
class _LexicalTemplate(object):
  """Lexically-aware Python templates.

  $variables are only used for replacements if they occur inside Python, not
  inside of e.g. a string literal or a comment. So "a = $x" has an x variable
  in the template, but "a = '$x'" does not.
  """

  template = attr.ib()
  _tokens = attr.ib(init=False, repr=False)
  _var_to_i = attr.ib(init=False, repr=False)
  variables = attr.ib(init=False, repr=False)

  def __attrs_post_init__(self):
    # Because we have frozen=True, creating values for _tokens and _var_to_i
    # is a little complex, and requires invoking object.__setattr__.
    tokenized, metavar_indices = python_pattern.token_pattern(self.template)
    var_to_i = {}
    for i in metavar_indices:
      var = tokenized[i][1]
      var_to_i.setdefault(var, []).append(i)
    object.__setattr__(self, '_tokens', tokenized)
    object.__setattr__(self, '_var_to_i', var_to_i)
    object.__setattr__(self, 'variables', six.viewkeys(var_to_i))

  def substitute(self, replacements):
    """Lexically-aware substitution.

    Args:
      replacements: A map from metavariable name to new content.

    Returns:
      Substituted Python code.

    Raises:
      KeyError: A variable in the template was not specified in the
          replacements. THis is to be compatible with strings.Template.
    """
    if not self.template:
      # Work around: if u'' is untokenized and then retokenized,
      # it comes back out as b'' on Python 2!
      return self.template
    # Take a copy of tokens to modify the target slots.
    tokens = list(self._tokens)
    free_vars = set(self._var_to_i)
    logging.debug('Applying %r to tokens %r for substitution of %r', free_vars,
                  tokens, replacements)
    for var, new in six.iteritems(replacements):
      try:
        all_i = self._var_to_i[var]
      except KeyError:
        # overspecified: a replacement for a variable not in the template.
        continue
      free_vars.remove(var)
      for i in all_i:
        tok = list(tokens[i])
        tok[1] = new
        tokens[i] = tuple(tok)
    if free_vars:
      raise KeyError(next(iter(free_vars)))
    return tokenize.untokenize(tokens)


@attr.s(frozen=True)
class _BasePythonTemplate(formatting.Template):
  """Base class for syntax-aware templates.

  The templates use ShTemplate/string.Template style templates. e.g. "$x + $y".

  Subclasses must override _pattern_factory to provide a matcher for the
  template.

  Attributes:
    template: The source template
  """
  template = attr.ib(type=Text)
  _lexical_template = attr.ib(repr=False, init=False)  # type: _LexicalTemplate
  _ast_matcher = attr.ib(repr=False, init=False)  # type: matcher.Matcher

  def __attrs_post_init__(self):
    if not isinstance(self.template, six.text_type):
      raise TypeError('Expected text, got: {}'.format(
          type(self.template).__name__))

  @_lexical_template.default
  def _lexical_template_default(self):
    return _LexicalTemplate(self.template)

  @_ast_matcher.default
  def _ast_matcher_default(self):
    return self._pattern_factory(self.template)

  def substitute_match(self, parsed, match, matches):
    """Syntax-aware substitution, parsing the template using _pattern_factory.

    Args:
      parsed: The ParsedFile being substituted into.
      match: The match being replaced.
      matches: The matches used for formatting.

    Returns:
      Substituted Python code.
    """
    replacement, _ = self._parenthesized(
        _matchers_for_matches(matches),
        formatting.stringify_matches(matches),
    )
    if not isinstance(parsed, matcher.PythonParsedFile):
      # This file is not (known to be) a Python file, so we can't (efficiently)
      # check the replacement into the parent AST node.
      # TODO: It would help if we could automatically obtain a
      # PythonParsedFile for any given ParsedFile. This also lets us compose
      # arbitrary searchers together, some of which take a PythonParsedFile, and
      # others which don't.
      return replacement

    # replacement is now a safely-interpolated string: all of the substitutions
    # are parenthesized where needed. The only thing left is to ensure that when
    # replacement itself is substituted in, it itself is parenthesized
    # correctly.
    #
    # To do this, we essentially repeat the same safe substitution algorithm,
    # except using the context of the replacement as a fake pattern.
    #
    # Note that this whole process is only valid if we are matching an actual
    # AST node, and an expr node at that.
    # For example, it is _not_ valid to replace b'foo' with b('foo'), or 'foo'
    # with 'f(o)o'.

    if not isinstance(match, matcher.LexicalASTMatch):
      # The match wasn't even for an AST node. We'll assume they know what
      # they're doing and pass thru verbatim. Non-AST matches can't be
      # automatically parenthesized -- for example, b'foo' vs b('foo')
      return replacement

    if not isinstance(match.matched, ast.expr):
      # Only expressions need to be parenthesized, so this is fine as-is.
      return replacement

    parent = parsed.nav.get_parent(match.matched)

    if isinstance(parent, ast.Expr):
      # the matched object is already a top-level expression, and will never
      # need extra parentheses.
      # We are assuming here that the template does not contain comments,
      # which is not enforced. We also assume that it doesn't contain raw
      # newlines, but this is enforced by the template and substitution both
      # needing to parse on their own.
      return replacement

    if isinstance(parent, ast.stmt) and hasattr(parent, 'body'):
      # TODO(b/139758169): re-enable reparsing of statements in templating.
      # Multi-line statements can't be reparsed due to issues with
      # indentation. We can usually safely assume that it doesn't need parens,
      # although exceptions exist. (Including, in an ironic twist, "except".)
      return replacement

    # keep navigating up until we reach a lexical AST node.
    # e.g. skip over lists.
    while True:
      parent_span = matcher.create_match(parsed, parent).span
      if parent_span is not None and isinstance(parent, (ast.expr, ast.stmt)):
        # We need a parent node which has a known source span,
        # and which is by itself parseable (i.e. is an expr or stmt).
        break
      next_parent = parsed.nav.get_parent(parent)
      if isinstance(next_parent, ast.stmt) and hasattr(next_parent, 'body'):
        # TODO(b/139758169): re-enable reparsing of statements in templating.
        # We encountered no reparseable parents between here and a
        # non-reparseable statement, so, as before, we must fall back to
        # returning the replacement verbatim and hoping it isn't broken.
        # (For example, replacing T with T1, T2 in "class A(T)" is incorrect.)
        return replacement
      parent = next_parent
    else:
      raise formatting.RewriteError(
          "Bug in Python formatter? Couldn't find parent of %r" % match)

    # Re-apply the safe substitution, but on the parent.
    context_start, context_end = parent_span
    match_start, match_end = match.span
    prefix = parsed.text[context_start:match_start]
    suffix = parsed.text[match_end:context_end]
    if isinstance(parent, ast.expr):
      # expressions can occur in a multiline context, but now that we've
      # removed it from its context for reparsing, we're in a single-line
      # unparenthesized context. We need to add parens to make sure this
      # parses correctly.
      prefix = '(' + prefix
      suffix += ')'
    parent_pseudotemplate = PythonTemplate(prefix + u'$current_expr' + suffix)
    parsed_replacement = ast.parse(replacement)
    if len(parsed_replacement.body) != 1 or not isinstance(
        parsed_replacement.body[0], ast.Expr):
      raise formatting.RewriteError(
          "Non-expression template can't be used in expression context: %s" %
          self.template)

    current_matcher = syntax_matchers.ast_matchers_matcher(
        parsed_replacement.body[0].value)
    _, safe_mapping = parent_pseudotemplate._parenthesized(  # pylint: disable=protected-access
        {u'current_expr': current_matcher}, {u'current_expr': replacement})
    return safe_mapping[u'current_expr']

  def _parenthesized(self, matchers, stringified_matches):
    """Parenthesizes a substitution for a template.

    Args:
      matchers: Dict mapping {var: Matcher that must match this variable}
      stringified_matches: Dict mapping variable -> string for match.

    Returns:
      A tuple of two elements:
        0: The full safely parenthesized substitution.
        1: A dict dict mapping var -> parenthesized string, for each match.
    """
    safe_mapping = {}
    unparenthesized_mapping = {}
    for k, v in stringified_matches.items():
      raw_string = stringified_matches[k]
      if k in matchers:
        safe_mapping[k] = '(%s)' % raw_string
        unparenthesized_mapping[k] = raw_string
      else:
        # Non-expressions cannot be parenthesized and must be inserted verbatim.
        safe_mapping[k] = raw_string

    # We start parenthesized and try dropping parentheses to see if things
    # still match the same way.
    # First, build up the canonical replacement:
    replacement = self._lexical_template.substitute(safe_mapping)

    # Now let's parse the produced canonical replacement and make sure that it
    # looks "correct" -- it is structurally the same as our template is,
    # and the substituted in values are identical.
    try:
      parsed_template = matcher.parse_ast(replacement,
                                          '<_BasePythonTemplate pattern>')
    except matcher.ParseError as e:
      raise formatting.RewriteError(
          'Bug in Python formatter? Failed to parse formatted Python string as '
          'Python: template=%r, substitute(matches for %r) -> %r: %s' %
          (self.template, stringified_matches, replacement, e))

    m = self._ast_matcher.match(
        matcher.MatchContext(parsed_template), parsed_template.tree)
    if m is None:
      raise formatting.RewriteError(
          'Bug in Python formatter? Even "safe" formatting of Python template '
          'produced an incorrect and different AST, so it must be discarded: '
          ' template=%r, substitute(matches for %r) -> %r' %
          (self.template, stringified_matches, replacement ))

    for k, bound in m.bindings.items():
      v = bound.value
      if not matchers[k].match(
          matcher.MatchContext(parsed_template), v.matched):
        raise formatting.RewriteError(
            'Bug in Python formatter? Even "safe" formatting of Python template'
            ' produced an incorrect and different AST, so it must be discarded '
            '[variable %s=%r was corrupted -- %r]: '
            'template=%r, substitute(matches for %r) -> %r' %
            (k, matchers[k], v, self.template, stringified_matches,
             replacement))

    # The preliminaries are done: safe templating worked, and all that's left is
    # to try to make the substitutions less over-parenthesized.
    candidate_matcher = syntax_matchers.ast_matchers_matcher(
        parsed_template.tree)

    for k, unparenthesized in unparenthesized_mapping.items():
      parenthesized = safe_mapping[k]
      safe_mapping[k] = unparenthesized
      try:
        alt_replacement = self._lexical_template.substitute(safe_mapping)
        alt_parsed = matcher.parse_ast(
            alt_replacement, '<_BasePythonTemplate alternate proposal>')
      except matcher.ParseError as e:
        pass
      else:
        if candidate_matcher.match(
            matcher.MatchContext(alt_parsed), alt_parsed.tree):
          replacement = alt_replacement
          continue

      # if we made it this far, the replacement was not a success.
      safe_mapping[k] = parenthesized

    return replacement, safe_mapping

  @cached_property.cached_property
  def variables(self):
    return self._lexical_template.variables


def _matchers_for_matches(matches):
  """Returns AST matchers for all expressions in `matches`.

  Args:
    matches: A mapping of variable name -> match

  Returns:
    A mapping of <variable name> -> <matcher that must match>.
    Only variables that can be parenthesized are in this mapping, and the
    matcher must match where those variables are substituted in.
  """
  matchers = {}
  for k, v in matches.items():
    if (isinstance(v, matcher.LexicalASTMatch) and
        isinstance(v.matched, ast.expr)):
      matchers[k] = syntax_matchers.ast_matchers_matcher(v.matched)
  return matchers


class PythonTemplate(_BasePythonTemplate):
  _pattern_factory = syntax_matchers.ModulePattern


class PythonExprTemplate(_BasePythonTemplate):
  """A template for a Python expression."""

  @staticmethod
  def _pattern_factory(pattern):
    return ast_matchers.Module(
        body=base_matchers.ItemsAre(
            [ast_matchers.Expr(value=syntax_matchers.ExprPattern(pattern))]))


class PythonStmtTemplate(_BasePythonTemplate):
  """A template for a single Python statement."""

  @staticmethod
  def _pattern_factory(pattern):
    return ast_matchers.Module(
        body=base_matchers.ItemsAre([syntax_matchers.StmtPattern(pattern)]))
