from __future__ import annotations
from eventforge.handlers.base import AuthenticatedHandler
from eventforge.validation import pagination, query_options

def _query_page(rows, limit, offset, query):
 sort=query.pop('sort'); text=query.get('text','').lower(); result=[]
 for row in rows:
  if text and text not in str(row.get('name',row.get('title',''))).lower():continue
  if any(str(row.get(key)) != str(value) for key,value in query.items() if key not in {'text','startDate','endDate'}):continue
  # Task due dates and schedule-like dates use inclusive ISO date boundaries.
  date_value=str(row.get('due_at',row.get('start_date','')))
  if query.get('startDate') and date_value[:10] < query['startDate']:continue
  if query.get('endDate') and date_value[:10] > query['endDate']:continue
  result.append(row)
 field=sort.lstrip('-');result.sort(key=lambda row:(row.get(field) is None,row.get(field)),reverse=sort.startswith('-'))
 return {'items':result[offset:offset+limit],'total':len(result),'limit':limit,'offset':offset}

class EventsHandler(AuthenticatedHandler):
 async def get(self):
  l,o=pagination(self.request.arguments); query=query_options(self.request.arguments,allowed_sort={'id','name','start_date','created_at'},allowed_filters={'text','startDate','endDate'},default_sort='-id');sort=query.pop('sort')
  self.write_json(self.service.list_events(self.user_id,l,o,query,sort))
 async def post(self):self.write_json(self.service.create_event(self.user_id,self.body()),201)
class EventHandler(AuthenticatedHandler):
 async def get(self,event_id):self.write_json(self.service.event(self.user_id,int(event_id)))
 async def put(self,event_id):self.write_json(self.service.update_event(self.user_id,int(event_id),self.body()))
 async def delete(self,event_id):self.service.delete_event(self.user_id,int(event_id));self.set_status(204);self.finish()
class NestedHandler(AuthenticatedHandler):
 def initialize(self,service,settings,table):super().initialize(service,settings);self.table=table
 async def get(self,event_id,item_id=None):
  event=int(event_id)
  if self.table=='tasks':
   if item_id is None:
    l,o=pagination(self.request.arguments);query=query_options(self.request.arguments,allowed_sort={'id','title','due_at','priority','status'},allowed_filters={'text','status','priority','startDate','endDate'},default_sort='-id');rows=self.service.list_tasks(self.user_id,event);self.write_json(_query_page(rows,l,o,query));return
   self.write_json(self.service.task(self.user_id,event,int(item_id)));return
  if self.table=='guests':
   if item_id is None:
    limit,offset=pagination(self.request.arguments);query=query_options(self.request.arguments,allowed_sort={'id','name','status'},allowed_filters={'text','name','status'},default_sort='-id');result=self.service.list_guests(self.user_id,event,100,0);self.write_json(_query_page(result['items'],limit,offset,query))
   else:self.write_json(self.service.guest(self.user_id,event,int(item_id)))
   return
  if item_id is None:l,o=pagination(self.request.arguments);self.write_json(self.service.nested_list(self.table,self.user_id,event,l,o))
  else:self.write_json(self.service.nested_get(self.table,self.user_id,event,int(item_id)))
 async def post(self,event_id,item_id=None):
  event=int(event_id);body=self.body()
  if self.table=='tasks':self.write_json(self.service.create_task(self.user_id,event,body),201);return
  if self.table=='guests':self.write_json(self.service.create_guest(self.user_id,event,body),201);return
  self.write_json(self.service.nested_create(self.table,self.user_id,event,body),201)
 async def put(self,event_id,item_id):
  event=int(event_id);item=int(item_id);body=self.body()
  if self.table=='tasks':self.write_json(self.service.update_task(self.user_id,event,item,body));return
  if self.table=='guests':self.write_json(self.service.update_guest(self.user_id,event,item,body));return
  self.write_json(self.service.nested_update(self.table,self.user_id,event,item,body))
 async def delete(self,event_id,item_id):
  event=int(event_id);item=int(item_id)
  if self.table=='tasks':self.service.delete_task(self.user_id,event,item)
  elif self.table=='guests':self.service.delete_guest(self.user_id,event,item)
  else:self.service.nested_delete(self.table,self.user_id,event,item)
  self.set_status(204);self.finish()
