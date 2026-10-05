from __future__ import annotations
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from eventforge.errors import AuthenticationError, BusinessRuleError, ValidationError
from eventforge.models import serialize
from eventforge.repositories import Repository
from eventforge.resource_services.core import CoreResourceService
from eventforge.resource_services.operations import OperationsResourceService
from eventforge.resource_services.budget import BudgetResourceService
from eventforge.resource_services.notifications import NotificationResourceService
from eventforge.security import hash_password, issue_token, verify_password
from eventforge.config import Settings
from eventforge.validation import decimal_value, parse_date, require_text


class EventForgeService:
 """Handler-facing facade; resource rules live in specialized services."""
 def __init__(self,repository:Repository,settings:Settings)->None:
  self._r=repository;self._s=settings;self._core=CoreResourceService(repository);self._operations=OperationsResourceService(repository);self._budget=BudgetResourceService(repository);self._notifications=NotificationResourceService(repository)
 def register(self,data:dict[str,Any])->dict[str,Any]:
  email=data.get('email');password=data.get('password')
  if not isinstance(email,str) or '@' not in email or not isinstance(password,str) or len(password)<8:raise ValidationError('email and password (8+ characters) are required')
  if self._r.user_by_email(email.lower()):raise BusinessRuleError('email is already registered')
  user=self._r.create_user(email.lower(),hash_password(password,self._s.bcrypt_rounds));return {'user':serialize(user),'token':issue_token(int(user['id']),self._s)}
 def login(self,data:dict[str,Any])->dict[str,Any]:
  email=data.get('email');password=data.get('password');user=self._r.user_by_email(email.lower()) if isinstance(email,str) else None
  if not user or not isinstance(password,str) or not verify_password(password,str(user['password_hash'])):raise AuthenticationError('invalid email or password')
  return {'user':serialize(user),'token':issue_token(int(user['id']),self._s)}

 # Core facade delegates ----------------------------------------------------
 def list_events(self,u:int,l:int,o:int,filters:dict[str,Any]|None=None,sort:str='-id')->dict[str,Any]: return self._core.list_events(u,limit=l,offset=o,filters=filters,sort=sort)
 def event(self,u:int,e:int)->dict[str,Any]: return self._core.get_event(u,e)
 def create_event(self,u:int,d:dict[str,Any])->dict[str,Any]: return self._core.create_event(u,self._event_data(d,required=True))
 def update_event(self,u:int,e:int,d:dict[str,Any])->dict[str,Any]: return self._core.update_event(u,e,self._event_data(d,required=False))
 def delete_event(self,u:int,e:int)->None:self._core.delete_event(u,e)
 def list_tasks(self,u:int,e:int)->list[dict[str,Any]]:return self._core.list_tasks(u,e)
 def task(self,u:int,e:int,i:int)->dict[str,Any]:return self._core.get_task(u,e,i)
 def create_task(self,u:int,e:int,d:dict[str,Any])->dict[str,Any]:return self._core.create_task(u,e,d)
 def update_task(self,u:int,e:int,i:int,d:dict[str,Any])->dict[str,Any]:return self._core.update_task(u,e,i,d)
 def delete_task(self,u:int,e:int,i:int)->None:self._core.delete_task(u,e,i)
 def list_guests(self,u:int,e:int,l:int,o:int)->dict[str,Any]:return self._core.list_guests(u,e,limit=l,offset=o)
 def guest(self,u:int,e:int,i:int)->dict[str,Any]:return self._core.get_guest(u,e,i)
 def create_guest(self,u:int,e:int,d:dict[str,Any])->dict[str,Any]:return self._core.create_guest(u,e,d)
 def update_guest(self,u:int,e:int,i:int,d:dict[str,Any])->dict[str,Any]:return self._core.update_guest(u,e,i,d)
 def delete_guest(self,u:int,e:int,i:int)->None:self._core.delete_guest(u,e,i)

 # Budget facade: owner validation and the domain mutation/audit/notification share one transaction.
 def _budget_dto(self,value:Any)->Any:return serialize(asdict(value) if is_dataclass(value) else value)
 def budget(self,u:int,e:int)->dict[str,Any]:self._r.event(u,e);return self._budget_dto(self._budget.get_budget_aggregate(str(e)))
 def list_budget_categories(self,u:int,e:int)->list[dict[str,Any]]:self._r.event(u,e);return self._budget_dto(self._budget.list_categories(str(e)))
 def budget_category(self,u:int,e:int,c:int)->dict[str,Any]:self._r.event(u,e);return self._budget_dto(self._budget.get_category(str(e),str(c)))
 def create_budget_category(self,u:int,e:int,d:dict[str,Any])->dict[str,Any]:
  with self._r.transaction():self._r.event(u,e);return self._budget_dto(self._budget.create_category(str(e),str(u),name=d.get('name'),planned_amount=d.get('planned_amount')))
 def update_budget_category(self,u:int,e:int,c:int,d:dict[str,Any])->dict[str,Any]:
  with self._r.transaction():self._r.event(u,e);return self._budget_dto(self._budget.update_category(str(e),str(c),str(u),name=d.get('name'),planned_amount=d.get('planned_amount')))
 def delete_budget_category(self,u:int,e:int,c:int)->None:
  with self._r.transaction():self._r.event(u,e);self._budget.delete_category(str(e),str(c),str(u))
 def list_expenses(self,u:int,e:int,c:int)->list[dict[str,Any]]:self._r.event(u,e);return self._budget_dto(self._budget.list_expenses(str(e),str(c)))
 def expense(self,u:int,e:int,c:int,x:int)->dict[str,Any]:self._r.event(u,e);return self._budget_dto(self._budget.get_expense(str(e),str(c),str(x)))
 def _expense_data(self,d:dict[str,Any],*,creating:bool)->dict[str,Any]:
  allowed={'name','amount','spent_on','notes'};unknown=set(d)-allowed
  if unknown:raise ValidationError('unsupported expense fields: '+', '.join(sorted(unknown)))
  if creating and set(d) - {'notes'} != {'name','amount','spent_on'}:raise ValidationError('name, amount, and spent_on are required')
  if not creating and not d:raise ValidationError('at least one expense field is required')
  return d
 def create_expense(self,u:int,e:int,c:int,d:dict[str,Any])->dict[str,Any]:
  d=self._expense_data(d,creating=True)
  with self._r.transaction():self._r.event(u,e);return self._budget_dto(self._budget.create_expense(str(e),str(c),str(u),name=d['name'],amount=d['amount'],spent_on=d['spent_on'],notes=d.get('notes')))
 def update_expense(self,u:int,e:int,c:int,x:int,d:dict[str,Any])->dict[str,Any]:
  d=self._expense_data(d,creating=False)
  with self._r.transaction():self._r.event(u,e);return self._budget_dto(self._budget.update_expense(str(e),str(c),str(x),str(u),name=d.get('name'),amount=d.get('amount'),spent_on=d.get('spent_on'),notes=d.get('notes'),notes_supplied='notes' in d))
 def delete_expense(self,u:int,e:int,c:int,x:int)->None:
  with self._r.transaction():self._r.event(u,e);self._budget.delete_expense(str(e),str(c),str(x),str(u))

 # Operations facade.
 def list_schedule_items(self,u:int,e:int):return self._operations.list_schedule_items(u,e)
 def schedule_item(self,u:int,e:int,i:int):return self._operations.get_schedule_item(u,e,i)
 def create_schedule_item(self,u:int,e:int,d:dict[str,Any]):return self._operations.create_schedule_item(u,e,d)
 def update_schedule_item(self,u:int,e:int,i:int,d:dict[str,Any]):return self._operations.update_schedule_item(u,e,i,d)
 def delete_schedule_item(self,u:int,e:int,i:int)->None:self._operations.delete_schedule_item(u,e,i)
 def list_vendors(self,u:int,e:int):return self._operations.list_vendors(u,e)
 def vendor(self,u:int,e:int,i:int):return self._operations.get_vendor(u,e,i)
 def create_vendor(self,u:int,e:int,d:dict[str,Any]):return self._operations.create_vendor(u,e,d)
 def update_vendor(self,u:int,e:int,i:int,d:dict[str,Any]):return self._operations.update_vendor(u,e,i,d)
 def delete_vendor(self,u:int,e:int,i:int)->None:self._operations.delete_vendor(u,e,i)
 def list_vendor_payments(self,u:int,e:int,v:int):return self._operations.list_vendor_payments(u,e,v)
 def vendor_payment(self,u:int,e:int,v:int,p:int):return self._operations.get_vendor_payment(u,e,v,p)
 def create_vendor_payment(self,u:int,e:int,v:int,d:dict[str,Any]):return self._operations.create_vendor_payment(u,e,v,d)
 def update_vendor_payment(self,u:int,e:int,v:int,p:int,d:dict[str,Any]):return self._operations.update_vendor_payment(u,e,v,p,d)
 def delete_vendor_payment(self,u:int,e:int,v:int,p:int)->None:self._operations.delete_vendor_payment(u,e,v,p)

 # Generic path is deliberately retained only for feature groups not owned by Core.
 def nested_list(self,t:str,u:int,e:int,l:int,o:int)->dict[str,Any]:
  rows,total=self._r.list_nested(t,u,e,l,o);return {'items':serialize(rows),'total':total,'limit':l,'offset':o}
 def nested_get(self,t:str,u:int,e:int,i:int)->dict[str,Any]:return serialize(self._r.nested(t,u,e,i))
 def nested_create(self,t:str,u:int,e:int,d:dict[str,Any])->dict[str,Any]:self._r.event(u,e);return serialize(self._r._insert(t,{'event_id':e,**d}))
 def nested_update(self,t:str,u:int,e:int,i:int,d:dict[str,Any])->dict[str,Any]:self._r.nested(t,u,e,i);return serialize(self._r._update(t,i,d))
 def nested_delete(self,t:str,u:int,e:int,i:int)->None:self._r.nested(t,u,e,i);self._r._delete(t,i)
 def _event_data(self,d:dict[str,Any],required:bool)->dict[str,Any]:
  allowed={'name','description','start_date','end_date','capacity','planned_budget'}
  if required:
   missing=allowed-set(d)
   if missing:raise ValidationError('missing required event fields: '+', '.join(sorted(missing)))
  out={k:v for k,v in d.items() if k in allowed}
  if not out:raise ValidationError('at least one event field is required')
  if 'name' in out:out['name']=require_text(out['name'],'name')
  if 'description' in out:out['description']=require_text(out['description'],'description')
  for field in ('start_date','end_date'):
   if field in out:out[field]=parse_date(out[field],field)
  if 'start_date' in out and 'end_date' in out and out['end_date'] < out['start_date']:raise ValidationError('end_date must not be before start_date')
  if 'capacity' in out:
   value=out['capacity']
   if isinstance(value,bool) or not isinstance(value,int) or value<0:raise ValidationError('capacity must be a non-negative integer')
  if 'planned_budget' in out:
   value=decimal_value(out['planned_budget'],'planned_budget')
   if value<0:raise ValidationError('planned_budget must be non-negative')
   out['planned_budget']=value
  return out
 # Notification/audit facade.  The scheduler uses this same facade as HTTP handlers.
 def list_notifications(self,u:int,l:int,o:int)->dict[str,Any]:return serialize(self._notifications.list_notifications(str(u),limit=l,offset=o))
 def notification(self,u:int,i:int)->dict[str,Any]:return serialize(self._notifications.get_notification(str(u),str(i)))
 def mark_notification_read(self,u:int,i:int)->dict[str,Any]:return serialize(self._notifications.mark_notification_read(str(u),str(i),read_at=datetime.utcnow()))
 def delete_notification(self,u:int,i:int)->None:self._notifications.delete_notification(str(u),str(i))
 def list_audit_logs(self,u:int,l:int,o:int)->dict[str,Any]:return serialize(self._notifications.list_audit_logs(str(u),limit=l,offset=o))
 def list_event_audit_logs(self,u:int,e:int,l:int,o:int)->dict[str,Any]:return serialize(self._notifications.list_event_audit_logs(str(u),str(e),limit=l,offset=o))
 def scan_notifications(self)->dict[str,Any]:return self._notifications.scan_due_task_notifications(scanned_at=datetime.utcnow())
