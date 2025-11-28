from django.db import models
from datetime import time, date
from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from django.db.models import Sum, Q


class Employee(models.Model):
    STATUS_CHOICES = (
        ('active', 'ทำงานอยู่'),
        ('inactive', 'ออกแล้ว'),
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_profile',
        verbose_name="เชื่อมกับ User (สำหรับให้ล็อกอินดูสลิป)"
    )
    address = models.TextField(
        blank=True,
        null=True,
        verbose_name="ที่อยู่ติดต่อ"
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="เบอร์โทรศัพท์"
    )
    code = models.CharField(max_length=50, unique=True, verbose_name="รหัสพนักงาน")
    first_name = models.CharField(max_length=100, verbose_name="ชื่อ")
    last_name = models.CharField(max_length=100, verbose_name="นามสกุล")
    position = models.CharField(max_length=100, blank=True, null=True, verbose_name="ตำแหน่ง")
    department = models.CharField(max_length=100, blank=True, null=True, verbose_name="แผนก")

    hire_date = models.DateField(blank=True, null=True, verbose_name="วันที่เริ่มงาน")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    base_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="ฐานเงินเดือน / เดือน"
    )

    bank_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="ธนาคาร")
    bank_account_no = models.CharField(max_length=50, blank=True, null=True, verbose_name="เลขบัญชี")

    citizen_id = models.CharField(max_length=20, blank=True, null=True, verbose_name="เลขบัตรประชาชน")

    def __str__(self):
        return f"{self.code} - {self.first_name} {self.last_name}"
    
class EmployeeTaxProfile(models.Model):
    """
    เก็บข้อมูลสิทธิ์ลดหย่อนภาษีของพนักงาน ‘รายปี’
    เอาไว้ใช้เวลาคำนวณภาษีหัก ณ ที่จ่าย (WHT)
    """
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name='tax_profile',
        verbose_name="พนักงาน"
    )

    # สถานะครอบครัว (เวอร์ชันง่าย ๆ)
    is_married = models.BooleanField(default=False, verbose_name="สมรส")
    spouse_has_income = models.BooleanField(default=False, verbose_name="คู่สมรสมีรายได้")

    children_count = models.PositiveIntegerField(default=0, verbose_name="จำนวนบุตรที่ใช้สิทธิ์")

    # ลดหย่อนยอดรวมต่อปี (ยังไม่ลงรายละเอียดตามกฎหมายจริงทุกข้อ)
    insurance_deduction = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="เบี้ยประกันชีวิต/สุขภาพ (ต่อปี)"
    )
    provident_fund = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="กองทุนสำรองเลี้ยงชีพ/กองทุนรวม (ต่อปี)"
    )
    home_loan_interest = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="ดอกเบี้ยกู้ซื้อบ้าน (ต่อปี)"
    )
    other_deduction = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="ค่าลดหย่อนอื่น ๆ (ต่อปี)"
    )

    def __str__(self):
        return f"Tax Profile - {self.employee}"

    def get_basic_allowance(self) -> Decimal:
        """
        ค่าลดหย่อนพื้นฐานตามตัวบุคคล (ตัวเลขสมมุติ/เบื้องต้น)
        คุณจะไปปรับให้ตรงกฎหมายจริงทีหลังก็ได้
        """
        total = Decimal("60000.00")  # ค่าลดหย่อนส่วนตัว

        if self.is_married and not self.spouse_has_income:
            total += Decimal("60000.00")  # คู่สมรสไม่มีรายได้ (สมมุติ)

        # บุตร สมมุติ 30,000 ต่อคน
        total += Decimal("30000.00") * Decimal(self.children_count)
        return total

    def get_total_deduction(self) -> Decimal:
        """
        รวมค่าลดหย่อน 'ทั้งหมดต่อปี'
        = พื้นฐานบุคคล + คู่สมรส + บุตร + เบี้ยประกัน + กองทุน + ดอกเบี้ยบ้าน + อื่น ๆ
        """
        total = self.get_basic_allowance()
        total += (self.insurance_deduction or Decimal("0"))
        total += (self.provident_fund or Decimal("0"))
        total += (self.home_loan_interest or Decimal("0"))
        total += (self.other_deduction or Decimal("0"))
        return total
    
def calculate_thai_personal_income_tax(annual_taxable_income: Decimal) -> Decimal:
    """
    คำนวณภาษีบุคคลธรรมดาทั้งปีแบบขั้นบันได (เวอร์ชันง่าย ๆ)
    - ตัวเลขขั้นอัตราสามารถปรับเองได้ภายหลัง
    """
    income = max(Decimal("0.00"), annual_taxable_income)

    brackets = [
        (Decimal("150000"), Decimal("0.00")),   # 0 - 150,000  : 0%
        (Decimal("300000"), Decimal("0.05")),   # 150,001 - 300,000 : 5%
        (Decimal("500000"), Decimal("0.10")),   # 300,001 - 500,000 : 10%
        (Decimal("750000"), Decimal("0.15")),   # 500,001 - 750,000 : 15%
        (Decimal("1000000"), Decimal("0.20")),  # 750,001 - 1,000,000 : 20%
        (Decimal("2000000"), Decimal("0.25")),  # 1,000,001 - 2,000,000 : 25%
        (Decimal("5000000"), Decimal("0.30")),  # 2,000,001 - 5,000,000 : 30%
        (None, Decimal("0.35")),                # > 5,000,000 : 35%
    ]

    tax = Decimal("0.00")
    prev_limit = Decimal("0.00")

    for limit, rate in brackets:
        if limit is None:
            # ชั้นสุดท้าย
            taxable_part = income - prev_limit
            if taxable_part > 0:
                tax += taxable_part * rate
            break

        if income > limit:
            taxable_part = limit - prev_limit
            tax += taxable_part * rate
            prev_limit = limit
        else:
            taxable_part = income - prev_limit
            if taxable_part > 0:
                tax += taxable_part * rate
            break

    return tax.quantize(Decimal("0.01"))
    
class PayrollPeriod(models.Model):
    month = models.IntegerField()   # 1-12
    year = models.IntegerField()
    start_date = models.DateField()
    end_date = models.DateField()

    is_closed = models.BooleanField(default=False, verbose_name="ปิดรอบแล้วหรือไม่")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_payroll_periods'
    )

    class Meta:
        unique_together = ('month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"งวดเงินเดือน {self.month:02d}/{self.year}"

    def generate_payslips(self):
        """
        สร้าง payslip ให้พนักงานทุกคนที่ active
        + เติมรายการฐานเงินเดือนอัตโนมัติ
        """
        from .models import Employee, Payslip, PayslipItem, EarningType  # import วนในฟังก์ชันกัน circular

        base_type, _ = EarningType.objects.get_or_create(
            code='BASE_SALARY',
            defaults={
                'name': 'เงินเดือนพื้นฐาน',
                'is_taxable': True,
                'is_ssf': True,
            }
        )

        active_emps = Employee.objects.filter(status='active')

        for emp in active_emps:
            payslip, created = Payslip.objects.get_or_create(
                employee=emp,
                period=self,
            )

            # ถ้าเพิ่งสร้าง payslip ใหม่ ให้เติมฐานเงินเดือนเข้าไป
            if created:
                PayslipItem.objects.create(
                    payslip=payslip,
                    item_type='earning',
                    earning_type=base_type,
                    name='ฐานเงินเดือน',
                    amount=emp.base_salary,
                )

            # คำนวณยอดรวมอัพเดต
            payslip.recalc_totals()

class EarningType(models.Model):
    """ประเภทรายรับ เช่น เงินเดือน, OT, ค่าคอม"""
    name = models.CharField(max_length=100, verbose_name="ชื่อรายรับ")
    code = models.CharField(max_length=50, unique=True, verbose_name="รหัส")
    is_taxable = models.BooleanField(default=True, verbose_name="นำไปคำนวณภาษีไหม")
    is_ssf = models.BooleanField(default=True, verbose_name="นำไปคำนวณประกันสังคมไหม")

    def __str__(self):
        return self.name


class DeductionType(models.Model):
    """ประเภทรายหัก เช่น ภาษี, ประกันสังคม, เงินกู้"""
    name = models.CharField(max_length=100, verbose_name="ชื่อรายหัก")
    code = models.CharField(max_length=50, unique=True, verbose_name="รหัส")
    is_tax = models.BooleanField(default=False, verbose_name="เป็นภาษีไหม")
    is_ssf = models.BooleanField(default=False, verbose_name="เป็นประกันสังคมไหม")

    def __str__(self):
        return self.name


class Payslip(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payslips')
    period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name='payslips')

    gross_income = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="รายรับรวม")
    total_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="รายหักรวม")
    net_income = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="รับสุทธิ")

    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'period')

    def __str__(self):
        return f"Payslip {self.employee} - {self.period}"

    def recalc_totals(self):
        earnings = self.items.filter(item_type='earning').aggregate(
            s=Sum('amount')
        )['s'] or Decimal('0')

        deductions = self.items.filter(item_type='deduction').aggregate(
            s=Sum('amount')
        )['s'] or Decimal('0')

        self.gross_income = earnings
        self.total_deduction = deductions
        self.net_income = earnings - deductions
        self.save(update_fields=['gross_income', 'total_deduction', 'net_income'])

    # ====== เพิ่มฟังก์ชันใหม่จากตรงนี้ลงไป ======

    def _get_or_create_deduction_type(self, code, name, is_tax=False, is_ssf=False):
        from .models import DeductionType  # กัน circular import เวลาถูกเรียกจากที่อื่น
        dt, _ = DeductionType.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'is_tax': is_tax,
                'is_ssf': is_ssf,
            }
        )
        return dt

    def calculate_social_security_amount(self):
        """
        ประกันสังคมไทย (เวอร์ชันเบื้องต้น):
        5% ของฐานรายได้ แต่คิดสูงสุดจากเงินเดือน 15,000 → max 750 บาท
        """
        base = self.gross_income or Decimal('0')
        max_base = Decimal('15000')
        used_base = min(base, max_base)
        amount = (used_base * Decimal('0.05')).quantize(Decimal('0.01'))
        return amount

    def calculate_withholding_tax_amount(self):
        """
        ภาษีหัก ณ ที่จ่ายแบบ 'จำลองทั้งปีแล้วเฉลี่ยรายเดือน'

        ขั้นตอน:
        1) ใช้รายได้สุทธิจากรายรับ (self.gross_income) ของเดือนนี้
        2) สมมุติว่ารายได้ลักษณะเดียวกันนี้ทั้งปี -> annual_income
        3) อ่านโปรไฟล์ลดหย่อนภาษีจาก EmployeeTaxProfile (ถ้ามี)
        4) หักค่าลดหย่อนทั้งหมด -> ได้ annual_taxable_income
        5) คำนวณภาษีทั้งปีด้วย calculate_thai_personal_income_tax(...)
        6) หาร 12 กลายเป็นภาษีต่อเดือน (WHT)
        """
        from .models import EmployeeTaxProfile  # กัน circular ถ้าโดน import ซ้อน

        # ถ้ารายรับรวมเดือนนี้ยังเป็น 0 ก็ไม่ต้องหักภาษี
        monthly_gross = self.gross_income or Decimal("0.00")
        if monthly_gross <= 0:
            return Decimal("0.00")

        # 1) ประมาณรายได้ทั้งปี
        annual_income = monthly_gross * Decimal("12.00")

        # 2) ดึง profile ลดหย่อน (ถ้าไม่มีให้ถือว่าแค่มีลดหย่อนพื้นฐาน)
        tax_profile = getattr(self.employee, "tax_profile", None)
        if tax_profile:
            total_deduction = tax_profile.get_total_deduction()
        else:
            # ไม่มี profile -> ใช้ค่าลดหย่อนส่วนตัวพื้นฐานสมมุติ เช่น 60,000
            total_deduction = Decimal("60000.00")

        taxable_base = annual_income - total_deduction
        if taxable_base <= 0:
            return Decimal("0.00")

        # 3) ภาษีทั้งปี
        annual_tax = calculate_thai_personal_income_tax(taxable_base)

        # 4) เฉลี่ยรายเดือน
        monthly_tax = (annual_tax / Decimal("12.00")).quantize(Decimal("0.01"))
        return monthly_tax

    def update_social_security_item(self):
        """
        สร้าง/อัปเดตรายการ 'ประกันสังคม' ใน payslip นี้
        """
        from .models import PayslipItem

        dt = self._get_or_create_deduction_type(
            code='SOCIAL_SEC',
            name='ประกันสังคม',
            is_tax=False,
            is_ssf=True,
        )
        amount = self.calculate_social_security_amount()

        item, created = PayslipItem.objects.get_or_create(
            payslip=self,
            item_type='deduction',
            deduction_type=dt,
            defaults={
                'name': 'ประกันสังคม',
                'amount': amount,
            }
        )
        if not created:
            item.name = 'ประกันสังคม'
            item.amount = amount
            item.save(update_fields=['name', 'amount'])

        # คำนวณยอดรวมใหม่
        self.recalc_totals()

    def update_withholding_tax_item(self):
        """
        สร้าง/อัปเดตรายการ 'ภาษีหัก ณ ที่จ่าย' ใน payslip นี้
        """
        from .models import PayslipItem

        dt = self._get_or_create_deduction_type(
            code='WHT',
            name='ภาษีหัก ณ ที่จ่าย',
            is_tax=True,
            is_ssf=False,
        )
        amount = self.calculate_withholding_tax_amount()

        item, created = PayslipItem.objects.get_or_create(
            payslip=self,
            item_type='deduction',
            deduction_type=dt,
            defaults={
                'name': 'ภาษีหัก ณ ที่จ่าย',
                'amount': amount,
            }
        )
        if not created:
            item.name = 'ภาษีหัก ณ ที่จ่าย'
            item.amount = amount
            item.save(update_fields=['name', 'amount'])

        # คำนวณยอดรวมใหม่
        self.recalc_totals()

    def update_social_security_and_tax(self):
        """
        helper เอาไว้เรียกทีเดียวทั้งประกันสังคม + ภาษี
        """
        self.recalc_totals()  # ให้ gross_income ใช้ค่าล่าสุดก่อน
        self.update_social_security_item()
        self.update_withholding_tax_item()

class PayslipItem(models.Model):
    TYPE_CHOICES = (
        ('earning', 'รายรับ'),
        ('deduction', 'รายหัก'),
    )
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=20, choices=TYPE_CHOICES)

    earning_type = models.ForeignKey(EarningType, on_delete=models.SET_NULL, null=True, blank=True)
    deduction_type = models.ForeignKey(DeductionType, on_delete=models.SET_NULL, null=True, blank=True)

    name = models.CharField(max_length=100, verbose_name="ชื่อรายการ")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="จำนวนเงิน")

    def __str__(self):
        direction = "+" if self.item_type == 'earning' else "-"
        return f"{direction}{self.amount} {self.name}"
    
class CompanySetting(models.Model):
    """
    ตั้งค่าทั่วไปของบริษัท (ใช้ 1 record)
    - เวลาเริ่มงานปกติ
    - กี่นาทีหลังจากนั้นถือว่าสาย
    """
    name = models.CharField(max_length=100, default="default", unique=True)
    work_start_time = models.TimeField(default=time(9, 0), verbose_name="เวลาเริ่มงานปกติ")
    late_after_minutes = models.PositiveIntegerField(default=15, verbose_name="มาสายเกิน (นาที)")

    def __str__(self):
        return "Company Settings"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            name="default",
            defaults={
                "work_start_time": time(9, 0),
                "late_after_minutes": 15,
            }
        )
        return obj


class Holiday(models.Model):
    """
    วันหยุดนักขัตฤกษ์ / วันหยุดบริษัท
    """
    date = models.DateField(unique=True)
    name = models.CharField(max_length=200)
    is_public_holiday = models.BooleanField(default=True, verbose_name="เป็นวันหยุดนักขัตฤกษ์")

    def __str__(self):
        return f"{self.date} - {self.name}"


class LeaveType(models.Model):
    """
    ประเภทการลา เช่น ลาป่วย, ลากิจ, ลาพักร้อน
    """
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    max_days_per_year = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="จำนวนวันต่อปีที่ลาได้"
    )
    is_paid = models.BooleanField(default=True, verbose_name="นับเป็นวันลาพร้อมเงินเดือน")

    def __str__(self):
        return self.name


class LeaveRecord(models.Model):
    """
    การลาของพนักงานแต่ละครั้ง
    """
    STATUS_CHOICES = (
        ('pending', 'รออนุมัติ'),
        ('approved', 'อนุมัติ'),
        ('rejected', 'ไม่อนุมัติ'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leaves')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # จำนวนวัน (เช่น 1, 0.5)
    reason = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.start_date} - {self.end_date})"

    def is_effective_on(self, target_date: date) -> bool:
        return (
            self.status == 'approved'
            and self.start_date <= target_date <= self.end_date
        )


class AttendanceRecord(models.Model):
    """
    การลงเวลาทำงานต่อวันต่อคน (มาจาก CSV หรือกรอกมือ)
    """
    STATUS_CHOICES = (
        ('present', 'มาทำงาน'),
        ('late', 'มาสาย'),
        ('absent', 'ขาด'),
        ('leave', 'ลา'),
        ('holiday', 'วันหยุด'),
    )
    SOURCE_CHOICES = (
        ('csv', 'นำเข้าจาก CSV'),
        ('manual', 'กรอกด้วยมือ'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendances')
    work_date = models.DateField()
    check_in = models.TimeField(blank=True, null=True)
    check_out = models.TimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    remark = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'work_date')
        ordering = ['-work_date', 'employee__code']

    def __str__(self):
        return f"{self.work_date} - {self.employee.code} ({self.status})"

    def auto_calculate_status(self):
        """
        ใช้กฎจาก CompanySetting + Holiday + LeaveRecord
        เพื่อหาว่าวันนี้ควรเป็นสถานะอะไร
        """
        settings = CompanySetting.get_solo()

        # 1) ถ้าเป็นวันหยุด
        if Holiday.objects.filter(date=self.work_date).exists():
            self.status = 'holiday'
            return

        # 2) ถ้ามีการลาที่อนุมัติ
        leave_qs = LeaveRecord.objects.filter(
            employee=self.employee,
            status='approved',
            start_date__lte=self.work_date,
            end_date__gte=self.work_date,
        )
        if leave_qs.exists():
            self.status = 'leave'
            return

        # 3) ถ้าไม่มีเวลาเข้าเลย -> ขาด
        if not self.check_in:
            self.status = 'absent'
            return

        # 4) ตรวจสายจากเวลาเข้าเทียบกับ work_start_time + late_after_minutes
        from datetime import datetime, timedelta

        wst = settings.work_start_time
        late_threshold = (datetime.combine(self.work_date, wst)
                          + timedelta(minutes=settings.late_after_minutes)).time()

        if self.check_in > late_threshold:
            self.status = 'late'
        else:
            self.status = 'present'
