import csv
from datetime import datetime, timedelta
from io import StringIO

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from .models import Equipment, Reservation, DamageRecord, StockFlow, AuditLog
from .services import (
    ReservationError,
    create_reservation,
    cancel_reservation,
    approve_reservation,
    reject_reservation,
    pick_up_reservation,
    return_reservation,
    report_damage,
    process_damage,
    check_and_mark_overdue,
    get_weekly_heat_data,
    get_overdue_reservations,
    get_pending_damages,
    get_available_quantity,
)


def is_staff(user):
    return user.is_authenticated and user.is_staff


def login_view(request):
    if request.user.is_authenticated:
        return redirect('equipment:home')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            messages.error(request, '用户名或密码错误')
    return render(request, 'equipment/login.html')


def logout_view(request):
    logout(request)
    return redirect('equipment:login')


@login_required
def home(request):
    check_and_mark_overdue()

    weekly_heat = get_weekly_heat_data()
    overdue_list = get_overdue_reservations()[:5]
    pending_damages = get_pending_damages()[:5]

    my_reservations = Reservation.objects.filter(
        user=request.user
    ).select_related('equipment').order_by('-created_at')[:5]

    total_equipments = Equipment.objects.count()
    pending_count = Reservation.objects.filter(status=Reservation.STATUS_PENDING).count()
    overdue_count = overdue_list.count() if hasattr(overdue_list, 'count') else len(list(overdue_list))
    damage_pending_count = pending_damages.count() if hasattr(pending_damages, 'count') else len(list(pending_damages))

    context = {
        'weekly_heat': weekly_heat,
        'overdue_list': list(overdue_list)[:5],
        'pending_damages': list(pending_damages)[:5],
        'my_reservations': my_reservations,
        'total_equipments': total_equipments,
        'pending_count': pending_count,
        'overdue_count': overdue_count,
        'damage_pending_count': damage_pending_count,
    }
    return render(request, 'equipment/home.html', context)


@login_required
def equipment_list(request):
    category = request.GET.get('category', '')
    search = request.GET.get('search', '')

    equipments = Equipment.objects.all()
    if category:
        equipments = equipments.filter(category=category)
    if search:
        equipments = equipments.filter(name__icontains=search)

    categories = Equipment.objects.values_list('category', flat=True).distinct()
    categories = [c for c in categories if c]

    context = {
        'equipments': equipments,
        'categories': categories,
        'current_category': category,
        'search': search,
    }
    return render(request, 'equipment/equipment_list.html', context)


@login_required
def equipment_detail(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    today = timezone.now().date()
    dates = [today + timedelta(days=i) for i in range(7)]

    availability = []
    for d in dates:
        morning_avail = get_available_quantity(equipment, d, Reservation.TIME_SLOT_MORNING)
        afternoon_avail = get_available_quantity(equipment, d, Reservation.TIME_SLOT_AFTERNOON)
        availability.append({
            'date': d,
            'weekday': d.strftime('%A'),
            'morning': morning_avail,
            'afternoon': afternoon_avail,
        })

    my_reservations = Reservation.objects.filter(
        user=request.user,
        equipment=equipment
    ).order_by('-created_at')[:5]

    context = {
        'equipment': equipment,
        'availability': availability,
        'my_reservations': my_reservations,
    }
    return render(request, 'equipment/equipment_detail.html', context)


@login_required
@require_http_methods(['POST'])
def reservation_create(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)

    reservation_date = request.POST.get('reservation_date')
    time_slot = request.POST.get('time_slot')
    quantity = int(request.POST.get('quantity', 1))
    purpose = request.POST.get('purpose', '')

    try:
        reservation = create_reservation(
            user=request.user,
            equipment=equipment,
            reservation_date=reservation_date,
            time_slot=time_slot,
            quantity=quantity,
            purpose=purpose,
            request=request,
        )
        if request.headers.get('HX-Request'):
            messages.success(request, '预约提交成功，等待管理员审批')
            return render(request, 'equipment/partials/reservation_success.html', {
                'reservation': reservation,
                'equipment': equipment,
            })
        messages.success(request, '预约提交成功，等待管理员审批')
        return redirect('equipment:reservation_list')
    except ReservationError as e:
        if request.headers.get('HX-Request'):
            return render(request, 'equipment/partials/error_alert.html', {
                'message': str(e),
            }, status=400)
        messages.error(request, str(e))
        return redirect('equipment:equipment_detail', pk=pk)


@login_required
def reservation_list(request):
    status = request.GET.get('status', '')
    my_reservations = request.GET.get('my', '1') == '1'

    reservations = Reservation.objects.select_related('user', 'equipment')

    if my_reservations or not request.user.is_staff:
        reservations = reservations.filter(user=request.user)

    if status:
        reservations = reservations.filter(status=status)

    reservations = reservations.order_by('-created_at')

    context = {
        'reservations': reservations,
        'current_status': status,
        'status_choices': Reservation.STATUS_CHOICES,
    }
    return render(request, 'equipment/reservation_list.html', context)


@login_required
@require_http_methods(['POST'])
def reservation_cancel(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    try:
        cancel_reservation(reservation, request.user, request=request)
        if request.headers.get('HX-Request'):
            messages.success(request, '预约已取消')
            return render(request, 'equipment/partials/reservation_item.html', {
                'reservation': reservation,
            })
        messages.success(request, '预约已取消')
    except ReservationError as e:
        if request.headers.get('HX-Request'):
            return render(request, 'equipment/partials/error_alert.html', {
                'message': str(e),
            }, status=400)
        messages.error(request, str(e))

    return redirect('equipment:reservation_list')


@login_required
@user_passes_test(is_staff)
def admin_dashboard(request):
    check_and_mark_overdue()

    pending_reservations = Reservation.objects.filter(
        status=Reservation.STATUS_PENDING
    ).select_related('user', 'equipment').order_by('created_at')

    overdue_reservations = get_overdue_reservations()
    pending_damages = get_pending_damages()

    context = {
        'pending_reservations': pending_reservations,
        'overdue_reservations': list(overdue_reservations),
        'pending_damages': list(pending_damages),
    }
    return render(request, 'equipment/admin_dashboard.html', context)


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def reservation_approve(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    try:
        approve_reservation(reservation, request.user, request=request)
        if request.headers.get('HX-Request'):
            messages.success(request, '预约已批准')
            return render(request, 'equipment/partials/reservation_item.html', {
                'reservation': reservation,
            })
        messages.success(request, '预约已批准')
    except ReservationError as e:
        if request.headers.get('HX-Request'):
            return render(request, 'equipment/partials/error_alert.html', {
                'message': str(e),
            }, status=400)
        messages.error(request, str(e))

    return redirect('equipment:admin_dashboard')


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def reservation_reject(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    reason = request.POST.get('reason', '')
    try:
        reject_reservation(reservation, request.user, reason=reason, request=request)
        if request.headers.get('HX-Request'):
            messages.success(request, '预约已拒绝')
            return render(request, 'equipment/partials/reservation_item.html', {
                'reservation': reservation,
            })
        messages.success(request, '预约已拒绝')
    except ReservationError as e:
        if request.headers.get('HX-Request'):
            return render(request, 'equipment/partials/error_alert.html', {
                'message': str(e),
            }, status=400)
        messages.error(request, str(e))

    return redirect('equipment:admin_dashboard')


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def reservation_pickup(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    try:
        pick_up_reservation(reservation, request.user, request=request)
        if request.headers.get('HX-Request'):
            messages.success(request, '已登记领取')
            return render(request, 'equipment/partials/reservation_item.html', {
                'reservation': reservation,
            })
        messages.success(request, '已登记领取')
    except ReservationError as e:
        if request.headers.get('HX-Request'):
            return render(request, 'equipment/partials/error_alert.html', {
                'message': str(e),
            }, status=400)
        messages.error(request, str(e))

    return redirect('equipment:admin_dashboard')


@login_required
@user_passes_test(is_staff)
def reservation_return(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if request.method == 'POST':
        note = request.POST.get('note', '')
        is_damaged = request.POST.get('is_damaged') == 'on'
        damage_description = request.POST.get('damage_description', '')
        try:
            return_reservation(
                reservation, request.user,
                note=note,
                is_damaged=is_damaged,
                damage_description=damage_description,
                request=request,
            )
            messages.success(request, '归还登记成功')
            return redirect('equipment:admin_dashboard')
        except ReservationError as e:
            messages.error(request, str(e))

    return render(request, 'equipment/reservation_return.html', {'reservation': reservation})


@login_required
def damage_list(request):
    status = request.GET.get('status', '')
    damages = DamageRecord.objects.select_related('equipment', 'reported_by')
    if status:
        damages = damages.filter(status=status)
    damages = damages.order_by('-created_at')

    context = {
        'damages': damages,
        'current_status': status,
        'status_choices': DamageRecord.STATUS_CHOICES,
    }
    return render(request, 'equipment/damage_list.html', context)


@login_required
@require_http_methods(['POST'])
def damage_report(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    description = request.POST.get('description', '')
    quantity = int(request.POST.get('quantity', 1))

    try:
        damage_record = report_damage(
            equipment, request.user,
            description=description,
            quantity=quantity,
            request=request,
        )
        messages.success(request, '损坏已上报')
        return redirect('equipment:damage_list')
    except ReservationError as e:
        messages.error(request, str(e))
        return redirect('equipment:equipment_detail', pk=pk)


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def damage_process(request, pk):
    damage_record = get_object_or_404(DamageRecord, pk=pk)
    handle_note = request.POST.get('handle_note', '')
    mark_resolved = request.POST.get('mark_resolved') == 'on'

    try:
        process_damage(damage_record, request.user, handle_note=handle_note, mark_resolved=mark_resolved, request=request)
        messages.success(request, '损坏记录已处理')
    except ReservationError as e:
        messages.error(request, str(e))

    return redirect('equipment:damage_list')


@login_required
@user_passes_test(is_staff)
def stock_flow_list(request):
    equipment_id = request.GET.get('equipment', '')
    flows = StockFlow.objects.select_related('equipment', 'operator', 'reservation')
    if equipment_id:
        flows = flows.filter(equipment_id=equipment_id)
    flows = flows.order_by('-created_at')

    equipments = Equipment.objects.all()

    context = {
        'flows': flows,
        'equipments': equipments,
        'current_equipment': equipment_id,
    }
    return render(request, 'equipment/stock_flow_list.html', context)


@login_required
@user_passes_test(is_staff)
def audit_log_list(request):
    logs = AuditLog.objects.select_related('user').order_by('-created_at')[:100]
    return render(request, 'equipment/audit_log_list.html', {'logs': logs})


@login_required
@user_passes_test(is_staff)
def export_csv(request):
    month = request.GET.get('month', '')
    if not month:
        today = timezone.now()
        month = today.strftime('%Y-%m')

    year, month_num = map(int, month.split('-'))
    start_date = datetime(year, month_num, 1).date()
    if month_num == 12:
        end_date = datetime(year + 1, 1, 1).date()
    else:
        end_date = datetime(year, month_num + 1, 1).date()

    reservations = Reservation.objects.filter(
        reservation_date__range=[start_date, end_date]
    ).select_related('user', 'equipment').order_by('reservation_date', 'time_slot')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="reservations_{month}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        '预约ID', '预约人', '器材名称', '预约日期', '时段',
        '数量', '状态', '用途', '审批人', '审批时间',
        '领取时间', '归还时间', '创建时间'
    ])

    for r in reservations:
        writer.writerow([
            r.id,
            r.user.username,
            r.equipment.name,
            r.reservation_date,
            r.get_time_slot_display(),
            r.quantity,
            r.get_status_display(),
            r.purpose,
            r.approved_by.username if r.approved_by else '',
            r.approved_at.strftime('%Y-%m-%d %H:%M') if r.approved_at else '',
            r.picked_at.strftime('%Y-%m-%d %H:%M') if r.picked_at else '',
            r.returned_at.strftime('%Y-%m-%d %H:%M') if r.returned_at else '',
            r.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    return response


@login_required
@user_passes_test(is_staff)
def export_stock_csv(request):
    month = request.GET.get('month', '')
    if not month:
        today = timezone.now()
        month = today.strftime('%Y-%m')

    year, month_num = map(int, month.split('-'))
    start_date = datetime(year, month_num, 1)
    if month_num == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month_num + 1, 1)

    flows = StockFlow.objects.filter(
        created_at__range=[start_date, end_date]
    ).select_related('equipment', 'operator', 'reservation').order_by('created_at')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="stock_flows_{month}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        '流水ID', '器材名称', '流动类型', '变动原因',
        '数量', '变动后库存', '操作人', '关联预约ID',
        '备注', '创建时间'
    ])

    for f in flows:
        writer.writerow([
            f.id,
            f.equipment.name,
            f.get_flow_type_display(),
            f.get_flow_reason_display(),
            f.quantity,
            f.balance_after,
            f.operator.username if f.operator else '',
            f.reservation_id if f.reservation_id else '',
            f.note,
            f.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    return response
