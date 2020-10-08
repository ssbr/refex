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
"""Tests for refex.future_string."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import collections
import unittest

from absl.testing import absltest
from absl.testing import parameterized
import attr
import six

from refex import future_string


@attr.s
class Stringifiable(object):
  """Test class for future_string.Template string conversion.

  bytes(stringifiable)         == stringifiable.byte_string
  six.text_type(stringifiable) == stringifiable.text_string
  """
  text_string = attr.ib()
  byte_string = attr.ib()

  def __bytes__(self):
    return self.byte_string

  def __unicode__(self):
    return self.text_string

  __str__ = __bytes__ if six.PY2 else __unicode__


class StringifiableTest(object):
  """Stringifiable is complex enough to need tests..."""

  def test_stringifiable_text(self):
    self.assertEqual(
        six.text_type(Stringifiable(text_string=u'text', byte_string=b'bytes')),
        u'text')

  def test_stringifiable_bytes(self):
    self.assertEqual(
        bytes(Stringifiable(text_string=u'text', byte_string=b'bytes')),
        b'bytes')


@parameterized.named_parameters(
    ('substitute', lambda t, m: t.substitute(m)),
    ('safe_substitute', lambda t, m: t.safe_substitute(m)),
)
class TemplateTest(parameterized.TestCase):
  """Tests for future_string.Template."""

  @unittest.skipUnless(six.PY2, 'bytes formatting differs in py2 and py3+')
  def test_bytes_value_py2(self, substitute):
    """Tests that bytes and str (both Text) are interchangeable in Python 2."""
    self.assertEqual(
        substitute(future_string.Template(u'hello $var'), {u'var': b'world'}),
        u'hello world')

  @unittest.skipIf(six.PY2, 'bytes formatting differs in py2 and py3+')
  def test_bytes_value_py3(self, substitute):
    self.assertEqual(
        substitute(future_string.Template(u'hello $var'), {u'var': b'world'}),
        u"hello b'world'")

  def test_text(self, substitute):
    self.assertEqual(
        substitute(future_string.Template(u'hello $var'), {u'var': u'world'}),
        u'hello world')

  def test_text_unencodeable(self, substitute):
    self.assertEqual(
        substitute(
            future_string.Template(u'hello $var'), {u'var': u'world\xff'}),
        u'hello world\xff')

  def test_text_convertible(self, substitute):
    self.assertEqual(
        substitute(
            future_string.Template(u'hello $var'),
            {u'var': Stringifiable(text_string=u'world', byte_string=b'FAIL')}),
        u'hello world')

  def test_text_convertible_unencodeable(self, substitute):
    self.assertEqual(
        substitute(
            future_string.Template(u'hello $var'), {
                u'var':
                    Stringifiable(
                        text_string=u'world\xff', byte_string=b'FAIL')
            }), u'hello world\xff')

  def test_lazy_dict(self, substitute):
    self.assertEqual(
        substitute(
            future_string.Template(u'$x $y'), collections.Counter([u'x'])),
        u'1 0')


if __name__ == '__main__':
  absltest.main()
