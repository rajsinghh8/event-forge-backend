import unittest
from eventforge.openapi import build_openapi,PATHS
class OpenApiTests(unittest.TestCase):
 def test_complete_declared_coverage(self):self.assertEqual(set(build_openapi()['paths']),set(PATHS))
 def test_auth_and_security(self):
  spec=build_openapi();self.assertIn('/api/auth/register',spec['paths']);self.assertIn('/api/auth/login',spec['paths']);self.assertNotIn('security',spec['paths']['/api/auth/login']['post']);self.assertEqual(spec['paths']['/api/events']['get']['security'],[{'bearerAuth':[]}])
 def test_docs_and_nested_routes(self):
  paths=build_openapi()['paths'];self.assertIn('/openapi.json',paths);self.assertIn('/docs',paths);self.assertIn('/api/events/{eventId}/budget-categories/{categoryId}/expenses/{expenseId}',paths)
