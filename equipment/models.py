from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, time


class Equipment(models.Model):
    STATUS_NORMAL = 'normal'
    STATUS_DAMAGED = 'damaged'
    STATUS_CHOICES = [
        (STATUS_NORMAL, '正常'),
        (STATUS_DAMAGED, '损坏'),
    ]

    name = models.CharField('器材名称', max_length=100)
    description = models.TextField('描述', blank=True)
    total_quantity = models.IntegerField('总库存', default=1)
    available_quantity = models.IntegerField('可用库存', default=1)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_NORMAL)
    category = models.CharField('分类', max_length=50, blank=True)
    image_url = models.URLField('图片链接', blank=True)
    created_at = models.DateTimeField('创建时间', default=timezone.now)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '器材'
        verbose_name_plural = '器材'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk is None:
            self.available_quantity = self.total_quantity
        super().save(*args, **kwargs)


class Reservation(models.Model):
    TIME_SLOT_MORNING = 'morning'
    TIME_SLOT_AFTERNOON = 'afternoon'
    TIME_SLOT_CHOICES = [
        (TIME_SLOT_MORNING, '上午 (8:00-12:00)'),
        (TIME_SLOT_AFTERNOON, '下午 (14:00-18:00)'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CANCELLED = 'cancelled'
    STATUS_PICKED = 'picked'
    STATUS_RETURNED = 'returned'
    STATUS_OVERDUE = 'overdue'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待审批'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已拒绝'),
        (STATUS_CANCELLED, '已取消'),
        (STATUS_PICKED, '已领取'),
        (STATUS_RETURNED, '已归还'),
        (STATUS_OVERDUE, '已逾期'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='预约人', related_name='reservations')
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, verbose_name='器材', related_name='reservations')
    reservation_date = models.DateField('预约日期')
    time_slot = models.CharField('时段', max_length=20, choices=TIME_SLOT_CHOICES)
    quantity = models.IntegerField('数量', default=1)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    purpose = models.TextField('用途', blank=True)

    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    verbose_name='审批人', related_name='approved_reservations')
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.TextField('拒绝原因', blank=True)

    picked_at = models.DateTimeField('领取时间', null=True, blank=True)
    returned_at = models.DateTimeField('归还时间', null=True, blank=True)
    return_note = models.TextField('归还备注', blank=True)

    created_at = models.DateTimeField('创建时间', default=timezone.now)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '预约'
        verbose_name_plural = '预约'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} - {self.equipment.name} - {self.reservation_date}'

    def is_overdue(self):
        if self.status in [self.STATUS_APPROVED, self.STATUS_PICKED]:
            now = timezone.now().date()
            if self.reservation_date < now:
                return True
            elif self.reservation_date == now:
                now_time = timezone.now().time()
                if self.time_slot == self.TIME_SLOT_MORNING and now_time > time(12, 0):
                    return True
                elif self.time_slot == self.TIME_SLOT_AFTERNOON and now_time > time(18, 0):
                    return True
        return False


class DamageRecord(models.Model):
    STATUS_REPORTED = 'reported'
    STATUS_PROCESSING = 'processing'
    STATUS_RESOLVED = 'resolved'
    STATUS_CHOICES = [
        (STATUS_REPORTED, '已上报'),
        (STATUS_PROCESSING, '处理中'),
        (STATUS_RESOLVED, '已处理'),
    ]

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, verbose_name='器材', related_name='damage_records')
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='上报人', related_name='reported_damages')
    description = models.TextField('损坏描述')
    quantity = models.IntegerField('损坏数量', default=1)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_REPORTED)
    handled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='处理人', related_name='handled_damages')
    handle_note = models.TextField('处理备注', blank=True)
    handled_at = models.DateTimeField('处理时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', default=timezone.now)

    class Meta:
        verbose_name = '损坏记录'
        verbose_name_plural = '损坏记录'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.equipment.name} - {self.get_status_display()}'


class AuditLog(models.Model):
    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    ACTION_DELETE = 'delete'
    ACTION_APPROVE = 'approve'
    ACTION_REJECT = 'reject'
    ACTION_CANCEL = 'cancel'
    ACTION_PICK = 'pick'
    ACTION_RETURN = 'return'
    ACTION_DAMAGE = 'damage'
    ACTION_OVERDUE = 'overdue'
    ACTION_CHOICES = [
        (ACTION_CREATE, '创建'),
        (ACTION_UPDATE, '更新'),
        (ACTION_DELETE, '删除'),
        (ACTION_APPROVE, '批准'),
        (ACTION_REJECT, '拒绝'),
        (ACTION_CANCEL, '取消'),
        (ACTION_PICK, '领取'),
        (ACTION_RETURN, '归还'),
        (ACTION_DAMAGE, '损坏'),
        (ACTION_OVERDUE, '逾期'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='操作人')
    action = models.CharField('操作类型', max_length=20, choices=ACTION_CHOICES)
    target_type = models.CharField('目标类型', max_length=50)
    target_id = models.IntegerField('目标ID')
    details = models.TextField('详情', blank=True)
    ip_address = models.GenericIPAddressField('IP地址', null=True, blank=True)
    created_at = models.DateTimeField('操作时间', default=timezone.now)

    class Meta:
        verbose_name = '审计记录'
        verbose_name_plural = '审计记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f'{self.get_action_display()} - {self.target_type} #{self.target_id}'


class StockFlow(models.Model):
    FLOW_IN = 'in'
    FLOW_OUT = 'out'
    FLOW_TYPE_CHOICES = [
        (FLOW_IN, '入库'),
        (FLOW_OUT, '出库'),
    ]

    FLOW_REASON_PURCHASE = 'purchase'
    FLOW_REASON_RESERVE = 'reserve'
    FLOW_REASON_RETURN = 'return'
    FLOW_REASON_DAMAGE = 'damage'
    FLOW_REASON_ADJUST = 'adjust'
    FLOW_REASON_CHOICES = [
        (FLOW_REASON_PURCHASE, '采购入库'),
        (FLOW_REASON_RESERVE, '预约出库'),
        (FLOW_REASON_RETURN, '归还入库'),
        (FLOW_REASON_DAMAGE, '损坏出库'),
        (FLOW_REASON_ADJUST, '库存调整'),
    ]

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, verbose_name='器材', related_name='stock_flows')
    flow_type = models.CharField('流动类型', max_length=10, choices=FLOW_TYPE_CHOICES)
    flow_reason = models.CharField('变动原因', max_length=20, choices=FLOW_REASON_CHOICES)
    quantity = models.IntegerField('数量')
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True,
                                    verbose_name='关联预约', related_name='stock_flows')
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='操作人')
    note = models.TextField('备注', blank=True)
    balance_after = models.IntegerField('变动后库存')
    created_at = models.DateTimeField('创建时间', default=timezone.now)

    class Meta:
        verbose_name = '库存流水'
        verbose_name_plural = '库存流水'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.equipment.name} - {self.get_flow_type_display()} - {self.quantity}'
