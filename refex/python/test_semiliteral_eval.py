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

from absl.testing import absltest

from refex.python import semiliteral_eval

# Create alias for easier tests.
Eval = semiliteral_eval.Eval  # pylint: disable=invalid-name


class SemiliteralEvalTest(absltest.TestCase):

  def testString(self):
    self.assertEqual(Eval('"hello world"'), 'hello world')
    self.assertEqual(Eval('\'hello world\''), 'hello world')

  def testBytes(self):
    self.assertEqual(Eval('b"hello world"'), b'hello world')
    self.assertEqual(Eval('b\'hello world\''), b'hello world')

  def testNumber(self):
    self.assertEqual(Eval('42'), 42)
    self.assertEqual(Eval('-42'), -42)

  def testTuple(self):
    self.assertEqual(Eval('(3, "four")'), (3, 'four'))
    self.assertEqual(Eval('()'), ())

  def testList(self):
    self.assertEqual(Eval('[1, 2, 3]'), [1, 2, 3])
    self.assertEqual(Eval('[[]]'), [[]])

  def testDict(self):
    self.assertEqual(Eval('{"x":16}'), {'x': 16})
    self.assertEqual(Eval('{"x":{"y": "z"}}'), {'x': {'y': 'z'}})
    self.assertEqual(Eval('{}'), {})

  def testSet(self):
    self.assertEqual(Eval('{3, 4, 5}'), {3, 4, 5})
    self.assertEqual(Eval('{"unity"}'), {'unity'})

  def testConstant(self):
    self.assertEqual(Eval('True'), True)
    self.assertEqual(Eval('False'), False)
    self.assertEqual(Eval('None'), None)

    self.assertRaises(SyntaxError, lambda: Eval('true'))
    self.assertEqual(Eval('true', constants={'true': True}), True)

  def testEmptyConstants(self):
    # If empty dict is passed, respect that choice and don't override with
    # default.
    self.assertRaises(SyntaxError, lambda: Eval('True', constants={}))

  def testCallable(self):
    self.assertEqual(
        Eval(
            '[1, "two", set([3])]', callables={'set': set}),
        [1, 'two', set([3])])

    self.assertEqual(
        Eval(
            'cons(42, (cons(43, None)))',
            callables={'cons': lambda x, y: [x, y]}), [42, [43, None]])

    self.assertEqual(
        Eval(
            'cons(y=42, x=(cons(y=43, x=None)))',
            callables={'cons': lambda x, y: [x, y]}), [[None, 43], 42])

  def testDottedNamesInCallable(self):
    # Dotted names are allowed in callable position, but must be explicitly
    # listed as a fully-qualified name in the callables dictionary.  This is to
    # curtail arbitrary attribute lookup.
    self.assertEqual(
        Eval(
            'a.B(42)', callables={'a.B': 'result is {}'.format}),
        'result is 42')

  def testDottedNamesInConstant(self):
    # Dotted names are allowed outside of callable position, but must be
    # explicitly listed as a fully-qualified name in the constants dictionary,
    # to curtail arbitrary attribute lookup.
    self.assertEqual(Eval('foo.BAR', constants={'foo.BAR': 42}), 42)

  def testUnknownCallables(self):
    self.assertRaises(SyntaxError, lambda: Eval('[1, "two", set([3])]'))
    self.assertRaises(SyntaxError, lambda: Eval('[1, "two", True()]'))

  def testCallablesOnlyInCallablePosition(self):
    self.assertRaises(SyntaxError, lambda: Eval('set', callables={'set': set}))

  def testLambdaIsSyntaxError(self):
    # https://mail.python.org/pipermail/tutor/2004-December/033828.html
    infinite_loop = '(lambda l: l(l)) (lambda l: l(l))'
    self.assertRaises(SyntaxError, lambda: Eval(infinite_loop))


if __name__ == '__main__':
  absltest.main()
