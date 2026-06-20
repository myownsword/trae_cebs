from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from datetime import timedelta
from .models import Equipment, Reservation, DamageRecord, AuditLog, StockFlow


class ReservationError(Exception):
    pass


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_audit(user, action, target_type, target_id, details='', ip_address=None):
    AuditLog.objects.create(
        user=user,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )


def create_stock_flow(equipment, flow_type, flow_reason, quantity, operator, reservation=None, note=''):
    if flow_type == StockFlow.FLOW_IN:
        equipment.available_quantity += quantity
    else:
        equipment.available_quantity -= quantity
    equipment.save()

    StockFlow.objects.create(
        equipment=equipment,
        flow_type=flow_type,
        flow_reason=flow_reason,
        quantity=quantity,
        reservation=reservation,
        operator=operator,
        note=note,
        balance_after=equipment.available_quantity,
    )


def get_available_quantity(equipment, reservation_date, time_slot, exclude_reservation_id=None):
    reserved_quantity = Reservation.objects.filter(
        equipment=equipment,
        reservation_date=reservation_date,
        time_slot=time_slot,
        status__in=[
            Reservation.STATUS_PENDING,
            Reservation.STATUS_APPROVED,
            Reservation.STATUS_PICKED,
        ]
    )
    if exclude_reservation_id:
        reserved_quantity = reserved_quantity.exclude(id=exclude_reservation_id)
    reserved_quantity = reserved_quantity.aggregate(total=Sum('quantity'))['total'] or 0
    return equipment.total_quantity - reserved_quantity


def create_reservation(user, equipment, reservation_date, time_slot, quantity, purpose='', request=None):
    if equipment.status == Equipment.STATUS_DAMAGED:
        raise ReservationError('该器材已损坏，无法预约')

    if quantity <= 0:
        raise ReservationError('预约数量必须大于0')

    if quantity > equipment.total_quantity:
        raise ReservationError(f'预约数量不能超过总库存 {equipment.total_quantity}')

    available = get_available_quantity(equipment, reservation_date, time_slot)
    if available < quantity:
        raise ReservationError(f'该时段库存不足，当前可用 {available} 件')

    with transaction.atomic():
        reservation = Reservation.objects.create(
            user=user,
            equipment=equipment,
            reservation_date=reservation_date,
            time_slot=time_slot,
            quantity=quantity,
            purpose=purpose,
            status=Reservation.STATUS_PENDING,
        )

        ip = get_client_ip(request) if request else None
        log_audit(
            user=user,
            action=AuditLog.ACTION_CREATE,
            target_type='reservation',
            target_id=reservation.id,
            details=f'预约 {equipment.name} {quantity} 件，日期：{reservation_date}，时段：{time_slot}',
            ip_address=ip,
        )

    return reservation


def cancel_reservation(reservation, user, request=None):
    if reservation.user != user and not user.is_staff:
        raise ReservationError('只能取消自己的预约')

    if reservation.status not in [Reservation.STATUS_PENDING, Reservation.STATUS_APPROVED]:
        raise ReservationError('当前状态无法取消预约')

    with transaction.atomic():
        old_status = reservation.status
        reservation.status = Reservation.STATUS_CANCELLED
        reservation.save()

        ip = get_client_ip(request) if request else None
        log_audit(
            user=user,
            action=AuditLog.ACTION_CANCEL,
            target_type='reservation',
            target_id=reservation.id,
            details=f'取消预约，原状态：{old_status}',
            ip_address=ip,
        )

    return reservation


def approve_reservation(reservation, admin_user, request=None):
    if not admin_user.is_staff:
        raise ReservationError('只有管理员可以审批预约')

    if reservation.status != Reservation.STATUS_PENDING:
        raise ReservationError('只有待审批的预约可以批准')

    if reservation.equipment.status == Equipment.STATUS_DAMAGED:
        raise ReservationError('器材已损坏，无法批准预约')

    available = get_available_quantity(
        reservation.equipment,
        reservation.reservation_date,
        reservation.time_slot,
        exclude_reservation_id=reservation.id
    )
    if available < reservation.quantity:
        raise ReservationError(f'库存不足，当前可用 {available} 件')

    with transaction.atomic():
        reservation.status = Reservation.STATUS_APPROVED
        reservation.approved_by = admin_user
        reservation.approved_at = timezone.now()
        reservation.save()

        ip = get_client_ip(request) if request else None
        log_audit(
            user=admin_user,
            action=AuditLog.ACTION_APPROVE,
            target_type='reservation',
            target_id=reservation.id,
            details=f'批准预约 {reservation.equipment.name} {reservation.quantity} 件',
            ip_address=ip,
        )

    return reservation


def reject_reservation(reservation, admin_user, reason='', request=None):
    if not admin_user.is_staff:
        raise ReservationError('只有管理员可以拒绝预约')

    if reservation.status != Reservation.STATUS_PENDING:
        raise ReservationError('只有待审批的预约可以拒绝')

    with transaction.atomic():
        reservation.status = Reservation.STATUS_REJECTED
        reservation.approved_by = admin_user
        reservation.approved_at = timezone.now()
        reservation.reject_reason = reason
        reservation.save()

        ip = get_client_ip(request) if request else None
        log_audit(
            user=admin_user,
            action=AuditLog.ACTION_REJECT,
            target_type='reservation',
            target_id=reservation.id,
            details=f'拒绝预约，原因：{reason}',
            ip_address=ip,
        )

    return reservation


def pick_up_reservation(reservation, admin_user, request=None):
    if not admin_user.is_staff:
        raise ReservationError('只有管理员可以登记领取')

    if reservation.status != Reservation.STATUS_APPROVED:
        raise ReservationError('只有已批准的预约可以领取')

    if reservation.equipment.status == Equipment.STATUS_DAMAGED:
        raise ReservationError('器材已损坏，无法领取')

    with transaction.atomic():
        reservation.status = Reservation.STATUS_PICKED
        reservation.picked_at = timezone.now()
        reservation.save()

        create_stock_flow(
            equipment=reservation.equipment,
            flow_type=StockFlow.FLOW_OUT,
            flow_reason=StockFlow.FLOW_REASON_RESERVE,
            quantity=reservation.quantity,
            operator=admin_user,
            reservation=reservation,
            note=f'领取：{reservation.user.username}',
        )

        ip = get_client_ip(request) if request else None
        log_audit(
            user=admin_user,
            action=AuditLog.ACTION_PICK,
            target_type='reservation',
            target_id=reservation.id,
            details=f'登记领取 {reservation.equipment.name} {reservation.quantity} 件，领取人：{reservation.user.username}',
            ip_address=ip,
        )

    return reservation


def return_reservation(reservation, admin_user, note='', is_damaged=False, damage_description='', request=None):
    if not admin_user.is_staff:
        raise ReservationError('只有管理员可以登记归还')

    if reservation.status not in [Reservation.STATUS_PICKED, Reservation.STATUS_OVERDUE]:
        raise ReservationError('只有已领取或逾期的预约可以归还')

    if reservation.status == Reservation.STATUS_RETURNED:
        raise ReservationError('该预约已经归还，请勿重复操作')

    with transaction.atomic():
        reservation.status = Reservation.STATUS_RETURNED
        reservation.returned_at = timezone.now()
        reservation.return_note = note
        reservation.save()

        if not is_damaged:
            create_stock_flow(
                equipment=reservation.equipment,
                flow_type=StockFlow.FLOW_IN,
                flow_reason=StockFlow.FLOW_REASON_RETURN,
                quantity=reservation.quantity,
                operator=admin_user,
                reservation=reservation,
                note=f'归还：{reservation.user.username}',
            )
        else:
            equipment = reservation.equipment
            damage_qty = reservation.quantity

            DamageRecord.objects.create(
                equipment=equipment,
                reported_by=admin_user,
                description=damage_description or note or '归还时发现损坏',
                quantity=damage_qty,
                status=DamageRecord.STATUS_REPORTED,
            )

            equipment.total_quantity = max(0, equipment.total_quantity - damage_qty)
            if equipment.total_quantity <= 0:
                equipment.status = Equipment.STATUS_DAMAGED
            equipment.save()

            StockFlow.objects.create(
                equipment=equipment,
                flow_type=StockFlow.FLOW_OUT,
                flow_reason=StockFlow.FLOW_REASON_DAMAGE,
                quantity=damage_qty,
                reservation=reservation,
                operator=admin_user,
                note=f'归还时损坏：{reservation.user.username}，描述：{(damage_description or note)[:50]}',
                balance_after=equipment.available_quantity,
            )

            ip = get_client_ip(request) if request else None
            log_audit(
                user=admin_user,
                action=AuditLog.ACTION_DAMAGE,
                target_type='equipment',
                target_id=equipment.id,
                details=f'归还时发现损坏：{equipment.name} {damage_qty} 件，描述：{damage_description or note}，总库存已扣减',
                ip_address=ip,
            )

        ip = get_client_ip(request) if request else None
        log_audit(
            user=admin_user,
            action=AuditLog.ACTION_RETURN,
            target_type='reservation',
            target_id=reservation.id,
            details=f'登记归还 {reservation.equipment.name} {reservation.quantity} 件，归还人：{reservation.user.username}，损坏：{is_damaged}',
            ip_address=ip,
        )

    return reservation


def report_damage(equipment, user, description, quantity=1, request=None):
    if equipment.status == Equipment.STATUS_DAMAGED:
        raise ReservationError('该器材已标记为损坏状态')

    if quantity <= 0:
        raise ReservationError('损坏数量必须大于0')

    if quantity > equipment.available_quantity:
        raise ReservationError(f'损坏数量不能超过可用库存 {equipment.available_quantity}')

    with transaction.atomic():
        damage_record = DamageRecord.objects.create(
            equipment=equipment,
            reported_by=user,
            description=description,
            quantity=quantity,
            status=DamageRecord.STATUS_REPORTED,
        )

        create_stock_flow(
            equipment=equipment,
            flow_type=StockFlow.FLOW_OUT,
            flow_reason=StockFlow.FLOW_REASON_DAMAGE,
            quantity=quantity,
            operator=user,
            note=f'损坏上报：{description[:50]}',
        )

        equipment.total_quantity = max(0, equipment.total_quantity - quantity)
        if equipment.total_quantity <= 0 or equipment.available_quantity <= 0:
            equipment.status = Equipment.STATUS_DAMAGED
        equipment.save()

        ip = get_client_ip(request) if request else None
        log_audit(
            user=user,
            action=AuditLog.ACTION_DAMAGE,
            target_type='damage',
            target_id=damage_record.id,
            details=f'上报损坏 {equipment.name} {quantity} 件：{description}，总库存已扣减',
            ip_address=ip,
        )

    return damage_record


def process_damage(damage_record, admin_user, handle_note='', mark_resolved=True, request=None):
    if not admin_user.is_staff:
        raise ReservationError('只有管理员可以处理损坏记录')

    if damage_record.status == DamageRecord.STATUS_RESOLVED:
        raise ReservationError('该损坏记录已处理')

    with transaction.atomic():
        if mark_resolved:
            damage_record.status = DamageRecord.STATUS_RESOLVED
        else:
            damage_record.status = DamageRecord.STATUS_PROCESSING
        damage_record.handled_by = admin_user
        damage_record.handle_note = handle_note
        damage_record.handled_at = timezone.now()
        damage_record.save()

        ip = get_client_ip(request) if request else None
        log_audit(
            user=admin_user,
            action=AuditLog.ACTION_UPDATE,
            target_type='damage',
            target_id=damage_record.id,
            details=f'处理损坏记录：{handle_note}，状态：{damage_record.get_status_display()}',
            ip_address=ip,
        )

    return damage_record


def check_and_mark_overdue():
    now = timezone.now()
    today = now.date()
    now_time = now.time()

    overdue_reservations = Reservation.objects.filter(
        status__in=[Reservation.STATUS_APPROVED, Reservation.STATUS_PICKED],
        reservation_date__lte=today,
    )

    marked = []
    for res in overdue_reservations:
        is_overdue = False
        if res.reservation_date < today:
            is_overdue = True
        elif res.reservation_date == today:
            from datetime import time
            if res.time_slot == Reservation.TIME_SLOT_MORNING and now_time > time(12, 0):
                is_overdue = True
            elif res.time_slot == Reservation.TIME_SLOT_AFTERNOON and now_time > time(18, 0):
                is_overdue = True

        if is_overdue and res.status != Reservation.STATUS_OVERDUE:
            res.status = Reservation.STATUS_OVERDUE
            res.save()
            log_audit(
                user=None,
                action=AuditLog.ACTION_OVERDUE,
                target_type='reservation',
                target_id=res.id,
                details=f'预约已逾期：{res.equipment.name} {res.quantity} 件',
            )
            marked.append(res)

    return marked


def get_weekly_heat_data():
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    reservations = Reservation.objects.filter(
        reservation_date__range=[week_start, week_end],
        status__in=[Reservation.STATUS_APPROVED, Reservation.STATUS_PICKED, Reservation.STATUS_RETURNED]
    ).values('equipment__name').annotate(
        total=Sum('quantity')
    ).order_by('-total')[:10]

    return list(reservations)


def get_overdue_reservations():
    check_and_mark_overdue()
    return Reservation.objects.filter(
        status=Reservation.STATUS_OVERDUE
    ).select_related('user', 'equipment').order_by('reservation_date')


def get_pending_damages():
    return DamageRecord.objects.filter(
        status__in=[DamageRecord.STATUS_REPORTED, DamageRecord.STATUS_PROCESSING]
    ).select_related('equipment', 'reported_by').order_by('-created_at')
