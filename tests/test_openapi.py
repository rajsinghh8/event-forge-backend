import unittest

from eventforge.handlers.base import BaseHandler
from eventforge.handlers.docs import DocsHandler, OpenApiHandler
from eventforge.openapi import PATHS, build_openapi


class OpenApiTests(unittest.TestCase):
 def test_complete_route_and_method_coverage(self):
  spec = build_openapi()
  self.assertEqual(set(spec['paths']), set(PATHS))
  self.assertEqual({path: set(item) for path, item in spec['paths'].items()}, {path: set(methods) for path, methods in PATHS.items()})

 def test_public_deployment_routes_and_bearer_security(self):
  spec = build_openapi()
  self.assertTrue(issubclass(OpenApiHandler, BaseHandler))
  self.assertTrue(issubclass(DocsHandler, BaseHandler))
  for path in ('/health', '/docs', '/openapi.json', '/api/auth/register', '/api/auth/login'):
   self.assertNotIn('security', spec['paths'][path]['get' if path in ('/health', '/docs', '/openapi.json') else 'post'])
  self.assertEqual(spec['components']['securitySchemes']['bearerAuth']['scheme'], 'bearer')
  self.assertEqual(spec['paths']['/api/events']['get']['security'], [{'bearerAuth': []}])

 def test_real_budget_aliases_and_audit_path_are_advertised(self):
  paths = build_openapi()['paths']
  self.assertIn('/api/events/{eventId}/budget/categories', paths)
  self.assertIn('/api/events/{eventId}/budget-categories', paths)
  self.assertIn('/api/events/{eventId}/expenses', paths)
  self.assertIn('/api/audit-logs', paths)
  self.assertIn('/api/events/{eventId}/audit-logs', paths)
  self.assertEqual({'eventId', 'limit', 'offset'}, {parameter['name'] for parameter in paths['/api/events/{eventId}/audit-logs']['get']['parameters']})
  self.assertNotIn('/api/events/{eventId}/budget-categories/{categoryId}/expenses', paths)

 def test_contract_includes_bodies_parameters_and_error_envelopes(self):
  spec = build_openapi()
  create_expense = spec['paths']['/api/events/{eventId}/expenses']['post']
  self.assertEqual(create_expense['responses']['201']['content']['application/json']['schema']['$ref'], '#/components/schemas/Expense')
  self.assertIn('requestBody', create_expense)
  list_expenses = spec['paths']['/api/events/{eventId}/expenses']['get']
  self.assertIn('category_id', {parameter['name'] for parameter in list_expenses['parameters']})
  list_events = spec['paths']['/api/events']['get']
  self.assertEqual({'limit', 'offset'}, {parameter['name'] for parameter in list_events['parameters']})
  self.assertIn('422', create_expense['responses'])
  self.assertIn('409', create_expense['responses'])
  self.assertEqual(spec['components']['schemas']['Error']['required'], ['timestamp', 'status', 'error', 'message', 'path'])
