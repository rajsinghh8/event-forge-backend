from __future__ import annotations
import logging
from typing import Any
import tornado.web
from eventforge.errors import ApiError,ValidationError,write_error_response
from eventforge.security import authenticated_user_id
from eventforge.validation import json_body
LOGGER=logging.getLogger(__name__)
class BaseHandler(tornado.web.RequestHandler):
 def initialize(self,service:Any,settings:Any)->None:self.service=service;self.settings=settings
 def set_default_headers(self)->None:self.set_header('Content-Type','application/json')
 def write_json(self,value:Any,status:int=200)->None:self.set_status(status);self.finish(value)
 def write_error(self,status_code:int,**kwargs:Any)->None:
  exc=kwargs.get('exc_info',(None,None,None))[1]
  if isinstance(exc,ApiError):write_error_response(self,exc)
  else:
   LOGGER.exception('Unhandled request error path=%s',self.request.path,exc_info=exc);write_error_response(self,ApiError('internal server error'))
 def body(self)->dict[str,Any]:return json_body(self.request.body)
class AuthenticatedHandler(BaseHandler):
 @property
 def user_id(self)->int:return authenticated_user_id(self)
