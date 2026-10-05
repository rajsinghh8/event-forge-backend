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
  if item_id is None:l,o=pagination(self.request.arguments);self.write_json(self.service.nested_list(self.table,self.user_id,int(event_id),l,o))
  else:self.write_json(self.service.nested_get(self.table,self.user_id,int(event_id),int(item_id)))
 async def post(self,event_id,item_id=None):self.write_json(self.service.nested_create(self.table,self.user_id,int(event_id),self.body()),201)
 async def put(self,event_id,item_id):self.write_json(self.service.nested_update(self.table,self.user_id,int(event_id),int(item_id),self.body()))
 async def delete(self,event_id,item_id):self.service.nested_delete(self.table,self.user_id,int(event_id),int(item_id));self.set_status(204);self.finish()
