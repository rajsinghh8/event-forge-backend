from __future__ import annotations
from decimal import Decimal
from typing import Any
from eventforge.db import Database
from eventforge.errors import NotFoundError
class Repository:
 def __init__(self, db: Database)->None:self._db=db
 def _one(self, cursor: Any)->dict[str,Any]|None:
  row=cursor.fetchone(); return dict(zip(cursor.column_names,row)) if row else None
 def create_user(self,email:str,password_hash:str)->dict[str,Any]:
  with self._db.transaction() as c:
   q=c.cursor();q.execute('INSERT INTO users(email,password_hash) VALUES(%s,%s)',(email,password_hash));q.execute('SELECT id,email,created_at FROM users WHERE id=%s',(q.lastrowid,));return self._one(q) or {}
 def user_by_email(self,email:str)->dict[str,Any]|None:
  with self._db.connection() as c:q=c.cursor();q.execute('SELECT * FROM users WHERE email=%s',(email,));return self._one(q)
 def event(self,user:int,event:int)->dict[str,Any]:
  with self._db.connection() as c:q=c.cursor();q.execute('SELECT * FROM events WHERE id=%s AND owner_id=%s',(event,user));row=self._one(q)
  if not row:raise NotFoundError('event was not found')
  return row
 def list_events(self,user:int,limit:int,offset:int)->tuple[list[dict[str,Any]],int]:
  with self._db.connection() as c:
   q=c.cursor();q.execute('SELECT COUNT(*) FROM events WHERE owner_id=%s',(user,));total=q.fetchone()[0];q.execute('SELECT * FROM events WHERE owner_id=%s ORDER BY id DESC LIMIT %s OFFSET %s',(user,limit,offset));return [dict(zip(q.column_names,r)) for r in q.fetchall()],total
 def create_event(self,user:int,data:dict[str,Any])->dict[str,Any]:return self._insert('events',{'owner_id':user,**data})
 def update_event(self,user:int,event:int,data:dict[str,Any])->dict[str,Any]:self.event(user,event);return self._update('events',event,data)
 def delete_event(self,user:int,event:int)->None:self.event(user,event);self._delete('events',event)
 def nested(self,table:str,user:int,event:int,item:int)->dict[str,Any]:
  self.event(user,event)
  with self._db.connection() as c:
   q=c.cursor();q.execute(f'SELECT * FROM {table} WHERE id=%s AND event_id=%s',(item,event));row=self._one(q)
  if not row:raise NotFoundError(f'{table} resource was not found')
  return row
 def list_nested(self,table:str,user:int,event:int,limit:int,offset:int)->tuple[list[dict[str,Any]],int]:
  self.event(user,event)
  with self._db.connection() as c:
   q=c.cursor();q.execute(f'SELECT COUNT(*) FROM {table} WHERE event_id=%s',(event,));total=q.fetchone()[0];q.execute(f'SELECT * FROM {table} WHERE event_id=%s ORDER BY id DESC LIMIT %s OFFSET %s',(event,limit,offset));return [dict(zip(q.column_names,r)) for r in q.fetchall()],total
 def _insert(self,table:str,data:dict[str,Any])->dict[str,Any]:
  cols=list(data); sql=f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s']*len(cols))})"
  with self._db.transaction() as c:q=c.cursor();q.execute(sql,tuple(data.values()));new=q.lastrowid;q.execute(f'SELECT * FROM {table} WHERE id=%s',(new,));return self._one(q) or {}
 def _update(self,table:str,item:int,data:dict[str,Any])->dict[str,Any]:
  if not data:raise NotFoundError('no values supplied')
  with self._db.transaction() as c:q=c.cursor();q.execute(f"UPDATE {table} SET {','.join(f'{x}=%s' for x in data)} WHERE id=%s",(*data.values(),item));q.execute(f'SELECT * FROM {table} WHERE id=%s',(item,));return self._one(q) or {}
 def _delete(self,table:str,item:int)->None:
  with self._db.transaction() as c:c.cursor().execute(f'DELETE FROM {table} WHERE id=%s',(item,))
