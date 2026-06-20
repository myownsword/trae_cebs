from django.urls import path
from . import views

app_name = 'equipment'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.home, name='home'),

    path('equipments/', views.equipment_list, name='equipment_list'),
    path('equipment/<int:pk>/', views.equipment_detail, name='equipment_detail'),

    path('reservations/', views.reservation_list, name='reservation_list'),
    path('equipment/<int:pk>/reserve/', views.reservation_create, name='reservation_create'),
    path('reservation/<int:pk>/cancel/', views.reservation_cancel, name='reservation_cancel'),

    path('management/', views.admin_dashboard, name='admin_dashboard'),
    path('management/reservation/<int:pk>/approve/', views.reservation_approve, name='reservation_approve'),
    path('management/reservation/<int:pk>/reject/', views.reservation_reject, name='reservation_reject'),
    path('management/reservation/<int:pk>/pickup/', views.reservation_pickup, name='reservation_pickup'),
    path('management/reservation/<int:pk>/return/', views.reservation_return, name='reservation_return'),

    path('damages/', views.damage_list, name='damage_list'),
    path('equipment/<int:pk>/damage/', views.damage_report, name='damage_report'),
    path('damage/<int:pk>/process/', views.damage_process, name='damage_process'),

    path('stock-flows/', views.stock_flow_list, name='stock_flow_list'),
    path('audit-logs/', views.audit_log_list, name='audit_log_list'),

    path('export/csv/', views.export_csv, name='export_csv'),
    path('export/stock-csv/', views.export_stock_csv, name='export_stock_csv'),
]
