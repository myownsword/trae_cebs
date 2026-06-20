import codecs
import csv
from datetime import datetime, timedelta
from io import BytesIO

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from .models import Equipment, Reservation, DamageRecord, StockFlow, AuditLog, WaitlistEntry
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
    get_equipment_occupied_quantity,
    create_equipment,
    update_equipment,
    adjust_equipment_stock,
    set_equipment_offline,
    set_equipment_online,
    create_waitlist_entry,
    cancel_waitlist_entry,
    skip_waitlist_entry,
    reject_waitlist_entry,
    promote_waitlist_entry,
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

    categories = sorted(set(c for c in Equipment.objects.values_list('category', flat=True) if c and c.strip()))

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
    join_waitlist = request.POST.get('join_waitlist') == '1'

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
        error_msg = str(e)
        if join_waitlist and '库存不足' in error_msg:
            try:
                entry = create_waitlist_entry(
                    user=request.user,
                    equipment=equipment,
                    reservation_date=reservation_date,
                    time_slot=time_slot,
                    quantity=quantity,
                    request=request,
                )
                success_msg = f'已加入候补队列，排队位置：第 {entry.queue_position} 位'
                if request.headers.get('HX-Request'):
                    messages.success(request, success_msg)
                    return render(request, 'equipment/partials/reservation_success.html', {
                        'equipment': equipment,
                        'waitlist_entry': entry,
                    })
                messages.success(request, success_msg)
                return redirect('equipment:reservation_list')
            except ReservationError as we:
                if request.headers.get('HX-Request'):
                    return render(request, 'equipment/partials/error_alert.html', {
                        'message': str(we),
                    }, status=400)
                messages.error(request, str(we))
                return redirect('equipment:equipment_detail', pk=pk)

        if request.headers.get('HX-Request'):
            return render(request, 'equipment/partials/error_alert.html', {
                'message': error_msg,
                'show_waitlist': '库存不足' in error_msg,
                'equipment_pk': pk,
                'reservation_date': reservation_date,
                'time_slot': time_slot,
                'quantity': quantity,
            }, status=400)
        messages.error(request, error_msg)
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

    my_waitlist = WaitlistEntry.objects.filter(
        user=request.user
    ).select_related('equipment').order_by('-created_at')

    context = {
        'reservations': reservations,
        'current_status': status,
        'status_choices': Reservation.STATUS_CHOICES,
        'my_waitlist': my_waitlist,
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
    from django.core.paginator import Paginator, EmptyPage

    check_and_mark_overdue()
    per_page = 5

    pending_qs = Reservation.objects.filter(
        status=Reservation.STATUS_PENDING
    ).select_related('user', 'equipment').order_by('created_at')

    approved_qs = Reservation.objects.filter(
        status=Reservation.STATUS_APPROVED
    ).select_related('user', 'equipment').order_by('reservation_date', 'time_slot')

    picked_qs = Reservation.objects.filter(
        status=Reservation.STATUS_PICKED
    ).select_related('user', 'equipment').order_by('picked_at')

    overdue_qs = get_overdue_reservations()
    damage_qs = get_pending_damages()

    waitlist_qs = WaitlistEntry.objects.filter(
        status=WaitlistEntry.STATUS_WAITING
    ).select_related('user', 'equipment').order_by('queue_position')

    pending_paginator = Paginator(pending_qs, per_page)
    approved_paginator = Paginator(approved_qs, per_page)
    picked_paginator = Paginator(picked_qs, per_page)
    overdue_paginator = Paginator(overdue_qs, per_page)
    damage_paginator = Paginator(damage_qs, per_page)
    waitlist_paginator = Paginator(waitlist_qs, per_page)

    try:
        pending_page = pending_paginator.page(int(request.GET.get('pending_page', 1)))
    except (EmptyPage, ValueError):
        pending_page = pending_paginator.page(pending_paginator.num_pages)

    try:
        approved_page = approved_paginator.page(int(request.GET.get('approved_page', 1)))
    except (EmptyPage, ValueError):
        approved_page = approved_paginator.page(approved_paginator.num_pages)

    try:
        picked_page = picked_paginator.page(int(request.GET.get('picked_page', 1)))
    except (EmptyPage, ValueError):
        picked_page = picked_paginator.page(picked_paginator.num_pages)

    try:
        overdue_page = overdue_paginator.page(int(request.GET.get('overdue_page', 1)))
    except (EmptyPage, ValueError):
        overdue_page = overdue_paginator.page(overdue_paginator.num_pages)

    try:
        damage_page = damage_paginator.page(int(request.GET.get('damage_page', 1)))
    except (EmptyPage, ValueError):
        damage_page = damage_paginator.page(damage_paginator.num_pages)

    try:
        waitlist_page = waitlist_paginator.page(int(request.GET.get('waitlist_page', 1)))
    except (EmptyPage, ValueError):
        waitlist_page = waitlist_paginator.page(waitlist_paginator.num_pages)

    equipment_stats = {
        'total': Equipment.objects.count(),
        'normal': Equipment.objects.filter(status=Equipment.STATUS_NORMAL).count(),
        'damaged': Equipment.objects.filter(status=Equipment.STATUS_DAMAGED).count(),
        'offline': Equipment.objects.filter(status=Equipment.STATUS_OFFLINE).count(),
        'total_qty': Equipment.objects.aggregate(s=Sum('total_quantity'))['s'] or 0,
        'avail_qty': Equipment.objects.aggregate(s=Sum('available_quantity'))['s'] or 0,
    }

    context = {
        'pending_page': pending_page,
        'approved_page': approved_page,
        'picked_page': picked_page,
        'overdue_page': overdue_page,
        'damage_page': damage_page,
        'waitlist_page': waitlist_page,
        'equipment_stats': equipment_stats,
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
        reservation_date__gte=start_date,
        reservation_date__lt=end_date,
    ).select_related('user', 'equipment').order_by('reservation_date', 'time_slot')

    buffer = BytesIO()
    buffer.write(b'\xef\xbb\xbf')
    writer = csv.writer(codecs.getwriter('utf-8')(buffer))
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

    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="reservations_{month}.csv"'
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
        created_at__gte=start_date,
        created_at__lt=end_date,
    ).select_related('equipment', 'operator', 'reservation').order_by('created_at')

    buffer = BytesIO()
    buffer.write(b'\xef\xbb\xbf')
    writer = csv.writer(codecs.getwriter('utf-8')(buffer))
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

    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="stock_flows_{month}.csv"'
    return response


@login_required
@user_passes_test(is_staff)
def admin_equipment_list(request):
    status = request.GET.get('status', '')
    search = request.GET.get('search', '')
    category = request.GET.get('category', '')

    equipments = Equipment.objects.all()
    if status:
        equipments = equipments.filter(status=status)
    if search:
        equipments = equipments.filter(name__icontains=search)
    if category:
        equipments = equipments.filter(category=category)

    equipments = equipments.order_by('-updated_at')

    categories = sorted(set(c for c in Equipment.objects.values_list('category', flat=True) if c and c.strip()))

    for eq in equipments:
        eq.occupied_quantity = get_equipment_occupied_quantity(eq)

    context = {
        'equipments': equipments,
        'current_status': status,
        'current_search': search,
        'current_category': category,
        'status_choices': Equipment.STATUS_CHOICES,
        'categories': categories,
    }
    return render(request, 'equipment/admin_equipment_list.html', context)


@login_required
@user_passes_test(is_staff)
def admin_equipment_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', '').strip()
        description = request.POST.get('description', '')
        try:
            total_quantity = int(request.POST.get('total_quantity', 1))
        except (ValueError, TypeError):
            messages.error(request, '总库存必须是数字')
            return render(request, 'equipment/admin_equipment_form.html', {'mode': 'create'})

        try:
            equipment = create_equipment(
                admin_user=request.user,
                name=name,
                category=category,
                description=description,
                total_quantity=total_quantity,
                request=request,
            )
            messages.success(request, f'器材「{equipment.name}」创建成功')
            return redirect('equipment:admin_equipment_list')
        except ReservationError as e:
            messages.error(request, str(e))

    return render(request, 'equipment/admin_equipment_form.html', {'mode': 'create'})


@login_required
@user_passes_test(is_staff)
def admin_equipment_edit(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', '').strip()
        description = request.POST.get('description', '')
        status = request.POST.get('status', equipment.status)

        try:
            total_quantity = int(request.POST.get('total_quantity', equipment.total_quantity))
        except (ValueError, TypeError):
            messages.error(request, '总库存必须是数字')
            return render(request, 'equipment/admin_equipment_form.html', {
                'mode': 'edit', 'equipment': equipment
            })

        try:
            available_quantity = int(request.POST.get('available_quantity', equipment.available_quantity))
        except (ValueError, TypeError):
            messages.error(request, '可借库存必须是数字')
            return render(request, 'equipment/admin_equipment_form.html', {
                'mode': 'edit', 'equipment': equipment
            })

        try:
            update_equipment(
                equipment=equipment,
                admin_user=request.user,
                name=name,
                category=category,
                description=description,
                total_quantity=total_quantity,
                available_quantity=available_quantity,
                status=status,
                request=request,
            )
            messages.success(request, f'器材「{equipment.name}」更新成功')
            return redirect('equipment:admin_equipment_list')
        except ReservationError as e:
            messages.error(request, str(e))

    equipment.occupied_quantity = get_equipment_occupied_quantity(equipment)
    return render(request, 'equipment/admin_equipment_form.html', {
        'mode': 'edit',
        'equipment': equipment,
        'status_choices': Equipment.STATUS_CHOICES,
    })


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def admin_equipment_offline(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    reason = request.POST.get('reason', '')
    try:
        set_equipment_offline(equipment, request.user, reason=reason, request=request)
        messages.success(request, f'器材「{equipment.name}」已下架')
    except ReservationError as e:
        messages.error(request, str(e))
    return redirect('equipment:admin_equipment_list')


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def admin_equipment_online(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    try:
        set_equipment_online(equipment, request.user, request=request)
        messages.success(request, f'器材「{equipment.name}」已恢复上架')
    except ReservationError as e:
        messages.error(request, str(e))
    return redirect('equipment:admin_equipment_list')


@login_required
@user_passes_test(is_staff)
def admin_equipment_adjust_stock(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)

    if request.method == 'POST':
        try:
            adjustment = int(request.POST.get('adjustment', 0))
        except (ValueError, TypeError):
            messages.error(request, '调整数量必须是整数')
            equipment.occupied_quantity = get_equipment_occupied_quantity(equipment)
            return render(request, 'equipment/admin_equipment_adjust.html', {'equipment': equipment})

        note = request.POST.get('note', '')

        try:
            adjust_equipment_stock(
                equipment=equipment,
                admin_user=request.user,
                adjustment=adjustment,
                note=note,
                request=request,
            )
            messages.success(request, f'器材「{equipment.name}」库存调整成功')
            return redirect('equipment:admin_equipment_list')
        except ReservationError as e:
            messages.error(request, str(e))

    equipment.occupied_quantity = get_equipment_occupied_quantity(equipment)
    return render(request, 'equipment/admin_equipment_adjust.html', {'equipment': equipment})


@login_required
@require_http_methods(['POST'])
def waitlist_join(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    reservation_date = request.POST.get('reservation_date')
    time_slot = request.POST.get('time_slot')
    quantity = int(request.POST.get('quantity', 1))

    try:
        entry = create_waitlist_entry(
            user=request.user,
            equipment=equipment,
            reservation_date=reservation_date,
            time_slot=time_slot,
            quantity=quantity,
            request=request,
        )
        messages.success(request, f'已加入候补队列，排队位置：第 {entry.queue_position} 位')
    except ReservationError as e:
        messages.error(request, str(e))

    return redirect('equipment:equipment_detail', pk=pk)


@login_required
@require_http_methods(['POST'])
def waitlist_cancel(request, pk):
    entry = get_object_or_404(WaitlistEntry, pk=pk)
    try:
        cancel_waitlist_entry(entry, request.user, request=request)
        messages.success(request, '候补已取消')
    except ReservationError as e:
        messages.error(request, str(e))

    return redirect('equipment:reservation_list')


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def waitlist_skip(request, pk):
    entry = get_object_or_404(WaitlistEntry, pk=pk)
    try:
        skip_waitlist_entry(entry, request.user, request=request)
        messages.success(request, f'已跳过候补：{entry.user.username}')
    except ReservationError as e:
        messages.error(request, str(e))

    return redirect('equipment:admin_dashboard')


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def waitlist_reject(request, pk):
    entry = get_object_or_404(WaitlistEntry, pk=pk)
    reason = request.POST.get('reason', '')
    try:
        reject_waitlist_entry(entry, request.user, reason=reason, request=request)
        messages.success(request, f'已拒绝候补：{entry.user.username}')
    except ReservationError as e:
        messages.error(request, str(e))

    return redirect('equipment:admin_dashboard')


@login_required
@user_passes_test(is_staff)
@require_http_methods(['POST'])
def waitlist_promote(request, pk):
    entry = get_object_or_404(WaitlistEntry, pk=pk)
    try:
        promote_waitlist_entry(entry, request.user, request=request)
        messages.success(request, f'已提升候补为预约：{entry.user.username} - {entry.equipment.name}')
    except ReservationError as e:
        messages.error(request, str(e))

    return redirect('equipment:admin_dashboard')
