"""Budget-category and nested-expense domain service."""
from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import uuid4
from eventforge.errors import ConflictError, NotFoundError, ValidationError

MoneyInput = Decimal | str | int | float
_MONEY_PLACES=Decimal('0.01'); _ZERO=Decimal('0.00'); _NINETY_PERCENT=Decimal('0.90')

@dataclass(frozen=True, slots=True)
class BudgetCategoryRecord:
 id:str; event_id:str; name:str; planned_amount:Decimal; created_at:datetime|None=None; updated_at:datetime|None=None
@dataclass(frozen=True, slots=True)
class ExpenseRecord:
 id:str; event_id:str; category_id:str; name:str; amount:Decimal; spent_on:date; notes:str|None=None; created_at:datetime|None=None; updated_at:datetime|None=None
@dataclass(frozen=True, slots=True)
class BudgetCategoryDTO:
 id:str; event_id:str; name:str; planned_amount:str; actual_amount:str; remaining_amount:str; spent_percent:str
@dataclass(frozen=True, slots=True)
class ExpenseDTO:
 id:str; event_id:str; category_id:str; name:str; amount:str; spent_on:date; notes:str|None
@dataclass(frozen=True, slots=True)
class CategoryBudgetAggregateDTO:
 category:BudgetCategoryDTO; expense_count:int
@dataclass(frozen=True, slots=True)
class BudgetAggregateDTO:
 event_id:str; planned_amount:str; actual_amount:str; remaining_amount:str; spent_percent:str; categories:tuple[CategoryBudgetAggregateDTO,...]

class BudgetRepository(Protocol):
 def get_category(self,event_id:str,category_id:str)->BudgetCategoryRecord|None: ...
 def list_categories(self,event_id:str)->list[BudgetCategoryRecord]: ...
 def insert_category(self,category:BudgetCategoryRecord)->BudgetCategoryRecord: ...
 def update_category(self,category:BudgetCategoryRecord)->BudgetCategoryRecord: ...
 def delete_category(self,event_id:str,category_id:str)->None: ...
 def get_expense(self,event_id:str,category_id:str,expense_id:str)->ExpenseRecord|None: ...
 def list_expenses(self,event_id:str,category_id:str)->list[ExpenseRecord]: ...
 def insert_expense(self,expense:ExpenseRecord)->ExpenseRecord: ...
 def update_expense(self,expense:ExpenseRecord)->ExpenseRecord: ...
 def delete_expense(self,event_id:str,category_id:str,expense_id:str)->None: ...
 def audit(self,*,event_id:str,actor_id:str,action:str,entity_type:str,entity_id:str,details:dict[str,str])->None: ...
 def notify_spending_threshold_once(self,*,event_id:str,category_id:str,spent_amount:Decimal,planned_amount:Decimal,threshold:Decimal)->bool: ...

class BudgetResourceService:
 def __init__(self,repository:BudgetRepository)->None:self._repository=repository
 # Categories retain their established contract.
 def create_category(self,event_id:str,actor_id:str,*,name:str,planned_amount:MoneyInput)->BudgetCategoryDTO:
  created=self._repository.insert_category(BudgetCategoryRecord(str(uuid4()),event_id,self._required_text(name,'name'),self._money(planned_amount,'planned_amount',positive=False)))
  self._audit(actor_id,'create',created,{'planned_amount':self._decimal_text(created.planned_amount)})
  return self._category_dto(created,_ZERO)
 def get_category(self,event_id:str,category_id:str)->BudgetCategoryDTO:
  category=self._category_or_404(event_id,category_id);return self._category_dto(category,self._spent(event_id,category_id))
 def list_categories(self,event_id:str)->tuple[BudgetCategoryDTO,...]:return tuple(self.get_category(event_id,c.id) for c in self._repository.list_categories(event_id))
 def update_category(self,event_id:str,category_id:str,actor_id:str,*,name:str|None=None,planned_amount:MoneyInput|None=None)->BudgetCategoryDTO:
  category=self._category_or_404(event_id,category_id);spent=self._spent(event_id,category_id)
  planned=category.planned_amount if planned_amount is None else self._money(planned_amount,'planned_amount',positive=False)
  if planned<spent:raise ConflictError('planned_amount cannot be less than actual spending')
  updated=self._repository.update_category(replace(category,name=category.name if name is None else self._required_text(name,'name'),planned_amount=planned))
  self._audit(actor_id,'update',updated,{'planned_amount':self._decimal_text(planned)});self._notify_if_needed(updated,spent);return self._category_dto(updated,spent)
 def delete_category(self,event_id:str,category_id:str,actor_id:str)->None:
  category=self._category_or_404(event_id,category_id)
  if self._spent(event_id,category_id)>_ZERO:raise ConflictError('a category with recorded spending cannot be deleted')
  self._repository.delete_category(event_id,category_id);self._audit(actor_id,'delete',category,{})
 # Nested expense contract: name, amount, spent_on and notes only.
 def create_expense(self,event_id:str,category_id:str,actor_id:str,*,name:str,amount:MoneyInput,spent_on:date,notes:str|None=None)->ExpenseDTO:
  category=self._category_or_404(event_id,category_id);value=self._money(amount,'amount',positive=True)
  self._assert_within_plan(category,self._spent(event_id,category_id)+value)
  created=self._repository.insert_expense(ExpenseRecord(str(uuid4()),event_id,category_id,self._required_text(name,'name'),value,self._date(spent_on,'spent_on'),self._optional_text(notes,'notes')))
  self._audit(actor_id,'create',created,{'amount':self._decimal_text(value),'category_id':category_id});self._notify_if_needed(category,self._spent(event_id,category_id));return self._expense_dto(created)
 def get_expense(self,event_id:str,category_id:str,expense_id:str)->ExpenseDTO:return self._expense_dto(self._expense_or_404(event_id,category_id,expense_id))
 def list_expenses(self,event_id:str,category_id:str)->tuple[ExpenseDTO,...]:
  self._category_or_404(event_id,category_id);return tuple(self._expense_dto(x) for x in self._repository.list_expenses(event_id,category_id))
 def update_expense(self,event_id:str,category_id:str,expense_id:str,actor_id:str,*,name:str|None=None,amount:MoneyInput|None=None,spent_on:date|None=None,notes:str|None=None,notes_supplied:bool=False)->ExpenseDTO:
  expense=self._expense_or_404(event_id,category_id,expense_id);value=expense.amount if amount is None else self._money(amount,'amount',positive=True)
  category=self._category_or_404(event_id,category_id);self._assert_within_plan(category,self._spent(event_id,category_id,excluding_expense_id=expense_id)+value)
  updated=self._repository.update_expense(replace(expense,name=expense.name if name is None else self._required_text(name,'name'),amount=value,spent_on=expense.spent_on if spent_on is None else self._date(spent_on,'spent_on'),notes=expense.notes if not notes_supplied else self._optional_text(notes,'notes')))
  self._audit(actor_id,'update',updated,{'amount':self._decimal_text(value),'category_id':category_id});self._notify_if_needed(category,self._spent(event_id,category_id));return self._expense_dto(updated)
 def delete_expense(self,event_id:str,category_id:str,expense_id:str,actor_id:str)->None:
  expense=self._expense_or_404(event_id,category_id,expense_id);self._repository.delete_expense(event_id,category_id,expense_id);self._audit(actor_id,'delete',expense,{'amount':self._decimal_text(expense.amount)})
 def get_budget_aggregate(self,event_id:str)->BudgetAggregateDTO:
  categories=[];planned=actual=_ZERO
  for category in self._repository.list_categories(event_id):
   expenses=self._repository.list_expenses(event_id,category.id);spent=sum((x.amount for x in expenses),_ZERO);planned+=category.planned_amount;actual+=spent;categories.append(CategoryBudgetAggregateDTO(self._category_dto(category,spent),len(expenses)))
  return BudgetAggregateDTO(event_id,self._decimal_text(planned),self._decimal_text(actual),self._decimal_text(planned-actual),self._percent(actual,planned),tuple(categories))
 def _category_or_404(self,event_id:str,category_id:str)->BudgetCategoryRecord:
  value=self._repository.get_category(event_id,category_id)
  if value is None:raise NotFoundError('budget category was not found')
  return value
 def _expense_or_404(self,event_id:str,category_id:str,expense_id:str)->ExpenseRecord:
  value=self._repository.get_expense(event_id,category_id,expense_id)
  if value is None:raise NotFoundError('expense was not found')
  return value
 def _spent(self,event_id:str,category_id:str,*,excluding_expense_id:str|None=None)->Decimal:return sum((x.amount for x in self._repository.list_expenses(event_id,category_id) if x.id!=excluding_expense_id),_ZERO)
 def _assert_within_plan(self,category:BudgetCategoryRecord,spent:Decimal)->None:
  if spent>category.planned_amount:raise ConflictError('actual spending cannot exceed planned_amount')
 def _notify_if_needed(self,category:BudgetCategoryRecord,spent:Decimal)->None:
  if category.planned_amount>_ZERO and spent>=category.planned_amount*_NINETY_PERCENT:self._repository.notify_spending_threshold_once(event_id=category.event_id,category_id=category.id,spent_amount=spent,planned_amount=category.planned_amount,threshold=_NINETY_PERCENT)
 def _audit(self,actor_id:str,action:str,record:BudgetCategoryRecord|ExpenseRecord,details:dict[str,str])->None:self._repository.audit(event_id=record.event_id,actor_id=actor_id,action=action,entity_type='budget_category' if isinstance(record,BudgetCategoryRecord) else 'expense',entity_id=record.id,details=details)
 @staticmethod
 def _required_text(value:object,field:str)->str:
  if not isinstance(value,str) or not value.strip():raise ValidationError(f'{field} is required')
  return value.strip()
 @classmethod
 def _optional_text(cls,value:object,field:str)->str|None:
  if value is None:return None
  return cls._required_text(value,field)
 @staticmethod
 def _date(value:object,field:str)->date:
  if isinstance(value,date) and not isinstance(value,datetime):return value
  if not isinstance(value,str):raise ValidationError(f'{field} must be an ISO date')
  try:return date.fromisoformat(value)
  except ValueError:raise ValidationError(f'{field} must be an ISO date') from None
 @staticmethod
 def _money(value:MoneyInput,field:str,*,positive:bool)->Decimal:
  if isinstance(value,bool) or isinstance(value,float):raise ValidationError(f'{field} must be a decimal amount')
  try:amount=Decimal(str(value))
  except (InvalidOperation,ValueError,TypeError):raise ValidationError(f'{field} must be a decimal amount') from None
  if not amount.is_finite() or amount.as_tuple().exponent < -2 or (amount<=_ZERO if positive else amount<_ZERO):raise ValidationError(f"{field} must be a {'positive' if positive else 'non-negative'} amount with at most two decimal places")
  return amount.quantize(_MONEY_PLACES)
 @staticmethod
 def _decimal_text(value:Decimal)->str:return format(value.quantize(_MONEY_PLACES),'f')
 @classmethod
 def _percent(cls,actual:Decimal,planned:Decimal)->str:return '0.00' if planned==_ZERO else cls._decimal_text(actual/planned*Decimal('100'))
 @classmethod
 def _category_dto(cls,category:BudgetCategoryRecord,spent:Decimal)->BudgetCategoryDTO:return BudgetCategoryDTO(category.id,category.event_id,category.name,cls._decimal_text(category.planned_amount),cls._decimal_text(spent),cls._decimal_text(category.planned_amount-spent),cls._percent(spent,category.planned_amount))
 @classmethod
 def _expense_dto(cls,expense:ExpenseRecord)->ExpenseDTO:return ExpenseDTO(expense.id,expense.event_id,expense.category_id,expense.name,cls._decimal_text(expense.amount),expense.spent_on,expense.notes)
