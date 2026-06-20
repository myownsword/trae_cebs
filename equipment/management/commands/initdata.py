from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from equipment.models import Equipment, Reservation, DamageRecord, StockFlow, AuditLog
from equipment.services import create_reservation, approve_reservation, pick_up_reservation


class Command(BaseCommand):
    help = '初始化示例数据'

    def handle(self, *args, **options):
        self.stdout.write('开始初始化示例数据...')

        if User.objects.filter(username='admin').exists():
            self.stdout.write(self.style.WARNING('数据已存在，跳过初始化'))
            return

        admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123'
        )
        self.stdout.write(self.style.SUCCESS('创建管理员用户: admin / admin123'))

        zhangsan = User.objects.create_user(
            username='zhangsan',
            email='zhangsan@example.com',
            password='zs123456',
            first_name='张',
            last_name='三'
        )
        self.stdout.write(self.style.SUCCESS('创建居民用户: zhangsan / zs123456'))

        lisi = User.objects.create_user(
            username='lisi',
            email='lisi@example.com',
            password='ls123456',
            first_name='李',
            last_name='四'
        )
        self.stdout.write(self.style.SUCCESS('创建居民用户: lisi / ls123456'))

        wangwu = User.objects.create_user(
            username='wangwu',
            email='wangwu@example.com',
            password='ww123456',
            first_name='王',
            last_name='五'
        )
        self.stdout.write(self.style.SUCCESS('创建居民用户: wangwu / ww123456'))

        equipments_data = [
            {'name': '折叠桌椅套装', 'category': '户外活动', 'total_quantity': 10,
             'description': '便携折叠桌椅，适合户外聚餐、活动使用'},
            {'name': '羽毛球拍套装', 'category': '运动器材', 'total_quantity': 8,
             'description': '含2支球拍和3个羽毛球'},
            {'name': '篮球', 'category': '运动器材', 'total_quantity': 5,
             'description': '标准7号篮球'},
            {'name': '帐篷', 'category': '户外活动', 'total_quantity': 3,
             'description': '4人帐篷，防水防风'},
            {'name': '烧烤架', 'category': '户外活动', 'total_quantity': 4,
             'description': '木炭烧烤架，适合5-8人使用'},
            {'name': '急救包', 'category': '应急用品', 'total_quantity': 6,
             'description': '家用急救包，含常用医疗用品'},
            {'name': '电动螺丝刀', 'category': '工具', 'total_quantity': 3,
             'description': '充电式电动螺丝刀套装'},
            {'name': '梯子', 'category': '工具', 'total_quantity': 2,
             'description': '5步铝合金折叠梯'},
            {'name': '投影仪', 'category': '电子设备', 'total_quantity': 2,
             'description': '家用投影仪，1080P分辨率'},
            {'name': '音箱', 'category': '电子设备', 'total_quantity': 4,
             'description': '便携蓝牙音箱'},
        ]

        equipments = []
        for data in equipments_data:
            eq = Equipment.objects.create(**data)
            equipments.append(eq)
            StockFlow.objects.create(
                equipment=eq,
                flow_type=StockFlow.FLOW_IN,
                flow_reason=StockFlow.FLOW_REASON_PURCHASE,
                quantity=eq.total_quantity,
                operator=admin_user,
                note='初始库存',
                balance_after=eq.total_quantity,
            )
        self.stdout.write(self.style.SUCCESS(f'创建了 {len(equipments)} 种器材'))

        today = timezone.now().date()

        r1 = create_reservation(
            user=zhangsan,
            equipment=equipments[0],
            reservation_date=today + timedelta(days=1),
            time_slot=Reservation.TIME_SLOT_AFTERNOON,
            quantity=2,
            purpose='小区活动使用',
        )
        approve_reservation(r1, admin_user)
        self.stdout.write(self.style.SUCCESS('创建预约1：张三预约折叠桌椅套装（已批准）'))

        r2 = create_reservation(
            user=lisi,
            equipment=equipments[2],
            reservation_date=today + timedelta(days=2),
            time_slot=Reservation.TIME_SLOT_MORNING,
            quantity=1,
            purpose='周末打球',
        )
        approve_reservation(r2, admin_user)
        pick_up_reservation(r2, admin_user)
        self.stdout.write(self.style.SUCCESS('创建预约2：李四预约篮球（已领取）'))

        r3 = create_reservation(
            user=wangwu,
            equipment=equipments[1],
            reservation_date=today + timedelta(days=1),
            time_slot=Reservation.TIME_SLOT_MORNING,
            quantity=1,
            purpose='晨练',
        )
        self.stdout.write(self.style.SUCCESS('创建预约3：王五预约羽毛球拍套装（待审批）'))

        r4 = create_reservation(
            user=zhangsan,
            equipment=equipments[3],
            reservation_date=today - timedelta(days=2),
            time_slot=Reservation.TIME_SLOT_MORNING,
            quantity=1,
            purpose='露营',
        )
        approve_reservation(r4, admin_user)
        r4.status = Reservation.STATUS_OVERDUE
        r4.save()
        self.stdout.write(self.style.SUCCESS('创建预约4：张三预约帐篷（模拟逾期）'))

        self.stdout.write(self.style.SUCCESS('示例数据初始化完成！'))
        self.stdout.write('')
        self.stdout.write('测试账号：')
        self.stdout.write('  管理员: admin / admin123')
        self.stdout.write('  居民: zhangsan / zs123456')
        self.stdout.write('  居民: lisi / ls123456')
        self.stdout.write('  居民: wangwu / ww123456')
