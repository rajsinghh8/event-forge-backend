from __future__ import annotations
from eventforge.handlers.base import AuthenticatedHandler
from eventforge.errors import NotFoundError
class NotificationsHandler(AuthenticatedHandler):
 async def get(self,notification_id=None):raise NotFoundError('notification was not found')
 async def put(self,notification_id):raise NotFoundError('notification was not found')
 async def delete(self,notification_id):raise NotFoundError('notification was not found')
