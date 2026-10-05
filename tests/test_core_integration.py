import unittest
from contextlib import contextmanager
from eventforge.errors import ConflictError
from eventforge.resource_services.core import CoreResourceService

class MemoryCoreRepository:
 def __init__(self):self.events={1:{'id':1,'capacity':1}};self.guests={};self.audits=[];self.notifications=[];self.commits=0
 @contextmanager
 def transaction(self):
  try:yield
  except:raise
  else:self.commits+=1
 def get_event(self,u,e):return self.events[int(e)]
 def list_events(self,u,limit,offset):return list(self.events.values()),1
 def create_event(self,u,v):return {'id':2,**v}
 def update_event(self,u,e,v):self.events[int(e)].update(v);return self.events[int(e)]
 def delete_event(self,u,e):del self.events[int(e)]
 def create_task(self,*a):return {'id':1,'event_id':a[1],**a[2]}
 def get_task(self,*a):return {'id':a[2],'event_id':a[1],'status':'pending','dependency_ids':[]}
 def list_tasks(self,*a):return []
 def update_task(self,*a):return {'id':a[2],'event_id':a[1],**a[3]}
 def delete_task(self,*a):pass
 def list_task_dependents(self,*a):return []
 def create_guest(self,u,e,v):
  i=len(self.guests)+1;self.guests[i]={'id':i,'event_id':e,**v};return self.guests[i]
 def get_guest(self,u,e,i):return self.guests[int(i)]
 def list_guests(self,u,e,limit,offset):return list(self.guests.values()),len(self.guests)
 def update_guest(self,u,e,i,v):self.guests[int(i)].update(v);return self.guests[int(i)]
 def delete_guest(self,u,e,i):del self.guests[int(i)]
 def count_accepted_guests(self,u,e):return sum(g.get('status')=='accepted' for g in self.guests.values())
 def audit(self,*args):self.audits.append(args)
 def notify(self,*args):self.notifications.append(args)

class CoreIntegrationTests(unittest.TestCase):
 def test_guest_mutation_is_audited_notified_and_capacity_scoped(self):
  repository=MemoryCoreRepository();service=CoreResourceService(repository)
  guest=service.create_guest(9,1,{'name':'A','status':'accepted'})
  self.assertEqual(guest['id'],1);self.assertEqual(repository.commits,1)
  self.assertEqual(len(repository.audits),1);self.assertEqual(len(repository.notifications),1)
  with self.assertRaises(ConflictError):service.create_guest(9,1,{'name':'B','status':'accepted'})
