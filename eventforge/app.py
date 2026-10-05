from __future__ import annotations
import tornado.web
from eventforge.config import Settings,load_settings
from eventforge.db import Database
from eventforge.repositories import Repository
from eventforge.routes import routes
from eventforge.scheduler import NotificationScheduler
from eventforge.services import EventForgeService
def create_application(settings:Settings|None=None)->tornado.web.Application:
 settings=settings or load_settings();db=Database(settings);db.initialize_schema();service=EventForgeService(Repository(db),settings);app=tornado.web.Application(routes(service,settings));app.scheduler=NotificationScheduler(service);app.scheduler.start();return app
