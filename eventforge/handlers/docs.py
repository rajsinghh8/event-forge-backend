from __future__ import annotations

from eventforge.handlers.base import AuthenticatedHandler, BaseHandler
from eventforge.openapi import build_openapi


class OpenApiHandler(AuthenticatedHandler):
 async def get(self):
  # Resolve the principal even though the document itself is not user-specific.
  # AuthenticatedHandler deliberately validates lazily through ``user_id``.
  self.user_id
  self.write_json(build_openapi())


class DocsHandler(AuthenticatedHandler):
 async def get(self):
  self.user_id
  self.set_header('Content-Type', 'text/html')
  self.finish('<!doctype html><html><body><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui",persistAuthorization:true})</script></body></html>')


class HealthHandler(BaseHandler):
 async def get(self):
  self.write_json({'status': 'ok'})


__all__ = ['DocsHandler', 'HealthHandler', 'OpenApiHandler']

