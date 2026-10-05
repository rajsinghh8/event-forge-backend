from __future__ import annotations
from eventforge.handlers.base import AuthenticatedHandler
from eventforge.validation import pagination
class EventsHandler(AuthenticatedHandler):
 async def get(self):l,o=pagination(self.request.arguments);self.write_json(self.service.list_events(self.user_id,l,o))
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
   self.write_json(self.service.list_tasks(self.user_id,event) if item_id is None else self.service.task(self.user_id,event,int(item_id)));return
  if self.table=='guests':
   if item_id is None:
    limit,offset=pagination(self.request.arguments);self.write_json(self.service.list_guests(self.user_id,event,limit,offset))
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
