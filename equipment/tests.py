from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date, timedelta
from .models import Equipment, Reservation, StockFlow, AuditLog, WaitlistEntry
from .services import (
    create_equipment, update_equipment, adjust_equipment_stock,
    set_equipment_offline, set_equipment_online,
    get_equipment_occupied_quantity, create_reservation,
    approve_reservation, cancel_reservation, reject_reservation,
    return_reservation, pick_up_reservation,
    ReservationError,
    create_waitlist_entry, cancel_waitlist_entry,
    skip_waitlist_entry, reject_waitlist_entry,
    promote_waitlist_entry, process_waitlist_auto,
    get_available_quantity,
)


class EquipmentMgmtTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_test', 'a@t.com', 'pass1234')
        self.resident = User.objects.create_user('user_test', 'u@t.com', 'pass1234')

    def test_01_create_equipment(self):
        eq = create_equipment(
            admin_user=self.admin, name='测试投影仪', category='电子',
            description='1080P', total_quantity=5
        )
        self.assertEqual(eq.total_quantity, 5)
        self.assertEqual(eq.available_quantity, 5)
        self.assertTrue(StockFlow.objects.filter(
            equipment=eq, flow_reason=StockFlow.FLOW_REASON_PURCHASE, quantity=5
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            target_type='equipment', target_id=eq.id, action=AuditLog.ACTION_CREATE
        ).exists())

    def test_02_update_basic_fields(self):
        eq = create_equipment(self.admin, '测试投影仪', '电子', 'desc', 3)
        update_equipment(
            equipment=eq, admin_user=self.admin,
            name='高清投影仪', category='办公', description='4K高清'
        )
        eq.refresh_from_db()
        self.assertEqual(eq.name, '高清投影仪')
        self.assertEqual(eq.category, '办公')
        self.assertIn('4K', eq.description)
        log = AuditLog.objects.filter(
            target_type='equipment', target_id=eq.id, action=AuditLog.ACTION_UPDATE
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertIn('名称', log.details)

    def test_03_update_total_quantity_increase(self):
        eq = create_equipment(self.admin, '测试投影仪', '电子', 'desc', 3)
        update_equipment(equipment=eq, admin_user=self.admin, total_quantity=6)
        eq.refresh_from_db()
        self.assertEqual(eq.total_quantity, 6)
        self.assertEqual(eq.available_quantity, 6)
        flow = StockFlow.objects.filter(
            equipment=eq, flow_reason=StockFlow.FLOW_REASON_ADJUST
        ).order_by('-id').first()
        self.assertEqual(flow.flow_type, StockFlow.FLOW_IN)
        self.assertEqual(flow.quantity, 3)

    def test_04_occupied_quantity_and_block(self):
        eq = create_equipment(self.admin, '测试投影仪', '电子', 'desc', 8)
        tomorrow = date.today() + timedelta(days=1)
        r = create_reservation(
            user=self.resident, equipment=eq,
            reservation_date=tomorrow, time_slot=Reservation.TIME_SLOT_MORNING, quantity=3
        )
        approve_reservation(r, admin_user=self.admin)
        occupied = get_equipment_occupied_quantity(eq)
        self.assertEqual(occupied, 3)
        with self.assertRaises(ReservationError) as ctx:
            update_equipment(equipment=eq, admin_user=self.admin, total_quantity=2)
        self.assertIn('已占用量', str(ctx.exception))

    def test_05_status_via_update(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 2)
        update_equipment(equipment=eq, admin_user=self.admin, status=Equipment.STATUS_OFFLINE)
        eq.refresh_from_db()
        self.assertEqual(eq.status, Equipment.STATUS_OFFLINE)

    def test_06_offline_online_services(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 2)
        set_equipment_offline(eq, self.admin, reason='测试')
        eq.refresh_from_db()
        self.assertEqual(eq.status, Equipment.STATUS_OFFLINE)
        with self.assertRaises(ReservationError):
            set_equipment_offline(eq, self.admin)
        set_equipment_online(eq, self.admin)
        eq.refresh_from_db()
        self.assertEqual(eq.status, Equipment.STATUS_NORMAL)
        with self.assertRaises(ReservationError):
            set_equipment_online(eq, self.admin)

    def test_07_adjust_stock_increase(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 2)
        adjust_equipment_stock(eq, self.admin, adjustment=+4, note='采购4件')
        eq.refresh_from_db()
        self.assertEqual(eq.total_quantity, 6)
        self.assertEqual(eq.available_quantity, 6)
        flow = StockFlow.objects.filter(
            equipment=eq, flow_reason=StockFlow.FLOW_REASON_ADJUST
        ).order_by('-id').first()
        self.assertEqual(flow.flow_type, StockFlow.FLOW_IN)
        self.assertEqual(flow.quantity, 4)
        self.assertIn('采购4件', flow.note)

    def test_08_adjust_stock_block_below_occupied(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 10)
        tomorrow = date.today() + timedelta(days=1)
        r = create_reservation(
            user=self.resident, equipment=eq,
            reservation_date=tomorrow, time_slot=Reservation.TIME_SLOT_MORNING, quantity=4
        )
        approve_reservation(r, admin_user=self.admin)
        with self.assertRaises(ReservationError) as ctx:
            adjust_equipment_stock(eq, self.admin, adjustment=-10)
        self.assertIn('低于已占用量', str(ctx.exception))

    def test_09_adjust_zero_blocked(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 5)
        with self.assertRaises(ReservationError) as ctx:
            adjust_equipment_stock(eq, self.admin, adjustment=0)
        self.assertIn('不能为0', str(ctx.exception))

    def test_10_non_staff_blocked(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 2)
        with self.assertRaises(ReservationError):
            create_equipment(self.resident, 'X', total_quantity=1)
        with self.assertRaises(ReservationError):
            update_equipment(eq, self.resident, name='X')
        with self.assertRaises(ReservationError):
            adjust_equipment_stock(eq, self.resident, 1)
        with self.assertRaises(ReservationError):
            set_equipment_offline(eq, self.resident)
        with self.assertRaises(ReservationError):
            set_equipment_online(eq, self.resident)

    def test_11_offline_blocks_reservation(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 5)
        set_equipment_offline(eq, self.admin, reason='测试')
        with self.assertRaises(ReservationError) as ctx:
            create_reservation(
                user=self.resident, equipment=eq,
                reservation_date=date.today() + timedelta(days=2),
                time_slot=Reservation.TIME_SLOT_AFTERNOON, quantity=1
            )
        self.assertIn('下架', str(ctx.exception))

    def test_12_admin_views_accessible(self):
        eq = create_equipment(self.admin, '投影仪', '电子', 'd', 2)
        client = Client()
        client.login(username='admin_test', password='pass1234')
        urls = [
            reverse('equipment:admin_equipment_list'),
            reverse('equipment:admin_equipment_create'),
            reverse('equipment:admin_equipment_edit', kwargs={'pk': eq.id}),
            reverse('equipment:admin_equipment_adjust_stock', kwargs={'pk': eq.id}),
        ]
        for url in urls:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, msg=f'Failed: {url}')


class WaitlistTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_wl', 'a_wl@t.com', 'pass1234')
        self.user1 = User.objects.create_user('user_wl1', 'u1@t.com', 'pass1234')
        self.user2 = User.objects.create_user('user_wl2', 'u2@t.com', 'pass1234')
        self.user3 = User.objects.create_user('user_wl3', 'u3@t.com', 'pass1234')
        self.equipment = create_equipment(
            self.admin, '候补测试投影仪', '电子', '测试用', 2
        )
        self.tomorrow = date.today() + timedelta(days=1)
        self.time_slot = Reservation.TIME_SLOT_MORNING

    def test_01_full_stock_enters_waitlist(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )
        approve_reservation(r1, self.admin)

        with self.assertRaises(ReservationError):
            create_reservation(
                user=self.user2, equipment=self.equipment,
                reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
            )

        entry = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        self.assertEqual(entry.status, WaitlistEntry.STATUS_WAITING)
        self.assertEqual(entry.queue_position, 1)
        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.ACTION_WAITLIST_CREATE,
            target_type='waitlist',
            target_id=entry.id,
        ).exists())

    def test_02_auto_promote_on_cancel(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )
        approve_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        cancel_reservation(r1, self.user1)

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_PROMOTED)
        self.assertIsNotNone(w1.promoted_reservation)
        self.assertEqual(w1.promoted_reservation.status, Reservation.STATUS_PENDING)
        self.assertEqual(w1.promoted_reservation.user, self.user2)

        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.ACTION_WAITLIST_PROMOTE,
            target_type='waitlist',
            target_id=w1.id,
        ).exists())

    def test_03_auto_promote_preserves_order(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )
        approve_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        w2 = create_waitlist_entry(
            user=self.user3, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        cancel_reservation(r1, self.user1)

        w1.refresh_from_db()
        w2.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_PROMOTED)
        self.assertEqual(w2.status, WaitlistEntry.STATUS_PROMOTED)

        self.assertIsNotNone(w1.promoted_reservation)
        self.assertIsNotNone(w2.promoted_reservation)
        self.assertEqual(w1.promoted_reservation.user, self.user2)
        self.assertEqual(w2.promoted_reservation.user, self.user3)

    def test_03b_partial_release_only_promotes_first(self):
        eq = create_equipment(self.admin, '部分释放测试', '电子', 'd', 2)
        r1 = create_reservation(
            user=self.user1, equipment=eq,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        approve_reservation(r1, self.admin)
        r2 = create_reservation(
            user=self.user2, equipment=eq,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        approve_reservation(r2, self.admin)

        w1 = create_waitlist_entry(
            user=self.user3, equipment=eq,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        w2 = create_waitlist_entry(
            user=self.user1, equipment=eq,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        cancel_reservation(r1, self.user1)

        w1.refresh_from_db()
        w2.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_PROMOTED)
        self.assertEqual(w2.status, WaitlistEntry.STATUS_WAITING)

    def test_04_over_quantity_waitlist_stays(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        approve_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )

        available = get_available_quantity(self.equipment, self.tomorrow, self.time_slot)
        self.assertEqual(available, 1)

        r2 = create_reservation(
            user=self.user3, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        approve_reservation(r2, self.admin)

        cancel_reservation(r1, self.user1)

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_WAITING)

    def test_05_non_owner_cancel_fails(self):
        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        with self.assertRaises(ReservationError) as ctx:
            cancel_waitlist_entry(w1, self.user3)
        self.assertIn('只能取消自己的候补', str(ctx.exception))

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_WAITING)

    def test_06_admin_skip_then_promote_next(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )
        approve_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        w2 = create_waitlist_entry(
            user=self.user3, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        skip_waitlist_entry(w1, self.admin)
        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_SKIPPED)

        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.ACTION_WAITLIST_SKIP,
            target_type='waitlist',
            target_id=w1.id,
        ).exists())

        cancel_reservation(r1, self.user1)

        w2.refresh_from_db()
        self.assertEqual(w2.status, WaitlistEntry.STATUS_PROMOTED)
        self.assertIsNotNone(w2.promoted_reservation)

    def test_07_admin_reject_waitlist(self):
        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        reject_waitlist_entry(w1, self.admin, reason='不符合条件')

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_REJECTED)
        self.assertEqual(w1.reject_reason, '不符合条件')

        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.ACTION_WAITLIST_REJECT,
            target_type='waitlist',
            target_id=w1.id,
        ).exists())

    def test_08_admin_manual_promote(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        approve_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        cancel_reservation(r1, self.user1)

        promote_waitlist_entry(w1, self.admin)

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_PROMOTED)
        self.assertIsNotNone(w1.promoted_reservation)

    def test_09_auto_promote_on_reject_reservation(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        reject_reservation(r1, self.admin, reason='测试')

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_PROMOTED)

    def test_10_auto_promote_on_return(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )
        approve_reservation(r1, self.admin)
        pick_up_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        return_reservation(r1, self.admin, note='正常归还')

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_PROMOTED)

    def test_11_duplicate_waitlist_blocked(self):
        create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        with self.assertRaises(ReservationError) as ctx:
            create_waitlist_entry(
                user=self.user2, equipment=self.equipment,
                reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
            )
        self.assertIn('重复加入', str(ctx.exception))

    def test_12_cancel_own_waitlist(self):
        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        cancel_waitlist_entry(w1, self.user2)

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_CANCELLED)

        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.ACTION_WAITLIST_CANCEL,
            target_type='waitlist',
            target_id=w1.id,
        ).exists())

    def test_13_non_staff_cannot_skip(self):
        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )

        with self.assertRaises(ReservationError):
            skip_waitlist_entry(w1, self.user1)

    def test_14_promote_insufficient_stock_fails(self):
        r1 = create_reservation(
            user=self.user1, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )
        approve_reservation(r1, self.admin)

        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=2
        )

        with self.assertRaises(ReservationError) as ctx:
            promote_waitlist_entry(w1, self.admin)
        self.assertIn('库存不足', str(ctx.exception))

        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_WAITING)

    def test_15_waitlist_views_accessible(self):
        client = Client()
        client.login(username='admin_wl', password='pass1234')
        resp = client.get(reverse('equipment:admin_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_16_waitlist_join_view(self):
        client = Client()
        client.login(username='user_wl1', password='pass1234')
        resp = client.post(reverse('equipment:waitlist_join', kwargs={'pk': self.equipment.pk}), {
            'reservation_date': self.tomorrow.strftime('%Y-%m-%d'),
            'time_slot': self.time_slot,
            'quantity': 1,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(WaitlistEntry.objects.filter(user=self.user1).exists())

    def test_17_waitlist_cancel_view_owner(self):
        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        client = Client()
        client.login(username='user_wl2', password='pass1234')
        resp = client.post(reverse('equipment:waitlist_cancel', kwargs={'pk': w1.pk}))
        self.assertEqual(resp.status_code, 302)
        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_CANCELLED)

    def test_18_waitlist_cancel_view_non_owner_fails(self):
        w1 = create_waitlist_entry(
            user=self.user2, equipment=self.equipment,
            reservation_date=self.tomorrow, time_slot=self.time_slot, quantity=1
        )
        client = Client()
        client.login(username='user_wl3', password='pass1234')
        resp = client.post(reverse('equipment:waitlist_cancel', kwargs={'pk': w1.pk}))
        w1.refresh_from_db()
        self.assertEqual(w1.status, WaitlistEntry.STATUS_WAITING)
