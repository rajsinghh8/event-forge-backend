import unittest
from decimal import Decimal
from eventforge.errors import ValidationError
from eventforge.validation import decimal_value,pagination,parse_datetime,sort_field
class ValidationTests(unittest.TestCase):
 def test_decimal_never_accepts_float(self):
  self.assertEqual(decimal_value('12.30','amount'),Decimal('12.30'))
  with self.assertRaises(ValidationError):decimal_value(1.2,'amount')
 def test_invalid_pagination(self):
  with self.assertRaises(ValidationError):pagination({'limit':[b'0']})
 def test_bad_temporal_filter(self):
  with self.assertRaises(ValidationError):parse_datetime('not-a-date','startDate')
 def test_unsupported_sort(self):
  with self.assertRaises(ValidationError):sort_field('password_hash',{'name'})
