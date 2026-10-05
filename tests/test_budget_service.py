import unittest
from decimal import Decimal
from eventforge.errors import ConflictError
from eventforge.resource_services.budget import BudgetResourceService


class MemoryBudgetRepository:
 def __init__(self):self.categories={};self.expenses={};self.audits=[];self.notifications=[]
 def get_category(self,e,c):return self.categories.get((e,c))
 def list_categories(self,e):return [v for (event,_),v in self.categories.items() if event==e]
 def insert_category(self,c):self.categories[(c.event_id,c.id)]=c;return c
 def update_category(self,c):self.categories[(c.event_id,c.id)]=c;return c
 def delete_category(self,e,c):del self.categories[(e,c)]
 def get_expense(self,e,x):return self.expenses.get((e,x))
 def list_expenses(self,e,c=None):return [v for (event,_),v in self.expenses.items() if event==e and (c is None or v.category_id==c)]
 def insert_expense(self,x):self.expenses[(x.event_id,x.id)]=x;return x
 def update_expense(self,x):self.expenses[(x.event_id,x.id)]=x;return x
 def delete_expense(self,e,x):del self.expenses[(e,x)]
 def audit(self,**kw):self.audits.append(kw)
 def notify_spending_threshold_once(self,**kw):
  key=(kw['event_id'],kw['category_id'],kw['threshold'])
  if key in self.notifications:return False
  self.notifications.append(key);return True


class BudgetServiceTests(unittest.TestCase):
 def test_expense_cap_decimal_dto_and_threshold_deduplication(self):
  repo=MemoryBudgetRepository(); service=BudgetResourceService(repo)
  category=service.create_category('1','7',name='Food',planned_amount='100.00')
  expense=service.create_expense('1','7',category_id=category.id,description='Catering',actual_amount='90.00')
  self.assertEqual(expense.actual_amount,'90.00')
  self.assertEqual(service.get_budget_aggregate('1').actual_amount,'90.00')
  self.assertEqual(len(repo.notifications),1)
  service.update_expense('1',expense.id,'7',description='Catering',actual_amount='95.00')
  self.assertEqual(len(repo.notifications),1)
  with self.assertRaises(ConflictError):
   service.create_expense('1','7',category_id=category.id,description='Extra',actual_amount=Decimal('5.01'))
  self.assertTrue(any(a['action']=='expense.created' for a in repo.audits))
