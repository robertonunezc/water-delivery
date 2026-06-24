from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase

from tenant_client.test_utils import FastTenantTestCase


class FastTenantTestCaseContractTests(SimpleTestCase):
    def test_wrapper_uses_tenant_test_case_base(self):
        self.assertTrue(issubclass(FastTenantTestCase, TenantTestCase))

    def test_wrapper_generates_class_specific_schema_name(self):
        schema_name = FastTenantTestCase.get_test_schema_name()

        self.assertIn("tenant_client", schema_name)
        self.assertIn("fasttenanttestcase", schema_name)
        self.assertNotEqual(schema_name, "test")

    def test_wrapper_generates_hostname_safe_domain(self):
        domain = FastTenantTestCase.get_test_tenant_domain()

        self.assertTrue(domain.endswith(".test.com"))
        self.assertNotIn("_", domain)
