from django.test import TestCase, RequestFactory
from django.contrib import admin
from django.contrib.auth.models import User

from .models import Employee
from .admin import EmployeeAdmin
