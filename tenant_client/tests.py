from django.test import SimpleTestCase
from django_tenants.test.cases import FastTenantTestCase as DjangoTenantsFastTenantTestCase

from tenant_client.test_utils import FastTenantTestCase


class FastTenantTestCaseContractTests(SimpleTestCase):
    def test_wrapper_uses_django_tenants_fast_base(self):
        self.assertTrue(issubclass(FastTenantTestCase, DjangoTenantsFastTenantTestCase))
        self.assertEqual(FastTenantTestCase.__bases__[0], DjangoTenantsFastTenantTestCase)
