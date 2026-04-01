from django.contrib import admin
from django.utils.html import format_html

from . import models
from core.admin_mixins import SoftDeleteAdminMixin


class NotificationAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('title', 'client', 'type', 'channel', 'created_at', 'status', 'sent_at')
    list_filter = ('type', 'channel', 'created_at')
    search_fields = ('title', 'client__name', 'message')
    autocomplete_fields = ('client',)
    readonly_fields = ('created_at', 'updated_at', 'status', 'sent_at')
    exclude = ('deleted_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    fieldsets = (
        ('Información de Notificación', {
            'fields': (
                ('title', 'client'),
                ('type', 'channel'),
                'message'
            )
        }),
        ('Estado', {
            'fields': ('status', 'sent_at'),
        }),
        ('Información del Sistema', {
            'fields': (('created_at', 'updated_at'),),
            'classes': ('collapse',)
        })
    )




class ClientNotificationSettingAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        'client',
        'first_reminder_days',
        'second_reminder_days',
        'cancellation_days',
        'get_configuration_summary'
    )
    search_fields = ('client__name',)
    autocomplete_fields = ('client',)
    readonly_fields = ('created_at', 'updated_at', 'get_configuration_summary')
    exclude = ('deleted_at',)

    fieldsets = (
        ('Cliente', {
            'fields': ('client',)
        }),
        ('Primera Notificación (Recordatorio)', {
            'fields': (
                'first_reminder_days',
                ('first_moment', 'first_condition', )
            ),
            'description': 'Configuración para el primer recordatorio de pago'
        }),
        ('Segunda Notificación (Alerta)', {
            'fields': (
                'second_reminder_days',
                ('second_moment', 'second_condition')
            ),
            'description': 'Configuración para la segunda notificación de pago'
        }),
        ('Notificación de Cancelación', {
            'fields': (
                'cancellation_days',
                ('cancellation_moment', 'cancellation_condition')
            ),
            'description': 'Configuración para la notificación de cancelación de servicio'
        }),
        ('Resumen', {
            'fields': ('get_configuration_summary',),
            'classes': ('collapse',)
        }),
        ('Información del Sistema', {
            'fields': (('created_at', 'updated_at'),),
            'classes': ('collapse',)
        })
    )

    def get_configuration_summary(self, obj: models.ClientNotificationSetting) -> str:
        """Display a human-readable summary of notification settings"""
        summary = '<div style="line-height: 1.8;">'
        summary += '<h3>Configuración de Notificaciones</h3>'

        # First reminder
        summary += f'<strong>1er Recordatorio:</strong> '
        summary += f'{obj.first_reminder_days} días '
        summary += f'{obj.get_first_moment_display()} '
        summary += f'{obj.get_first_condition_display()}<br>'

        # Second reminder
        summary += f'<strong>2da Notificación:</strong> '
        summary += f'{obj.second_reminder_days} días '
        summary += f'{obj.get_second_moment_display()} '
        summary += f'{obj.get_second_condition_display()}<br>'

        # Cancellation
        summary += f'<strong>Cancelación:</strong> '
        summary += f'{obj.cancellation_days} días '
        summary += f'{obj.get_cancellation_moment_display()} '
        summary += f'{obj.get_cancellation_condition_display()}<br>'

        summary += '</div>'
        return format_html(summary)
    get_configuration_summary.short_description = 'Resumen de Configuración'

admin.site.register(models.Notification, NotificationAdmin)
admin.site.register(models.ClientNotificationSetting, ClientNotificationSettingAdmin)