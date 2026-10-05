from __future__ import annotations
from eventforge.handlers.base import AuthenticatedHandler

class BudgetHandler(AuthenticatedHandler):
 async def get(self,event_id:str)->None:self.write_json(self.service.budget(self.user_id,int(event_id)))

class BudgetCategoriesHandler(AuthenticatedHandler):
 async def get(self,event_id:str,category_id:str|None=None)->None:
  self.write_json(self.service.list_budget_categories(self.user_id,int(event_id)) if category_id is None else self.service.budget_category(self.user_id,int(event_id),int(category_id)))
 async def post(self,event_id:str,category_id:str|None=None)->None:self.write_json(self.service.create_budget_category(self.user_id,int(event_id),self.body()),201)
 async def put(self,event_id:str,category_id:str)->None:self.write_json(self.service.update_budget_category(self.user_id,int(event_id),int(category_id),self.body()))
 async def delete(self,event_id:str,category_id:str)->None:
  self.service.delete_budget_category(self.user_id,int(event_id),int(category_id));self.set_status(204);self.finish()

class CategoryBudgetHandler(AuthenticatedHandler):
 async def get(self,event_id:str,category_id:str)->None:
  # The aggregate is event-wide; category scope is nevertheless validated first.
  self.service.budget_category(self.user_id,int(event_id),int(category_id))
  self.write_json(self.service.budget(self.user_id,int(event_id)))

class ExpensesHandler(AuthenticatedHandler):
 async def get(self,event_id:str,category_id:str,expense_id:str|None=None)->None:
  if expense_id is None:self.write_json(self.service.list_expenses(self.user_id,int(event_id),int(category_id)))
  else:self.write_json(self.service.expense(self.user_id,int(event_id),int(category_id),int(expense_id)))
 async def post(self,event_id:str,category_id:str)->None:self.write_json(self.service.create_expense(self.user_id,int(event_id),int(category_id),self.body()),201)
 async def patch(self,event_id:str,category_id:str,expense_id:str)->None:self.write_json(self.service.update_expense(self.user_id,int(event_id),int(category_id),int(expense_id),self.body()))
 async def delete(self,event_id:str,category_id:str,expense_id:str)->None:
  self.service.delete_expense(self.user_id,int(event_id),int(category_id),int(expense_id));self.set_status(204);self.finish()
