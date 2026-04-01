from django.contrib import messages
from django.db.models.deletion import ProtectedError


class SoftDeleteAdminMixin:
    """Admin mixin to replace Django's default delete_selected action."""

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        actions['soft_delete_selected'] = (
            self.soft_delete_selected,
            'soft_delete_selected',
            self.soft_delete_selected.short_description,
        )
        return actions

    def soft_delete_selected(self, request, queryset):
        deleted_count = 0
        blocked_ids = []

        for obj in queryset:
            try:
                obj.delete()
                deleted_count += 1
            except ProtectedError:
                blocked_ids.append(getattr(obj, 'id', None))

        if deleted_count:
            self.message_user(
                request,
                f'Se eliminaron {deleted_count} registro(s) correctamente.',
                level=messages.SUCCESS,
            )

        if blocked_ids:
            sample = ', '.join(str(item) for item in blocked_ids[:10] if item is not None)
            remaining = len(blocked_ids) - 10
            suffix = f' y {remaining} más' if remaining > 0 else ''
            ids_text = f' IDs: {sample}{suffix}.' if sample else ''
            self.message_user(
                request,
                'No se pudieron eliminar algunos registros porque tienen relaciones protegidas.' + ids_text,
                level=messages.ERROR,
            )

    soft_delete_selected.short_description = 'Eliminar seleccionados'
