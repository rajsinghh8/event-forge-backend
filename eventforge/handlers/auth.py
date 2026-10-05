from __future__ import annotations
from eventforge.handlers.base import BaseHandler
class RegisterHandler(BaseHandler):
 async def post(self)->None:self.write_json(self.service.register(self.body()),201)
class LoginHandler(BaseHandler):
 async def post(self)->None:self.write_json(self.service.login(self.body()))
