from django.contrib import admin, messages
from .models import (
    Employee,
    PayrollPeriod,
    EarningType,
    DeductionType,
    Payslip,
    PayslipItem,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('code', 'first_name', 'last_name', 'position', 'department', 'base_salary', 'status')
    list_filter = ('status', 'department')
    search_fields = ('code', 'first_name', 'last_name')

@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ('month', 'year', 'start_date', 'end_date', 'is_closed')
    list_filter = ('year', 'is_closed')
    search_fields = ('month', 'year')

    actions = ['generate_payslips_action']

    @admin.action(description="Generate payslip ให้พนักงานทุกคนในงวดที่เลือก")
    def generate_payslips_action(self, request, queryset):
        count_periods = 0
        for period in queryset:
            period.generate_payslips()
            count_periods += 1

        self.message_user(
            request,
            f"สร้าง/อัปเดต payslip ให้พนักงานของ {count_periods} งวดเรียบร้อยแล้ว",
            level=messages.SUCCESS
        )

@admin.register(EarningType)
class EarningTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_taxable', 'is_ssf')
    search_fields = ('name', 'code')


@admin.register(DeductionType)
class DeductionTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_tax', 'is_ssf')
    search_fields = ('name', 'code')


class PayslipItemInline(admin.TabularInline):
    model = PayslipItem
    extra = 0

@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ('employee', 'period', 'gross_income', 'total_deduction', 'net_income', 'generated_at')
    list_filter = ('period__year', 'period__month')
    search_fields = ('employee__code', 'employee__first_name', 'employee__last_name')
    inlines = [PayslipItemInline]
    readonly_fields = ('gross_income', 'total_deduction', 'net_income', 'generated_at')

    actions = ['recalc_selected_payslips', 'calc_ssf_tax_for_selected']

    @admin.action(description="Recalculate totals (ยอดรวมรายรับ/รายหัก/รับสุทธิ)")
    def recalc_selected_payslips(self, request, queryset):
        count = 0
        for payslip in queryset:
            payslip.recalc_totals()
            count += 1
        self.message_user(
            request,
            f"อัปเดตยอดรวมให้ {count} payslip แล้ว",
            level=messages.SUCCESS
        )

    @admin.action(description="คำนวณ ประกันสังคม + ภาษีหัก ณ ที่จ่าย (เวอร์ชันเบื้องต้น)")
    def calc_ssf_tax_for_selected(self, request, queryset):
        count = 0
        for payslip in queryset:
            payslip.update_social_security_and_tax()
            count += 1
        self.message_user(
            request,
            f"คำนวณประกันสังคม + ภาษี ให้ {count} payslip เรียบร้อยแล้ว",
            level=messages.SUCCESS
        )
