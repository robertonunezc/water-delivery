from django.test import TestCase, RequestFactory
from django.contrib import admin
from django.contrib.auth import get_user_model

User = get_user_model()

from .models import Employee
from .admin import EmployeeAdmin
