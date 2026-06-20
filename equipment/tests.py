from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date, timedelta
from .models import Equipment, Reservation, StockFlow, AuditLog
from .services import (
    create_equipment, update_equipment, adjust_equipment_stock,
    set_equipment_offline, set_equipment_online,
    get_equipment_occupied_quantity, create_reservation,
    approve_reservation, ReservationError
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
