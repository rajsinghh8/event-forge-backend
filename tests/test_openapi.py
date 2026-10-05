import inspect
import unittest

from eventforge.handlers.base import AuthenticatedHandler, BaseHandler
from eventforge.handlers.docs import DocsHandler, HealthHandler, OpenApiHandler
from eventforge.openapi import PATHS, build_openapi


class OpenApiTests(unittest.TestCase):
 def test_complete_route_and_method_coverage(self):
  spec = build_openapi()
  self.assertEqual(set(spec['paths']), set(PATHS))
  self.assertEqual(
   {path: set(item) for path, item in spec['paths'].items()},
   {path: set(methods) for path, methods in PATHS.items()},
  )

 def test_docs_and_openapi_are_bearer_protected_but_health_is_public(self):
  spec = build_openapi()
  self.assertTrue(issubclass(OpenApiHandler, AuthenticatedHandler))
  self.assertTrue(issubclass(DocsHandler, AuthenticatedHandler))
  self.assertTrue(issubclass(HealthHandler, BaseHandler))
  self.assertNotIn('security', spec['paths']['/health']['get'])
  for path in ('/docs', '/openapi.json'):
   self.assertEqual(spec['paths'][path]['get']['security'], [{'bearerAuth': []}])
  self.assertIn('self.user_id', inspect.getsource(OpenApiHandler.get))
  self.assertIn('self.user_id', inspect.getsource(DocsHandler.get))
  self.assertEqual(spec['components']['securitySchemes']['bearerAuth']['scheme'], 'bearer')

 def test_canonical_nested_budget_and_expense_contract(self):
  paths = build_openapi()['paths']
  budget = '/api/events/{eventId}/budget-categories/{categoryId}/budget'
  expenses = '/api/events/{eventId}/budget-categories/{categoryId}/expenses'
  expense = expenses + '/{expenseId}'
  self.assertEqual(set(paths[budget]), {'get'})
  self.assertEqual(set(paths[expenses]), {'get', 'post'})
  self.assertEqual(set(paths[expense]), {'get', 'put', 'delete'})
  create = paths[expenses]['post']
  self.assertEqual(create['requestBody']['content']['application/json']['schema']['$ref'], '#/components/schemas/ExpenseInput')
  self.assertEqual(create['responses']['201']['content']['application/json']['schema']['$ref'], '#/components/schemas/Expense')

 def test_expense_event_count_and_strict_query_documentation(self):
  spec = build_openapi()
  schemas = spec['components']['schemas']
  expense = schemas['ExpenseInput']
  self.assertEqual(expense['required'], ['name', 'amount', 'spent_on'])
  self.assertEqual(set(expense['properties']), {'name', 'amount', 'spent_on', 'notes'})
  self.assertTrue(expense['properties']['notes']['nullable'])
  event = schemas['Event']['allOf'][1]
  self.assertIn('accepted_guest_count', event['required'])
  self.assertEqual(event['properties']['accepted_guest_count']['minimum'], 0)
  parameters = {item['name']: item for item in spec['paths']['/api/events']['get']['parameters']}
  self.assertEqual(set(parameters), {'page', 'size', 'filter', 'sort'})
  self.assertEqual(parameters['page']['schema']['minimum'], 1)
  self.assertEqual(parameters['size']['schema']['maximum'], 100)
  self.assertIn('allowlisted', parameters['sort']['description'])

 def test_error_envelope_is_reusable(self):
  spec = build_openapi()
  self.assertEqual(spec['components']['schemas']['Error']['required'], ['timestamp', 'status', 'error', 'message', 'path'])
  self.assertIn('422', spec['paths']['/api/events/{eventId}/budget-categories/{categoryId}/expenses']['post']['responses'])
  self.assertIn('409', spec['paths']['/api/events/{eventId}/budget-categories/{categoryId}/expenses']['post']['responses'])
