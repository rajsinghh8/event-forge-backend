import unittest
from datetime import datetime, timedelta

from eventforge.errors import NotFoundError, ValidationError
from eventforge.resource_services.notifications import NotificationResourceService


class FakeNotificationRepository:
 def __init__(self):
  self.created=[];self.notifications={'1':{'id':'1','recipient_id':'7','is_read':False}}
 def list_notifications_for_recipient(self,recipient_id,*,limit,offset):return {'items':[],'total':0,'limit':limit,'offset':offset}
 def get_notification_for_recipient(self,recipient_id,notification_id):return self.notifications.get(str(notification_id)) if recipient_id == 7 else None
 def mark_notification_read_for_recipient(self,recipient_id,notification_id,*,read_at):
  item=self.get_notification_for_recipient(recipient_id,notification_id)
  if item:item={'id':item['id'],'recipient_id':'7','is_read':True,'read_at':read_at}
  return item
 def delete_notification_for_recipient(self,recipient_id,notification_id):return recipient_id == 7 and str(notification_id) in self.notifications
 def list_audit_logs_for_owner(self,owner_id,*,limit,offset):return {'items':[],'total':0,'limit':limit,'offset':offset}
 def list_audit_logs_for_event_owner(self,owner_id,event_id,*,limit,offset):
  if (owner_id,event_id) != ('7','3'): raise NotFoundError('event not found')
  return {'items':[{'id':'1','event_id':'3'}],'total':1,'limit':limit,'offset':offset}
 def list_tasks_due_between(self,*,starts_at,ends_at):return [{'id':'11','recipient_id':'7','title':'Book hall','due_at':ends_at,'event_id':'3'}]
 def list_overdue_tasks(self,*,as_of):return [{'id':'12','recipient_id':'7','title':'Send invites','due_at':as_of-timedelta(seconds=1),'event_id':'3'}]
 def create_notification_for_new_source(self,notification):
  if notification['source_key'] in {n['source_key'] for n in self.created}:return None
  self.created.append(notification);return notification


class NotificationResourceServiceTests(unittest.TestCase):
 def setUp(self):self.repository=FakeNotificationRepository();self.service=NotificationResourceService(self.repository)
 def test_scan_creates_distinct_idempotent_due_and_overdue_sources(self):
  now=datetime(2025,1,1,10)
  result=self.service.scan_due_task_notifications(scanned_at=now)
  self.assertEqual((result['scanned_due_soon'],result['scanned_overdue'],result['created_due_soon'],result['created_overdue']),(1,1,1,1))
  self.assertEqual({n['source_key'] for n in self.repository.created},{'task_due_soon:task:11','task_overdue:task:12'})
  self.assertEqual(self.service.scan_due_task_notifications(scanned_at=now)['created_due_soon'],0)
 def test_recipient_scope_and_pagination_are_enforced(self):
  with self.assertRaises(NotFoundError):self.service.get_notification(8,'1')
  with self.assertRaises(ValidationError):self.service.list_notifications(7,limit=101)
  self.assertTrue(self.service.mark_notification_read(7,'1',read_at=datetime.now())['is_read'])
 def test_event_audit_list_is_event_and_owner_scoped(self):
  page=self.service.list_event_audit_logs('7','3',limit=20,offset=0)
  self.assertEqual(page['items'][0]['event_id'],'3')
  with self.assertRaises(NotFoundError):self.service.list_event_audit_logs('8','3',limit=20,offset=0)

if __name__ == '__main__':unittest.main()
