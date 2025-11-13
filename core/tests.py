from django.test import TestCase, RequestFactory
from django.contrib import admin
from django.contrib.auth.models import User

from .models import Employee
from .admin import EmployeeAdmin


class CoreAdminSignalsTests(TestCase):
	def test_user_post_save_creates_employee(self):
		user = User.objects.create(username='u1')
		# Employee should be created by the signal
		self.assertTrue(Employee.objects.filter(user=user).exists())

	def test_employee_admin_save_creates_user_when_missing(self):
		rf = RequestFactory()
		request = rf.post('/admin/core/employee/add/')
		# attach a user to the request (superuser) to mimic admin usage
		admin_user = User.objects.create_superuser('admin', email='admin@example.com', password='pass')
		request.user = admin_user

		emp = Employee(curp='TESTCURP1', rfc='TESTRFC1', street_number='123')

		emp_admin = EmployeeAdmin(Employee, admin.site)
		# Save the employee via admin; this should create and assign a User
		emp_admin.save_model(request, emp, form=None, change=False)

		self.assertIsNotNone(emp.user)
		self.assertTrue(User.objects.filter(pk=emp.user.pk).exists())
