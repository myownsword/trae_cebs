from django.contrib import admin
from .models import Equipment, Reservation, DamageRecord, AuditLog, StockFlow


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'total_quantity', 'available_quantity', 'status', 'created_at']
    list_filter = ['status', 'category']
    search_fields = ['name']
    ordering = ['name']


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'equipment', 'reservation_date', 'time_slot', 'quantity', 'status', 'created_at']
    list_filter = ['status', 'time_slot', 'reservation_date']
    search_fields = ['user__username', 'equipment__name']
    ordering = ['-created_at']


@admin.register(DamageRecord)
class DamageRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'equipment', 'quantity', 'status', 'reported_by', 'created_at']
    list_filter = ['status']
    search_fields = ['equipment__name', 'reported_by__username']
    ordering = ['-created_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'action', 'target_type', 'target_id', 'user', 'created_at']
    list_filter = ['action', 'target_type']
    search_fields = ['user__username', 'target_type']
    ordering = ['-created_at']
    readonly_fields = ['created_at']


@admin.register(StockFlow)
class StockFlowAdmin(admin.ModelAdmin):
    list_display = ['id', 'equipment', 'flow_type', 'flow_reason', 'quantity', 'balance_after', 'operator', 'created_at']
    list_filter = ['flow_type', 'flow_reason']
    search_fields = ['equipment__name', 'operator__username']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
