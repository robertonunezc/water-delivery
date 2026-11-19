from __future__ import annotations

from argparse import ArgumentParser
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import schema_context

from clients.models import Client
from clients.services.credit_transfer_service import (
    preview_branch_credit_transfer,
    transfer_existing_branch_credit,
)


class Command(BaseCommand):
    help = 'Preview or explicitly transfer older corporate-funded debt to existing branch credit accounts.'

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument('--schema', required=True, help='Tenant schema to process.')
        parser.add_argument('--branch-id', type=int, help='Process only this branch.')
        parser.add_argument('--user-id', type=int, help='Tenant user responsible for this migration.')
        parser.add_argument('--apply', action='store_true', help='Persist transfers; default is read-only preview.')

    def handle(self, *args: str, **options: Any) -> None:
        with schema_context(options['schema']):
            branches = Client.objects.filter(type='branch', credit_override_enabled=True)
            if options.get('branch_id'):
                branches = branches.filter(pk=options['branch_id'])
            branches = list(branches.select_related('corporate').order_by('pk'))
            if not branches:
                raise CommandError('No matching branches with their own credit were found.')
            user = self._get_user(options.get('user_id'))
            try:
                amounts = [(branch, self._preview(branch)) for branch in branches]
                if options['apply']:
                    with transaction.atomic():
                        list(Client.objects.select_for_update().filter(
                            pk__in=[branch.pk for branch in branches],
                        ).order_by('pk'))
                        amounts = [(branch, transfer_existing_branch_credit(branch, user)) for branch in branches]
            except ValueError as error:
                raise CommandError(str(error)) from error
            for branch, amount in amounts:
                mode = 'APPLIED' if options['apply'] else 'PREVIEW'
                self.stdout.write(f'{mode} branch={branch.pk} {branch.name} amount={amount:.2f}')

    def _preview(self, branch: Client) -> Decimal:
        if not branch.corporate_id:
            raise ValueError(f'Branch #{branch.pk} has no corporate account.')
        return preview_branch_credit_transfer(branch, branch.corporate, branch)

    def _get_user(self, user_id: int | None) -> AbstractBaseUser | None:
        if user_id is None:
            return None
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            raise CommandError(f'User #{user_id} does not exist in this tenant.')
        return user
