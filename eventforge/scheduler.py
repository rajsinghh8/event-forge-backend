from __future__ import annotations
import logging
import tornado.ioloop
LOGGER=logging.getLogger(__name__)
class NotificationScheduler:
 def __init__(self,service):self._service=service;self._callback=tornado.ioloop.PeriodicCallback(self._scan,60000)
 def start(self):self._callback.start()
 def stop(self):self._callback.stop()
 async def _scan(self):
  try:
   result=self._service.scan_notifications()
   LOGGER.debug('notification scan completed: %s',result)
  except Exception:
   # A failed database scan must not terminate the recurring callback.
   LOGGER.exception('notification scan failed')
