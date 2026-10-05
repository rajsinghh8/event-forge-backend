from __future__ import annotations
from eventforge.handlers.base import AuthenticatedHandler
from eventforge.validation import pagination

class NotificationsHandler(AuthenticatedHandler):
 async def get(self,notification_id=None):
  if notification_id is None:
   limit,offset=pagination(self.request.arguments);self.write_json(self.service.list_notifications(self.user_id,limit,offset))
  else:self.write_json(self.service.notification(self.user_id,int(notification_id)))
 async def put(self,notification_id):self.write_json(self.service.mark_notification_read(self.user_id,int(notification_id)))
 async def delete(self,notification_id):
  self.service.delete_notification(self.user_id,int(notification_id));self.set_status(204);self.finish()

class AuditLogsHandler(AuthenticatedHandler):
 async def get(self,event_id):
  limit,offset=pagination(self.request.arguments);self.write_json(self.service.list_audit_logs(self.user_id,int(event_id),limit,offset))
