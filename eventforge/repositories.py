from __future__ import annotations
from contextlib import contextmanager
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator, Mapping

from eventforge.db import Database
from eventforge.errors import NotFoundError
from eventforge.resource_services.budget import BudgetCategoryRecord, ExpenseRecord


class Repository:
 """MySQL persistence adapter.

 Core methods keep the event owner predicate in every resource query.  The
 transaction context is deliberately reusable: CoreResourceService opens one
 around a mutation so the mutation, audit row, and notification are committed
 (or rolled back) together.
 """
 def __init__(self, db: Database)->None:
  self._db=db; self._tx_conn: Any|None=None; self._tx_depth=0

 @contextmanager
 def transaction(self)->Iterator[None]:
  if self._tx_conn is not None:
   self._tx_depth+=1
   try: yield
   finally: self._tx_depth-=1
   return
  with self._db.transaction() as conn:
   self._tx_conn=conn; self._tx_depth=1
   try: yield
   finally: self._tx_depth=0; self._tx_conn=None

 @contextmanager
 def _cursor(self, *, write: bool=False)->Iterator[Any]:
  if self._tx_conn is not None:
   yield self._tx_conn.cursor(); return
  manager=self._db.transaction() if write else self._db.connection()
  with manager as conn: yield conn.cursor()

 def _one(self, cursor: Any)->dict[str,Any]|None:
  row=cursor.fetchone(); return self._row(cursor,row) if row else None
 def _row(self,cursor:Any,row:Any)->dict[str,Any]:
  values=dict(zip(cursor.column_names,row))
  return {key:self._wire_value(value) for key,value in values.items()}
 def _rows(self,cursor:Any)->list[dict[str,Any]]: return [self._row(cursor,row) for row in cursor.fetchall()]
 @staticmethod
 def _wire_value(value:Any)->Any:
  if isinstance(value,Decimal): return format(value,'f')
  if isinstance(value,(datetime,date)): return value.isoformat()
  return value

 # Authentication ----------------------------------------------------------
 def create_user(self,email:str,password_hash:str)->dict[str,Any]:
  with self._cursor(write=True) as q:
   q.execute('INSERT INTO users(email,password_hash) VALUES(%s,%s)',(email,password_hash));q.execute('SELECT id,email,created_at FROM users WHERE id=%s',(q.lastrowid,));return self._one(q) or {}
 def user_by_email(self,email:str)->dict[str,Any]|None:
  with self._cursor() as q:q.execute('SELECT * FROM users WHERE email=%s',(email,));return self._one(q)

 # Core owner-scoped contract ---------------------------------------------
 def get_event(self,user_id:str|int,event_id:str|int)->dict[str,Any]:
  with self._cursor() as q:
   q.execute('SELECT * FROM events WHERE id=%s AND owner_id=%s',(event_id,user_id)); row=self._one(q)
  if not row: raise NotFoundError('event was not found')
  return row
 event=get_event
 def list_events(self,user_id:str|int,limit:int|None=None,offset:int|None=None,**kwargs:Any)->tuple[list[dict[str,Any]],int]:
  limit=kwargs.get('limit',limit); offset=kwargs.get('offset',offset)
  with self._cursor() as q:
   q.execute('SELECT COUNT(*) FROM events WHERE owner_id=%s',(user_id,)); total=q.fetchone()[0]
   q.execute('SELECT * FROM events WHERE owner_id=%s ORDER BY id DESC LIMIT %s OFFSET %s',(user_id,limit,offset)); return self._rows(q),total
 def create_event(self,user_id:str|int,values:Mapping[str,object])->dict[str,Any]:
  return self._insert('events',{'owner_id':user_id,**dict(values)})
 def update_event(self,user_id:str|int,event_id:str|int,values:Mapping[str,object])->dict[str,Any]:
  self.get_event(user_id,event_id); return self._scoped_update('events',user_id,event_id,values)
 def delete_event(self,user_id:str|int,event_id:str|int)->None:
  self.get_event(user_id,event_id)
  with self._cursor(write=True) as q:q.execute('DELETE FROM events WHERE id=%s AND owner_id=%s',(event_id,user_id))

 def _core_item(self,table:str,user_id:Any,event_id:Any,item_id:Any)->dict[str,Any]:
  with self._cursor() as q:
   q.execute(f'SELECT r.* FROM {table} r JOIN events e ON e.id=r.event_id WHERE r.id=%s AND r.event_id=%s AND e.owner_id=%s',(item_id,event_id,user_id)); row=self._one(q)
  if not row: raise NotFoundError(f'{table} resource was not found')
  return self._task_shape(row) if table=='tasks' else row
 def _core_list(self,table:str,user_id:Any,event_id:Any,limit:int|None=None,offset:int|None=None)->tuple[list[dict[str,Any]],int]:
  self.get_event(user_id,event_id)
  with self._cursor() as q:
   q.execute(f'SELECT COUNT(*) FROM {table} WHERE event_id=%s',(event_id,)); total=q.fetchone()[0]
   sql=f'SELECT * FROM {table} WHERE event_id=%s ORDER BY id DESC'
   params:list[Any]=[event_id]
   if limit is not None: sql+=' LIMIT %s OFFSET %s';params.extend([limit,offset or 0])
   q.execute(sql,tuple(params)); rows=self._rows(q)
  return ([self._task_shape(row) for row in rows] if table=='tasks' else rows),total
 def _task_shape(self,row:dict[str,Any])->dict[str,Any]:
  value=dict(row); dep=value.pop('dependency_task_id',None);value['dependency_ids']=[] if dep is None else [str(dep)];return value
 def _task_values(self,values:Mapping[str,object])->dict[str,object]:
  value=dict(values)
  if 'dependency_ids' in value:
   dependencies=value.pop('dependency_ids')
   # The deployed schema has one nullable dependency column.
   value['dependency_task_id']=int(dependencies[0]) if dependencies else None
  return value
 def create_task(self,user_id:Any,event_id:Any,values:Mapping[str,object])->dict[str,Any]:
  self.get_event(user_id,event_id);return self._task_shape(self._insert('tasks',{'event_id':event_id,**self._task_values(values)}))
 def get_task(self,user_id:Any,event_id:Any,task_id:Any)->dict[str,Any]: return self._core_item('tasks',user_id,event_id,task_id)
 def list_tasks(self,user_id:Any,event_id:Any)->list[dict[str,Any]]: return self._core_list('tasks',user_id,event_id)[0]
 def update_task(self,user_id:Any,event_id:Any,task_id:Any,values:Mapping[str,object])->dict[str,Any]:
  self.get_task(user_id,event_id,task_id);return self._task_shape(self._scoped_update('tasks',user_id,task_id,self._task_values(values),event_id))
 def delete_task(self,user_id:Any,event_id:Any,task_id:Any)->None: self._scoped_delete('tasks',user_id,event_id,task_id)
 def list_task_dependents(self,user_id:Any,event_id:Any,task_id:Any)->list[dict[str,Any]]:
  self.get_task(user_id,event_id,task_id)
  with self._cursor() as q:
   q.execute('SELECT t.* FROM tasks t JOIN events e ON e.id=t.event_id WHERE t.event_id=%s AND t.dependency_task_id=%s AND e.owner_id=%s',(event_id,task_id,user_id));return [self._task_shape(r) for r in self._rows(q)]
 def create_guest(self,user_id:Any,event_id:Any,values:Mapping[str,object])->dict[str,Any]:
  self.get_event(user_id,event_id);return self._insert('guests',{'event_id':event_id,**dict(values)})
 def get_guest(self,user_id:Any,event_id:Any,guest_id:Any)->dict[str,Any]: return self._core_item('guests',user_id,event_id,guest_id)
 def list_guests(self,user_id:Any,event_id:Any,limit:int,offset:int)->tuple[list[dict[str,Any]],int]: return self._core_list('guests',user_id,event_id,limit,offset)
 def update_guest(self,user_id:Any,event_id:Any,guest_id:Any,values:Mapping[str,object])->dict[str,Any]:
  self.get_guest(user_id,event_id,guest_id);return self._scoped_update('guests',user_id,guest_id,values,event_id)
 def delete_guest(self,user_id:Any,event_id:Any,guest_id:Any)->None: self._scoped_delete('guests',user_id,event_id,guest_id)
 def count_accepted_guests(self,user_id:Any,event_id:Any)->int:
  self.get_event(user_id,event_id)
  with self._cursor() as q:q.execute('SELECT COUNT(*) FROM guests WHERE event_id=%s AND status=%s',(event_id,'accepted'));return int(q.fetchone()[0])

 def _scoped_update(self,table:str,user_id:Any,item_id:Any,values:Mapping[str,object],event_id:Any|None=None)->dict[str,Any]:
  if not values: raise NotFoundError('no values supplied')
  clauses=','.join(f'{key}=%s' for key in values); params=list(values.values())+[item_id,user_id]
  predicate='id=%s AND owner_id=%s' if table=='events' else f'id=%s AND event_id=%s AND EXISTS (SELECT 1 FROM events e WHERE e.id={table}.event_id AND e.owner_id=%s)'
  if table!='events': params=[*values.values(),item_id,event_id,user_id]
  with self._cursor(write=True) as q:
   q.execute(f'UPDATE {table} SET {clauses} WHERE {predicate}',tuple(params))
  return self.get_event(user_id,item_id) if table=='events' else self._core_item(table,user_id,event_id,item_id)
 def _scoped_delete(self,table:str,user_id:Any,event_id:Any,item_id:Any)->None:
  self._core_item(table,user_id,event_id,item_id)
  with self._cursor(write=True) as q:q.execute(f'DELETE FROM {table} WHERE id=%s AND event_id=%s AND EXISTS (SELECT 1 FROM events e WHERE e.id={table}.event_id AND e.owner_id=%s)',(item_id,event_id,user_id))

 def audit(self,*args:Any,**kwargs:Any)->None:
  """Accept Core's positional audit port and Budget's named audit port."""
  if kwargs:
   event_id=kwargs['event_id']; user_id=kwargs['actor_id']; resource=kwargs['entity_type']; resource_id=kwargs['entity_id']; action=kwargs['action']; details=kwargs.get('details',{})
  else:
   user_id,action,resource,resource_id,details=args; event_id=details.get('event_id') or (resource_id if resource=='event' else None)
  if event_id is None:return
  with self._cursor(write=True) as q:q.execute('INSERT INTO audit_logs(event_id,actor_user_id,resource_type,resource_id,action,details) VALUES(%s,%s,%s,%s,%s,%s)',(event_id,user_id,resource,resource_id,action[:32],json.dumps(dict(details), default=str)))
 def notify(self,user_id:Any,kind:str,details:Mapping[str,object])->None:
  event_id=details.get('event_id') or details.get('id')
  if event_id is None:return
  source_id=details.get('id')
  with self._cursor(write=True) as q:
   q.execute('INSERT IGNORE INTO notifications(user_id,event_id,kind,title,source_type,source_id,source_state,message) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(user_id,event_id,kind[:64],kind[:255],'core',source_id,kind[:128],f'{kind}: {details.get("name") or details.get("title") or "resource"}'))

 # Legacy generic methods remain for unrelated route groups. ----------------
 def nested(self,table:str,user:int,event:int,item:int)->dict[str,Any]: return self._core_item(table,user,event,item)
 def list_nested(self,table:str,user:int,event:int,limit:int,offset:int)->tuple[list[dict[str,Any]],int]: return self._core_list(table,user,event,limit,offset)
 def _insert(self,table:str,data:Mapping[str,object])->dict[str,Any]:
  cols=list(data);sql=f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s']*len(cols))})"
  with self._cursor(write=True) as q:q.execute(sql,tuple(data.values()));new=q.lastrowid;q.execute(f'SELECT * FROM {table} WHERE id=%s',(new,));return self._one(q) or {}
 def _update(self,table:str,item:int,data:dict[str,Any])->dict[str,Any]:
  if not data:raise NotFoundError('no values supplied')
  with self._cursor(write=True) as q:q.execute(f"UPDATE {table} SET {','.join(f'{x}=%s' for x in data)} WHERE id=%s",(*data.values(),item));q.execute(f'SELECT * FROM {table} WHERE id=%s',(item,));return self._one(q) or {}
 def _delete(self,table:str,item:int)->None:
  with self._cursor(write=True) as q:q.execute(f'DELETE FROM {table} WHERE id=%s',(item,))

 # Budget repository port --------------------------------------------------
 def _budget_category(self,row:dict[str,Any])->BudgetCategoryRecord:
  return BudgetCategoryRecord(str(row['id']),str(row['event_id']),row['name'],Decimal(str(row['planned_amount'])),row.get('created_at'),row.get('updated_at'))
 def _budget_expense(self,row:dict[str,Any])->ExpenseRecord:
  return ExpenseRecord(str(row['id']),str(row['event_id']),str(row['budget_category_id']),row['name'],Decimal(str(row['amount'])),row.get('spent_on'),row.get('created_at'),row.get('updated_at'))
 def _budget_one(self,q:Any)->dict[str,Any]|None:
  row=q.fetchone(); return dict(zip(q.column_names,row)) if row else None
 def get_category(self,event_id:str,category_id:str)->BudgetCategoryRecord|None:
  with self._cursor() as q:q.execute('SELECT * FROM budget_categories WHERE id=%s AND event_id=%s',(category_id,event_id));row=self._budget_one(q)
  return self._budget_category(row) if row else None
 def list_categories(self,event_id:str)->list[BudgetCategoryRecord]:
  with self._cursor() as q:q.execute('SELECT * FROM budget_categories WHERE event_id=%s ORDER BY id',(event_id,));return [self._budget_category(dict(zip(q.column_names,row))) for row in q.fetchall()]
 def insert_category(self,category:BudgetCategoryRecord)->BudgetCategoryRecord:
  with self._cursor(write=True) as q:
   q.execute('INSERT INTO budget_categories(event_id,name,planned_amount) VALUES(%s,%s,%s)',(category.event_id,category.name,category.planned_amount)); new=q.lastrowid;q.execute('SELECT * FROM budget_categories WHERE id=%s',(new,));return self._budget_category(self._budget_one(q) or {})
 def update_category(self,category:BudgetCategoryRecord)->BudgetCategoryRecord:
  with self._cursor(write=True) as q:
   q.execute('UPDATE budget_categories SET name=%s,planned_amount=%s WHERE id=%s AND event_id=%s',(category.name,category.planned_amount,category.id,category.event_id));q.execute('SELECT * FROM budget_categories WHERE id=%s AND event_id=%s',(category.id,category.event_id));row=self._budget_one(q)
  if not row:raise NotFoundError('budget category was not found')
  return self._budget_category(row)
 def delete_category(self,event_id:str,category_id:str)->None:
  with self._cursor(write=True) as q:q.execute('DELETE FROM budget_categories WHERE id=%s AND event_id=%s',(category_id,event_id))
 def get_expense(self,event_id:str,expense_id:str)->ExpenseRecord|None:
  with self._cursor() as q:q.execute('SELECT x.*,c.event_id FROM expenses x JOIN budget_categories c ON c.id=x.budget_category_id WHERE x.id=%s AND c.event_id=%s',(expense_id,event_id));row=self._budget_one(q)
  return self._budget_expense(row) if row else None
 def list_expenses(self,event_id:str,category_id:str|None=None)->list[ExpenseRecord]:
  sql='SELECT x.*,c.event_id FROM expenses x JOIN budget_categories c ON c.id=x.budget_category_id WHERE c.event_id=%s';args:list[Any]=[event_id]
  if category_id is not None:sql+=' AND c.id=%s';args.append(category_id)
  with self._cursor() as q:q.execute(sql,tuple(args));return [self._budget_expense(dict(zip(q.column_names,row))) for row in q.fetchall()]
 def insert_expense(self,expense:ExpenseRecord)->ExpenseRecord:
  with self._cursor(write=True) as q:
   q.execute('INSERT INTO expenses(budget_category_id,name,amount,spent_on) VALUES(%s,%s,%s,%s)',(expense.category_id,expense.description,expense.actual_amount,expense.incurred_at or date.today()));new=q.lastrowid
  result=self.get_expense(expense.event_id,str(new))
  return result or expense
 def update_expense(self,expense:ExpenseRecord)->ExpenseRecord:
  with self._cursor(write=True) as q:q.execute('UPDATE expenses x JOIN budget_categories c ON c.id=x.budget_category_id SET x.budget_category_id=%s,x.name=%s,x.amount=%s,x.spent_on=%s WHERE x.id=%s AND c.event_id=%s',(expense.category_id,expense.description,expense.actual_amount,expense.incurred_at or date.today(),expense.id,expense.event_id))
  result=self.get_expense(expense.event_id,expense.id)
  if not result:raise NotFoundError('expense was not found')
  return result
 def delete_expense(self,event_id:str,expense_id:str)->None:
  with self._cursor(write=True) as q:q.execute('DELETE x FROM expenses x JOIN budget_categories c ON c.id=x.budget_category_id WHERE x.id=%s AND c.event_id=%s',(expense_id,event_id))
 def notify_spending_threshold_once(self,*,event_id:str,category_id:str,spent_amount:Decimal,planned_amount:Decimal,threshold:Decimal)->bool:
  key=f'budget:{event_id}:{category_id}:{threshold}'
  with self._cursor(write=True) as q:
   q.execute('INSERT IGNORE INTO notification_sources(source_key) VALUES(%s)',(key,))
   if q.rowcount != 1:return False
   q.execute('SELECT owner_id FROM events WHERE id=%s',(event_id,)); owner=q.fetchone()
   if not owner:return False
   q.execute('INSERT INTO notifications(user_id,event_id,kind,title,message,source_type,source_id,source_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(owner[0],event_id,'budget_threshold','Budget threshold reached',f'Category spending reached {threshold * 100}% of plan ({spent_amount}/{planned_amount}).','budget_category',category_id,str(threshold)))
   return True

 # Operations: schedule, vendors, and payments. ---------------------------
 def _owned_operations_row(self,table:str,user_id:Any,event_id:Any,row_id:Any)->dict[str,Any]|None:
  with self._cursor() as q:
   q.execute(f'SELECT r.* FROM {table} r JOIN events e ON e.id=r.event_id WHERE r.id=%s AND r.event_id=%s AND e.owner_id=%s',(row_id,event_id,user_id));return self._one(q)
 def list_schedule_items(self,user_id:Any,event_id:Any)->list[dict[str,Any]]:
  self.get_event(user_id,event_id)
  with self._cursor() as q:q.execute('SELECT * FROM schedule_items WHERE event_id=%s ORDER BY start_at,id',(event_id,));rows=self._rows(q)
  for row in rows: row['start_at']=datetime.fromisoformat(str(row['start_at']));row['end_at']=datetime.fromisoformat(str(row['end_at']))
  return rows
 def get_schedule_item(self,user_id:Any,event_id:Any,item_id:Any)->dict[str,Any]|None:
  row=self._owned_operations_row('schedule_items',user_id,event_id,item_id)
  if row: row['start_at']=datetime.fromisoformat(str(row['start_at']));row['end_at']=datetime.fromisoformat(str(row['end_at']))
  return row
 def create_schedule_item(self,event_id:Any,values:Mapping[str,object])->dict[str,Any]:return self._insert('schedule_items',{'event_id':event_id,**dict(values)})
 def update_schedule_item(self,event_id:Any,item_id:Any,values:Mapping[str,object])->dict[str,Any]:return self._update('schedule_items',item_id,dict(values))
 def delete_schedule_item(self,event_id:Any,item_id:Any)->None:self._delete('schedule_items',item_id)
 def list_vendors(self,user_id:Any,event_id:Any)->list[dict[str,Any]]:
  self.get_event(user_id,event_id)
  with self._cursor() as q:q.execute('SELECT * FROM vendors WHERE event_id=%s ORDER BY id',(event_id,));return self._rows(q)
 def get_vendor(self,user_id:Any,event_id:Any,vendor_id:Any)->dict[str,Any]|None:return self._owned_operations_row('vendors',user_id,event_id,vendor_id)
 def create_vendor(self,event_id:Any,values:Mapping[str,object])->dict[str,Any]:return self._insert('vendors',{'event_id':event_id,**dict(values)})
 def update_vendor(self,event_id:Any,vendor_id:Any,values:Mapping[str,object])->dict[str,Any]:return self._update('vendors',vendor_id,dict(values))
 def delete_vendor(self,event_id:Any,vendor_id:Any)->None:self._delete('vendors',vendor_id)
 def vendor_paid_total(self,vendor_id:Any,*,exclude_payment_id:Any=None)->Decimal:
  sql='SELECT COALESCE(SUM(amount),0) FROM vendor_payments WHERE vendor_id=%s';params:list[Any]=[vendor_id]
  if exclude_payment_id is not None:sql+=' AND id<>%s';params.append(exclude_payment_id)
  with self._cursor() as q:q.execute(sql,tuple(params));return Decimal(str(q.fetchone()[0]))
 def list_vendor_payments(self,user_id:Any,event_id:Any,vendor_id:Any)->list[dict[str,Any]]:
  if not self.get_vendor(user_id,event_id,vendor_id):return []
  with self._cursor() as q:q.execute('SELECT * FROM vendor_payments WHERE vendor_id=%s ORDER BY paid_on,id',(vendor_id,));return self._rows(q)
 def get_vendor_payment(self,user_id:Any,event_id:Any,vendor_id:Any,payment_id:Any)->dict[str,Any]|None:
  if not self.get_vendor(user_id,event_id,vendor_id):return None
  with self._cursor() as q:q.execute('SELECT * FROM vendor_payments WHERE id=%s AND vendor_id=%s',(payment_id,vendor_id));return self._one(q)
 def create_vendor_payment(self,vendor_id:Any,values:Mapping[str,object])->dict[str,Any]:return self._insert('vendor_payments',{'vendor_id':vendor_id,**dict(values)})
 def update_vendor_payment(self,vendor_id:Any,payment_id:Any,values:Mapping[str,object])->dict[str,Any]:return self._update('vendor_payments',payment_id,dict(values))
 def delete_vendor_payment(self,vendor_id:Any,payment_id:Any)->None:self._delete('vendor_payments',payment_id)
 def record_audit(self,*,user_id:Any,event_id:Any,entity_type:str,entity_id:int,action:str,details:Mapping[str,object]|None=None)->None:
  with self._cursor(write=True) as q:q.execute('INSERT INTO audit_logs(event_id,actor_user_id,resource_type,resource_id,action,details) VALUES(%s,%s,%s,%s,%s,%s)',(event_id,user_id,entity_type,entity_id,action,json.dumps(dict(details or {}),default=str)))

 # Notification/audit repository port -------------------------------------
 @staticmethod
 def _as_datetime(value:Any)->datetime|None:
  if value is None or isinstance(value,datetime):return value
  return datetime.fromisoformat(str(value).replace('Z','+00:00'))
 def _notification_dto(self,row:dict[str,Any])->dict[str,Any]:
  result={'id':str(row['id']),'recipient_id':str(row['user_id']),'kind':row['kind'],'title':row['title'],'message':row['message'],'is_read':bool(row['is_read']),'created_at':self._as_datetime(row['created_at'])}
  if row.get('read_at') is not None:result['read_at']=self._as_datetime(row['read_at'])
  if row.get('source_type') == 'task':result['task_id']=None if row.get('source_id') is None else str(row['source_id'])
  if row.get('event_id') is not None:result['event_id']=str(row['event_id'])
  return result
 def list_notifications_for_recipient(self,recipient_id:str,*,limit:int,offset:int)->dict[str,Any]:
  with self._cursor() as q:
   q.execute('SELECT COUNT(*) FROM notifications WHERE user_id=%s',(recipient_id,));total=int(q.fetchone()[0])
   q.execute('SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',(recipient_id,limit,offset));items=[self._notification_dto(row) for row in self._rows(q)]
  return {'items':items,'total':total,'limit':limit,'offset':offset}
 def get_notification_for_recipient(self,recipient_id:str,notification_id:str)->dict[str,Any]|None:
  with self._cursor() as q:q.execute('SELECT * FROM notifications WHERE id=%s AND user_id=%s',(notification_id,recipient_id));row=self._one(q)
  return self._notification_dto(row) if row else None
 def mark_notification_read_for_recipient(self,recipient_id:str,notification_id:str,*,read_at:datetime)->dict[str,Any]|None:
  with self._cursor(write=True) as q:
   q.execute('UPDATE notifications SET is_read=TRUE,read_at=%s WHERE id=%s AND user_id=%s',(read_at,notification_id,recipient_id))
   if q.rowcount != 1:return None
   q.execute('SELECT * FROM notifications WHERE id=%s AND user_id=%s',(notification_id,recipient_id));row=self._one(q)
  return self._notification_dto(row) if row else None
 def delete_notification_for_recipient(self,recipient_id:str,notification_id:str)->bool:
  with self._cursor(write=True) as q:q.execute('DELETE FROM notifications WHERE id=%s AND user_id=%s',(notification_id,recipient_id));return q.rowcount == 1
 def _audit_dto(self,row:dict[str,Any])->dict[str,Any]:
  details=row.get('details')
  if isinstance(details,str):
   try:details=json.loads(details)
   except json.JSONDecodeError:details={}
  result={'id':str(row['id']),'owner_id':str(row['owner_id']),'action':row['action'],'entity_type':row.get('resource_type') or 'unknown','entity_id':str(row.get('resource_id') or ''),'occurred_at':self._as_datetime(row['created_at']),'actor_id':None if row.get('actor_user_id') is None else str(row['actor_user_id'])}
  if isinstance(details,dict):result['details']=details
  return result
 def list_audit_logs_for_owner(self,owner_id:str,*,limit:int,offset:int)->dict[str,Any]:
  join=' FROM audit_logs a JOIN events e ON e.id=a.event_id WHERE e.owner_id=%s'
  with self._cursor() as q:
   q.execute('SELECT COUNT(*)'+join,(owner_id,));total=int(q.fetchone()[0])
   q.execute('SELECT a.*,e.owner_id AS owner_id'+join+' ORDER BY a.created_at DESC,a.id DESC LIMIT %s OFFSET %s',(owner_id,limit,offset));items=[self._audit_dto(row) for row in self._rows(q)]
  return {'items':items,'total':total,'limit':limit,'offset':offset}
 def _due_task_dto(self,row:dict[str,Any])->dict[str,Any]:
  return {'id':str(row['id']),'recipient_id':str(row['recipient_id']),'title':row['title'],'due_at':self._as_datetime(row['due_at']),'event_id':str(row['event_id'])}
 def list_tasks_due_between(self,*,starts_at:datetime,ends_at:datetime)->list[dict[str,Any]]:
  sql="SELECT t.*,e.owner_id AS recipient_id FROM tasks t JOIN events e ON e.id=t.event_id WHERE t.due_at IS NOT NULL AND t.due_at >= %s AND t.due_at <= %s AND (t.status IS NULL OR t.status NOT IN ('completed','cancelled','done'))"
  with self._cursor() as q:q.execute(sql,(starts_at,ends_at));return [self._due_task_dto(row) for row in self._rows(q)]
 def list_overdue_tasks(self,*,as_of:datetime)->list[dict[str,Any]]:
  sql="SELECT t.*,e.owner_id AS recipient_id FROM tasks t JOIN events e ON e.id=t.event_id WHERE t.due_at IS NOT NULL AND t.due_at < %s AND (t.status IS NULL OR t.status NOT IN ('completed','cancelled','done'))"
  with self._cursor() as q:q.execute(sql,(as_of,));return [self._due_task_dto(row) for row in self._rows(q)]
 def create_notification_for_new_source(self,notification:Mapping[str,object])->dict[str,Any]|None:
  # INSERT IGNORE is the source-state claim: its unique primary key makes the
  # claim and notification insert safe across concurrent scheduler workers.
  with self._cursor(write=True) as q:
   q.execute('INSERT IGNORE INTO notification_sources(source_key) VALUES(%s)',(notification['source_key'],))
   if q.rowcount != 1:return None
   q.execute('INSERT INTO notifications(user_id,event_id,kind,title,message,source_type,source_id,source_state,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(notification['recipient_id'],notification.get('event_id'),notification['kind'],notification['title'],notification['message'],'task',notification['task_id'],notification['source_key'],notification['created_at']))
   new=q.lastrowid;q.execute('SELECT * FROM notifications WHERE id=%s',(new,));row=self._one(q)
  return self._notification_dto(row) if row else None
