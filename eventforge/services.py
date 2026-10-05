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
 def list_events(self,u:int,l:int,o:int)->dict[str,Any]: return self._core.list_events(u,limit=l,offset=o)
 def event(self,u:int,e:int)->dict[str,Any]: return self._core.get_event(u,e)
 def create_event(self,u:int,d:dict[str,Any])->dict[str,Any]: return self._core.create_event(u,self._event_data(d))
 def update_event(self,u:int,e:int,d:dict[str,Any])->dict[str,Any]: return self._core.update_event(u,e,self._event_data(d))
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
 def list_expenses(self,u:int,e:int,category_id:int|None=None)->list[dict[str,Any]]:self._r.event(u,e);return self._budget_dto(self._budget.list_expenses(str(e),category_id=None if category_id is None else str(category_id)))
 def expense(self,u:int,e:int,x:int)->dict[str,Any]:self._r.event(u,e);return self._budget_dto(self._budget.get_expense(str(e),str(x)))
 def _incurred_at(self,value:Any)->datetime|None:
  if value is None:return None
  if not isinstance(value,str):raise ValidationError('incurred_at must be an ISO-8601 datetime')
  try:return datetime.fromisoformat(value.replace('Z','+00:00'))
  except ValueError:raise ValidationError('incurred_at must be an ISO-8601 datetime') from None
 def create_expense(self,u:int,e:int,d:dict[str,Any])->dict[str,Any]:
  with self._r.transaction():self._r.event(u,e);return self._budget_dto(self._budget.create_expense(str(e),str(u),category_id=str(d.get('category_id','')),description=d.get('description'),actual_amount=d.get('actual_amount'),incurred_at=self._incurred_at(d.get('incurred_at'))))
 def update_expense(self,u:int,e:int,x:int,d:dict[str,Any])->dict[str,Any]:
  with self._r.transaction():self._r.event(u,e);return self._budget_dto(self._budget.update_expense(str(e),str(x),str(u),category_id=None if 'category_id' not in d else str(d['category_id']),description=d.get('description'),actual_amount=d.get('actual_amount'),incurred_at=self._incurred_at(d['incurred_at']) if 'incurred_at' in d else None))
 def delete_expense(self,u:int,e:int,x:int)->None:
  with self._r.transaction():self._r.event(u,e);self._budget.delete_expense(str(e),str(x),str(u))

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
 def _event_data(self,d:dict[str,Any])->dict[str,Any]:
  if not isinstance(d.get('name'),str) or not d['name'].strip():raise ValidationError('name is required')
  allowed={'name','description','start_date','end_date','capacity','planned_budget'};out={k:v for k,v in d.items() if k in allowed}
  if 'planned_budget' in out:out['planned_budget']=Decimal(str(out['planned_budget']))
  return out
 # Notification/audit facade.  The scheduler uses this same facade as HTTP handlers.
 def list_notifications(self,u:int,l:int,o:int)->dict[str,Any]:return serialize(self._notifications.list_notifications(str(u),limit=l,offset=o))
 def notification(self,u:int,i:int)->dict[str,Any]:return serialize(self._notifications.get_notification(str(u),str(i)))
 def mark_notification_read(self,u:int,i:int)->dict[str,Any]:return serialize(self._notifications.mark_notification_read(str(u),str(i),read_at=datetime.utcnow()))
 def delete_notification(self,u:int,i:int)->None:self._notifications.delete_notification(str(u),str(i))
 def list_audit_logs(self,u:int,l:int,o:int)->dict[str,Any]:return serialize(self._notifications.list_audit_logs(str(u),limit=l,offset=o))
 def scan_notifications(self)->dict[str,Any]:return self._notifications.scan_due_task_notifications(scanned_at=datetime.utcnow())
