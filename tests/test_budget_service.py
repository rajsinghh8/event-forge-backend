import unittest
from datetime import date
from eventforge.errors import ConflictError, NotFoundError, ValidationError
from eventforge.resource_services.budget import BudgetResourceService

class MemoryBudgetRepository:
 def __init__(self):self.categories={};self.expenses={};self.audits=[];self.notifications=[]
 def get_category(self,e,c):return self.categories.get((e,c))
 def list_categories(self,e):return [v for (event,_),v in self.categories.items() if event==e]
 def insert_category(self,c):self.categories[(c.event_id,c.id)]=c;return c
 def update_category(self,c):self.categories[(c.event_id,c.id)]=c;return c
 def delete_category(self,e,c):del self.categories[(e,c)]
 def get_expense(self,e,c,x):
  value=self.expenses.get((e,x));return value if value and value.category_id==c else None
 def list_expenses(self,e,c):return [v for (event,_),v in self.expenses.items() if event==e and v.category_id==c]
 def insert_expense(self,x):self.expenses[(x.event_id,x.id)]=x;return x
 def update_expense(self,x):self.expenses[(x.event_id,x.id)]=x;return x
 def delete_expense(self,e,c,x):
  if not self.get_expense(e,c,x):raise NotFoundError('expense was not found')
  del self.expenses[(e,x)]
 def audit(self,**kw):self.audits.append(kw)
 def notify_spending_threshold_once(self,**kw):
  key=(kw['event_id'],kw['category_id'],kw['threshold'])
  if key in self.notifications:return False
  self.notifications.append(key);return True

class BudgetServiceTests(unittest.TestCase):
 def setUp(self):
  self.repo=MemoryBudgetRepository();self.service=BudgetResourceService(self.repo)
  self.category=self.service.create_category('1','7',name='Food',planned_amount='100.00')
 def test_expense_contract_and_normalized_audit(self):
  expense=self.service.create_expense('1',self.category.id,'7',name='Catering',amount='90.00',spent_on='2025-01-02',notes=' deposit ')
  self.assertEqual((expense.name,expense.amount,expense.spent_on,expense.notes),('Catering','90.00',date(2025,1,2),'deposit'))
  updated=self.service.update_expense('1',self.category.id,expense.id,'7',amount='95.00',notes=None,notes_supplied=True)
  self.assertEqual(updated.notes,None)
  self.assertEqual({entry['action'] for entry in self.repo.audits},{'create','update'})
  self.assertEqual(len(self.repo.notifications),1)
  with self.assertRaises(ConflictError):self.service.create_expense('1',self.category.id,'7',name='Extra',amount='5.01',spent_on='2025-01-03')
 def test_expense_validation_and_category_scope(self):
  for amount in ('0','-1','1.001',1.5):
   with self.assertRaises(ValidationError):self.service.create_expense('1',self.category.id,'7',name='X',amount=amount,spent_on='2025-01-01')
  with self.assertRaises(ValidationError):self.service.create_expense('1',self.category.id,'7',name='X',amount='1',spent_on='not-a-date')
  other=self.service.create_category('1','7',name='Travel',planned_amount='100')
  expense=self.service.create_expense('1',self.category.id,'7',name='X',amount='1',spent_on='2025-01-01')
  with self.assertRaises(NotFoundError):self.service.get_expense('1',other.id,expense.id)

if __name__=='__main__':unittest.main()
