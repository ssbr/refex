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

# Lint as python2, python3
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import textwrap
import unittest

from absl.testing import absltest
from absl.testing import parameterized
import six

from refex import search
from refex.fix import fixer
from refex.fix.fixers import idiom_fixers


def _rewrite(fixer_, code):
  return search.rewrite_string(fixer_, code, 'example.py')


class ComprehensionFixerTest(absltest.TestCase):
  fixers = fixer.CombiningPythonFixer(idiom_fixers.SIMPLE_PYTHON_FIXERS)

  def test_fixes_listcomp(self):
    before = 'foo([hello for hello in world])'
    after = 'foo(list(world))'
    self.assertEqual(after, _rewrite(self.fixers, before))

  def test_fixes_setcomp(self):
    before = '_foo = {bar for bar in qux.spam.eggs()}'
    after = '_foo = set(qux.spam.eggs())'
    self.assertEqual(after, _rewrite(self.fixers, before))

  def test_ignores_dictcomp(self):
    before = '_foo = {bar: 1 for bar in qux.spam.eggs()}'
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_ignores_different_iteration_variable(self):
    before = '_foo = [baz for not_baz in qux]'
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_ignores_genexp(self):
    before = '_foo = (baz for baz in qux)'
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_ignores_if_filtering(self):
    before = '_foo = [hello for hello in world if some_condition]'
    self.assertEqual(before, _rewrite(self.fixers, before))


class NoneReturnFixerTest(absltest.TestCase):

  none_fixers = fixer.CombiningPythonFixer(idiom_fixers._NONE_RETURNS_FIXERS)

  def test_fix_non_void_function_with_bare_return(self):
    before = textwrap.dedent("""
      def func(a, b):
        if a:
         return 5
        elif b:
          print('a')
        return  # Nothing to return
    """)
    after = textwrap.dedent("""
      def func(a, b):
        if a:
         return 5
        elif b:
          print('a')
        return None  # Nothing to return
    """)
    self.assertEqual(after, _rewrite(self.none_fixers, before))

  def test_fix_void_function_with_return_none_and_bare_returns(self):
    before = textwrap.dedent("""
      def func(a, b):
        if a:
         return
        elif b:
          print('a')
          return None
        else:
          raise NotImplementedError
    """)
    after = textwrap.dedent("""
      def func(a, b):
        if a:
         return
        elif b:
          print('a')
          return
        else:
          raise NotImplementedError
    """)
    self.assertEqual(after, _rewrite(self.none_fixers, before))

  def test_fix_void_function_with_return_none_only(self):
    before = textwrap.dedent("""
      def func(a, b):
        if a:
         return None
        elif b:
          print('a')
          return None
        else:
          raise NotImplementedError
    """)
    after = textwrap.dedent("""
      def func(a, b):
        if a:
         return
        elif b:
          print('a')
          return
        else:
          raise NotImplementedError
    """)
    self.assertEqual(after, _rewrite(self.none_fixers, before))

  def test_skips_bad_void_functions_containing_other_functions(self):
    code = textwrap.dedent("""
      def func(a, b):
        if a:
         return None
        elif b:
          print('a')
        def inner():
          return 5
        return
    """)
    self.assertEmpty(
        list(search.find_iter(self.none_fixers, code, 'example.py')))

  def test_skips_bad_non_void_functions_containing_other_functions(self):
    code = textwrap.dedent("""
      def func(a, b):
        if a:
         return 5
        elif b:
          print('a')
          return
        def inner():
          return
        return inner
    """)
    self.assertEmpty(
        list(search.find_iter(self.none_fixers, code, 'example.py')))

  def test_skips_ok_funcs(self):
    code = textwrap.dedent("""
      def func1(a, b):
        if a:
         return 5
        elif b:
          print('a')
        return None

      def func2(a, b):
        if a:
         return
        elif b:
          print('a')
          return
        else:
          raise NotImplementedError
    """)
    self.assertEmpty(
        list(search.find_iter(self.none_fixers, code, 'example.py')))

  def test_single_return_none(self):
    before = textwrap.dedent("""
      def func(a, b):
        del a, b
        if 1:
          # do something here
          return None
    """)

    after = textwrap.dedent("""
      def func(a, b):
        del a, b
        if 1:
          # do something here
          return
    """)
    self.assertEqual(after, _rewrite(self.none_fixers, before))

  def test_fixes_methods(self):
    before = textwrap.dedent("""
      class A(object):
        def foo(self):
          if use_random():
            return None if random_bool() else 5
          elif something_else():
            return
          raise RuntimeError
    """)
    after = textwrap.dedent("""
      class A(object):
        def foo(self):
          if use_random():
            return None if random_bool() else 5
          elif something_else():
            return None
          raise RuntimeError
    """)
    self.assertEqual(after, _rewrite(self.none_fixers, before))

  @unittest.skipIf(six.PY2, 'Testing async functions')
  def test_fixes_async_functions(self):
    before = textwrap.dedent("""
      async def foo(self):
        if use_random():
          await asynio.sleep(2)
          return None if random_bool() else 5
        elif something_else():
          return
        else:
          return 6
    """)
    after = textwrap.dedent("""
      async def foo(self):
        if use_random():
          await asynio.sleep(2)
          return None if random_bool() else 5
        elif something_else():
          return None
        else:
          return 6
    """)
    self.assertEqual(after, _rewrite(self.none_fixers, before))

  def test_optional_return(self):
    """return None is fine if the function returns Optional[T]."""
    # TODO(b/117351081):  port this test to work on vanilla Python.
    example = textwrap.dedent("""
      # from __future__ import google_type_annotations
      import typing
      from typing import Optional

      def func() -> typing.Optional[int]:
        return None
      def func2() -> Optional[int]:
        return None
    """)

    self.assertEqual(example, _rewrite(self.none_fixers, example))


class MutableConstantFixers(parameterized.TestCase):

  mutable_constant_fixers = fixer.CombiningPythonFixer(
      idiom_fixers._MUTABLE_CONSTANT_FIXERS)

  @parameterized.named_parameters(
      ('set_literal', 'foo = {1}'),
      ('set_constructor', '_bar = set([1, 2])'),
      ('setcomp', 'mymod.bar = {x for x in y()}'),
  )
  def test_skips_non_constants(self, example):
    self.assertEqual(example, _rewrite(self.mutable_constant_fixers, example))

  def test_multiline_fix(self):
    before = textwrap.dedent("""
      _MYCONST = {
                  1,  # Thing1
                  2,  # Thing2
                 }
    """)
    after = textwrap.dedent("""
      _MYCONST = frozenset({
                  1,  # Thing1
                  2,  # Thing2
                 })
    """)
    self.assertEqual(after, _rewrite(self.mutable_constant_fixers, before))

  def test_does_not_recurse(self):
    before = textwrap.dedent("""
      _MYCONST = frozenset(
               (a, b)
                for a
                in y()
                for b in set([1, 2, 3])
               )
     """)
    self.assertEqual(before, _rewrite(self.mutable_constant_fixers, before))


class LoggingErrorFixerTest(parameterized.TestCase):
  fixers = fixer.CombiningPythonFixer(idiom_fixers._LOGGING_FIXERS)

  def test_nested_try_except(self):
    before = textwrap.dedent("""
    def foo(x, y):
      try:
        a = dangerous_func(x)
        b = other_func(y)
      except Exception as e:
        logging.error('Bad stuff: (%s, %d): %r', x, y, e)
        try:
          f = e.foo
        except AttributeError as e:
          logging.error('Error: %r', e)
        except IndexError as e2:
          logging.error('What happened? %s', e2)
    """)
    after = textwrap.dedent("""
    def foo(x, y):
      try:
        a = dangerous_func(x)
        b = other_func(y)
      except Exception as e:
        logging.exception('Bad stuff: (%s, %d): %r', x, y, e)
        try:
          f = e.foo
        except AttributeError as e:
          logging.exception('Error: %r', e)
        except IndexError as e2:
          logging.exception('What happened? %s', e2)
    """)
    self.assertEqual(after, _rewrite(self.fixers, before))

  def test_skips_exc_info(self):
    before = textwrap.dedent("""
      try:
        foo()
      except Exception as e:
        logging.error('Error: %r', e, exc_info=True)
    """)
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_skips_inner_unnamed_exception(self):
    before = textwrap.dedent("""
      try:
        foo()
      except Exception as e:
        try:
          bar()
        except:
          logging.error('bar() failed after foo() failed with: %r', e)
    """)
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_fixes_exception_as_message(self):
    before = textwrap.dedent("""
      try:
        foo()
      except Exception as e:
        logging.error(e)
    """)
    # NOTE(nmarrow): The replacement here is suboptimal and should be corrected
    # by the `logging.exception` fixer.
    after = textwrap.dedent("""
      try:
        foo()
      except Exception as e:
        logging.exception(e)
    """)
    self.assertEqual(after, _rewrite(self.fixers, before))


class LoggingExceptionFixerTest(parameterized.TestCase):
  fixers = fixer.CombiningPythonFixer(idiom_fixers._LOGGING_FIXERS)

  @parameterized.named_parameters(
      ('function_call_without_args', 'dangerous_func()', 'dangerous_func'),
      ('function_call_with_args', 'dangerous_func(1, b=2)', 'dangerous_func'),
      ('attribute_call_without_args', 'myobject.dangerous_func()',
       'myobject.dangerous_func'),
      ('attribute_call_with_args', 'myobject.dangerous_func(1, b=2)',
       'myobject.dangerous_func'),
      ('call_on_result_of_call',
       "myfunc().otherfunc(x, 'hello').dangerous_func()",
       "myfunc().otherfunc(x, 'hello').dangerous_func"),
      ('assignment_to_function_call', 'a = dangerous_func()', 'dangerous_func'),
      ('assignment_to_attribute_call', 'a = a.b.c.dangerous_func()',
       'a.b.c.dangerous_func'),
      ('returned_function_call_without_args', 'return dangerous_func()',
       'dangerous_func'),
  )
  def test_rewrites_redundant_logging_exception_for(self, try_body,
                                                    failing_name):
    before = textwrap.dedent("""
      f = open('/tmp/myfile', 'w')
      try:
        %s
      except (ValueError, KeyError) as exc:
        logging.exception(exc)
        _record_error(exc)
      else:
        f.write('...')
      finally:
        f.close()
    """ % try_body)
    after = before.replace(
        'logging.exception(exc)',
        'logging.exception(\'Call to "%s" resulted in an error\')' %
        failing_name)
    self.assertEqual(after, _rewrite(self.fixers, before))

  @parameterized.named_parameters((
      'same_exception_id',
      'e',
  ), (
      'different_exception_id',
      'e2',
  ))
  def test_fixes_multiple_except_clauses(self, second_exception_id):
    before = textwrap.dedent("""
      try:
        dangerous_func()
      except KeyError as e:
        if 'mykey' in str(e):
          logging.exception(e)
        raise
      except Exception as {second_exception_id}:
        logging.exception({second_exception_id})
    """.format(second_exception_id=second_exception_id))

    after = textwrap.dedent("""
      try:
        dangerous_func()
      except KeyError as e:
        if 'mykey' in str(e):
          logging.exception('Call to "dangerous_func" resulted in an error')
        raise
      except Exception as {second_exception_id}:
        logging.exception('Call to "dangerous_func" resulted in an error')
    """.format(second_exception_id=second_exception_id))
    self.assertEqual(after, _rewrite(self.fixers, before))

  def test_nested_try_except(self):
    before = textwrap.dedent("""
    def foo():
      try:
        return dangerous_func()
      except Exception as e:
        try:
          f = e.foo
        except AttributeError as e:
          logging.exception(e)
    """)
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_skips_ambiguous_try_body(self):
    before = textwrap.dedent("""
    def foo():
      try:
        return dangerous_func()
        other_dangerous_func()
      except Exception as e:
        logging.exception(e)
    """)
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_skips_non_redundant_logging_exception_call(self):
    before = textwrap.dedent("""
      try:
        dangerous_func()
      except Exception as e:
        msg = "Something bad happened"
        logging.exception(msg)
    """)
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_skips_replacement_requiring_escaping(self):
    before = textwrap.dedent("""
      try:
        foo("abc", "xyz").dangerous_func()
      except Exception as e:
        logging.exception(e)
    """)
    self.assertEqual(before, _rewrite(self.fixers, before))


if __name__ == '__main__':
  absltest.main()
