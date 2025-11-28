from django import forms
from .models import (
    CompanySetting, 
    Holiday, 
    LeaveType, 
    LeaveRecord,
    PayrollPeriod, 
    Employee,
    PayrollPeriod,
    EmployeeTaxProfile,
)

class AttendanceUploadForm(forms.Form):
    file = forms.FileField(label="ไฟล์ CSV")


class CompanySettingForm(forms.ModelForm):
    class Meta:
        model = CompanySetting
        fields = ['work_start_time', 'late_after_minutes']
        labels = {
            'work_start_time': 'เวลาเริ่มงานปกติ',
            'late_after_minutes': 'ถือว่าสายเมื่อเลย (นาที)',
        }
        widgets = {
            'work_start_time': forms.TimeInput(
                attrs={'type': 'time', 'class': 'form-control form-control-sm'}
            ),
            'late_after_minutes': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'min': 0}
            ),
        }


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ['date', 'name', 'is_public_holiday']
        labels = {
            'date': 'วันที่',
            'name': 'ชื่อวันหยุด',
            'is_public_holiday': 'เป็นวันหยุดนักขัตฤกษ์',
        }
        widgets = {
            'date': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control form-control-sm'}
            ),
            'name': forms.TextInput(
                attrs={'class': 'form-control form-control-sm'}
            ),
            'is_public_holiday': forms.CheckboxInput(
                attrs={'class': 'form-check-input'}
            ),
        }

class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ['code', 'name', 'max_days_per_year', 'is_paid']
        labels = {
            'code': 'รหัส',
            'name': 'ชื่อประเภทลา',
            'max_days_per_year': 'สิทธิ์วันลาต่อปี',
            'is_paid': 'ลาพร้อมเงินเดือน',
        }
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'max_days_per_year': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.5'}),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class LeaveRecordForm(forms.ModelForm):
    class Meta:
        model = LeaveRecord
        fields = ['employee', 'leave_type', 'start_date', 'end_date', 'days', 'reason', 'status']
        labels = {
            'employee': 'พนักงาน',
            'leave_type': 'ประเภทการลา',
            'start_date': 'วันที่เริ่มลา',
            'end_date': 'วันที่สิ้นสุด',
            'days': 'จำนวนวันลา',
            'reason': 'เหตุผล',
            'status': 'สถานะ',
        }
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'leave_type': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'days': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.5'}),
            'reason': forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2}),
            'status': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        days = cleaned.get('days')

        if start and end and start > end:
            self.add_error('end_date', 'วันที่สิ้นสุดต้องไม่น้อยกว่าวันที่เริ่มลา')

        # ถ้า days ว่างหรือ 0 ให้ auto คำนวณเป็นจำนวนวัน (เต็มวัน)
        if start and end and (days is None or days == 0):
            cleaned['days'] = (end - start).days + 1

        return cleaned
    
class PayrollRunForm(forms.Form):
    """
    ฟอร์มให้ HR เลือกงวดเงินเดือนที่จะใช้สร้างสลิป
    """
    period = forms.ModelChoiceField(
        queryset=PayrollPeriod.objects.all().order_by('-year', '-month'),
        label="งวดเงินเดือน",
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )

class PayrollPeriodForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriod
        fields = ['year', 'month', 'start_date', 'end_date']
        labels = {
            'year': 'ปี',
            'month': 'เดือน',
            'start_date': 'วันเริ่มงวด',
            'end_date': 'วันสิ้นสุดงวด',
        }
        widgets = {
            'year': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': 2000}),
            'month': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': 1, 'max': 12}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and start > end:
            self.add_error('end_date', 'วันสิ้นสุดงวดต้องไม่เร็วกว่าวันเริ่มงวด')
        return cleaned
    
class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'code',
            'first_name',
            'last_name',
            'position',
            'department',
            'hire_date',
            'status',
            'base_salary',
            'phone_number',
            'address',
            'citizen_id',
            'bank_name',
            'bank_account_no',
        ]
        labels = {
            'code': 'รหัสพนักงาน',
            'first_name': 'ชื่อ',
            'last_name': 'นามสกุล',
            'position': 'ตำแหน่ง',
            'department': 'แผนก',
            'hire_date': 'วันที่เริ่มงาน',
            'status': 'สถานะ',
            'base_salary': 'ฐานเงินเดือน / เดือน',
            'phone_number': 'เบอร์โทรศัพท์',
            'address': 'ที่อยู่ติดต่อ',
            'citizen_id': 'เลขบัตรประชาชน',
            'bank_name': 'ธนาคาร',
            'bank_account_no': 'เลขบัญชี',
        }
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'position': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'department': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'hire_date': forms.DateInput(attrs={
                'class': 'form-control form-control-sm',
                'type': 'date',
            }),
            'status': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'base_salary': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
            }),
            'phone_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'address': forms.Textarea(attrs={
                'class': 'form-control form-control-sm',
                'rows': 3,
            }),
            'citizen_id': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'bank_account_no': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }

class EmployeeTaxProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeeTaxProfile
        fields = [
            "is_married",
            "spouse_has_income",
            "children_count",
            "insurance_deduction",
            "provident_fund",
            "home_loan_interest",
            "other_deduction",
        ]
        widgets = {
            "insurance_deduction": forms.NumberInput(attrs={"step": "0.01"}),
            "provident_fund": forms.NumberInput(attrs={"step": "0.01"}),
            "home_loan_interest": forms.NumberInput(attrs={"step": "0.01"}),
            "other_deduction": forms.NumberInput(attrs={"step": "0.01"}),
        }

class EmployeeImportForm(forms.Form):
    file = forms.FileField(
        label="ไฟล์ CSV รายชื่อพนักงาน",
        help_text="ต้องมีอย่างน้อย: code, first_name, last_name, base_salary"
    )
