import csv
import calendar
from io import TextIOWrapper
from datetime import datetime, date, timedelta
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from django.template.loader import get_template, render_to_string
from xhtml2pdf import pisa

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.urls import reverse
from django.db import transaction
from django.http import HttpResponseForbidden, HttpResponse
from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.contrib import messages 
from .forms import (    
    AttendanceUploadForm,
    CompanySettingForm,
    HolidayForm,
    LeaveTypeForm,
    LeaveRecordForm,
    PayrollRunForm,
    PayrollPeriodForm,
    EmployeeForm,
    EmployeeTaxProfileForm,
    EmployeeImportForm,
)
from .models import (
    Employee,
    PayrollPeriod,
    EarningType,
    DeductionType,
    Payslip,
    PayslipItem,
    CompanySetting,
    Holiday,
    LeaveType,
    LeaveRecord,
    AttendanceRecord,
    EmployeeTaxProfile,
)

def hr_required(view_func):
    """
    ให้เฉพาะ user ที่ล็อกอินแล้ว และเป็น staff / superuser
    ใช้สำหรับทุกหน้าใน HR portal
    """
    decorated_view_func = login_required(
        user_passes_test(
            lambda u: u.is_staff or u.is_superuser,
        )(view_func)
    )
    return decorated_view_func

def hr_login_view(request):
    if request.user.is_authenticated:
        return redirect('app_hr:payroll_dashboard')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('app_hr:payroll_dashboard')
    else:
        form = AuthenticationForm(request)

    return render(request, 'app_hr/hr_login.html', {'form': form})

@login_required
def hr_logout_view(request):
    """
    ออกจากระบบ HR Portal
    """
    logout(request)
    return redirect('app_hr:hr_login')

@hr_required
def employee_list_view(request):
    """
    HR ดูรายการพนักงาน + filter + search
    """
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()

    employees = Employee.objects.all().order_by('code')

    if status:
        employees = employees.filter(status=status)

    if q:
        employees = employees.filter(
            Q(code__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(department__icontains=q)
        )

    # ดึง list สถานะจาก model (ค่า distinct)
    statuses = (
        Employee.objects
        .exclude(status__isnull=True)
        .exclude(status__exact='')
        .values_list('status', flat=True)
        .distinct()
        .order_by('status')
    )

    context = {
        'employees': employees,
        'q': q,
        'statuses': statuses,
        'selected_status': status,
    }
    return render(request, 'app_hr/employee_list.html', context)

@hr_required
def employee_detail_view(request, pk):
    """
    หน้าโปรไฟล์พนักงาน (สรุปภาพรวม)
    - ข้อมูลส่วนตัว
    - สลิปเงินเดือนล่าสุด
    - สรุปการเข้างานปีปัจจุบัน
    - สรุปการลา
    - เปลี่ยนสถานะ active / inactive ได้
    """
    emp = get_object_or_404(Employee, pk=pk)

    # ==== เปลี่ยนสถานะพนักงาน (POST) ====
    if request.method == 'POST':
        new_status = request.POST.get('status', '').strip()
        if new_status in ['active', 'inactive']:
            emp.status = new_status
            emp.save(update_fields=['status'])
            messages.success(
                request,
                f"อัปเดตสถานะพนักงาน {emp.code} เป็น "
                + ("ทำงานอยู่" if new_status == 'active' else "ออกแล้ว")
                + " เรียบร้อยแล้ว"
            )
        else:
            messages.error(request, "สถานะที่เลือกไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง")

        return redirect('app_hr:employee_detail', pk=emp.pk)

    # ==== ด้านล่างเป็นส่วนเดิม: สรุปปีปัจจุบัน ====
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))

    recent_payslips = (
        emp.payslips
        .select_related('period')
        .order_by('-period__year', '-period__month')[:6]
    )

    att_qs = AttendanceRecord.objects.filter(
        employee=emp,
        work_date__year=year,
    )

    status_counts = {
        'present': 0,
        'late': 0,
        'absent': 0,
        'leave': 0,
        'holiday': 0,
    }
    for row in att_qs.values('status').annotate(c=Count('id')):
        status_counts[row['status']] = row['c']

    total_days = att_qs.count()

    leaves_qs = LeaveRecord.objects.filter(
        employee=emp,
        start_date__year=year,
        status='approved',
    ).select_related('leave_type')

    leave_by_type = {}
    for lr in leaves_qs:
        key = lr.leave_type.name if lr.leave_type else 'ไม่ระบุประเภท'
        leave_by_type.setdefault(key, 0)
        leave_by_type[key] += float(lr.days or 0)

    context = {
        'employee': emp,
        'year': year,
        'recent_payslips': recent_payslips,
        'status_counts': status_counts,
        'total_days': total_days,
        'leave_by_type': leave_by_type,
    }
    return render(request, 'app_hr/employee_detail.html', context)

@hr_required
def employee_create_view(request):
    """
    HR สร้างพนักงานใหม่
    """
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            emp = form.save()
            messages.success(request, f"สร้างพนักงาน {emp.code} เรียบร้อยแล้ว")
            return redirect('app_hr:employee_edit', pk=emp.pk)
    else:
        form = EmployeeForm()

    context = {
        'form': form,
        'employee': None,
        'mode': 'create',
    }
    return render(request, 'app_hr/employee_form.html', context)

@hr_required
def employee_year_tax_pdf_view(request, pk):
    """
    ใบรับรองเงินเดือน + ภาษีหัก ณ ที่จ่าย (ทั้งปี) ของพนักงาน 1 คน
    - ถ้า weasyprint ใช้งานได้ -> ส่งออกเป็น PDF
    - ถ้า weasyprint / system lib มีปัญหา -> แสดงหน้า HTML สวย ๆ ให้พิมพ์ / save PDF เอง
    """
    emp = get_object_or_404(Employee, pk=pk)

    # ปีภาษี
    try:
        year = int(request.GET.get("year", timezone.now().year))
    except (TypeError, ValueError):
        year = timezone.now().year

    # CompanySetting (ถ้ามี field อื่น ๆ ก็ใช้ได้เลย)
    try:
        company = CompanySetting.get_solo()
    except Exception:
        company = None

    # ดึง payslip ทั้งปีของพนักงานคนนี้
    payslips = (
        Payslip.objects.filter(employee=emp, period__year=year)
        .select_related("period")
        .order_by("period__month")
    )

    totals = payslips.aggregate(
        total_gross=Sum("gross_income"),
        total_deduct=Sum("total_deduction"),
        total_net=Sum("net_income"),
    )
    total_gross = totals["total_gross"] or Decimal("0.00")
    total_deduct = totals["total_deduct"] or Decimal("0.00")
    total_net = totals["total_net"] or Decimal("0.00")

    # รวม WHT / SSF ทั้งปี
    deduction_items = PayslipItem.objects.filter(
        payslip__employee=emp,
        payslip__period__year=year,
        item_type="deduction",
    ).select_related("deduction_type")

    wht_total = deduction_items.filter(
        deduction_type__code="WHT"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    ssf_total = deduction_items.filter(
        deduction_type__code="SOCIAL_SEC"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    context = {
        "employee": emp,
        "company": company,
        "year": year,
        "payslips": payslips,
        "total_gross": total_gross,
        "total_deduct": total_deduct,
        "total_net": total_net,
        "wht_total": wht_total,
        "ssf_total": ssf_total,
        "generated_at": timezone.now(),
    }

    try:
        # พยายามสร้าง PDF ด้วย weasyprint ก่อน
        from weasyprint import HTML

        html = render_to_string("app_hr/employee_year_tax_pdf.html", context)
        response = HttpResponse(content_type="application/pdf")
        filename = f"tax_certificate_{emp.code}_{year}.pdf"
        response["Content-Disposition"] = f'inline; filename="{filename}"'

        HTML(string=html, base_url=request.build_absolute_uri()).write_pdf(response)
        return response

    except Exception:
        # ถ้า weasyprint หรือ system lib มีปัญหา
        context["weasyprint_error"] = (
            "ยังไม่สามารถสร้าง PDF อัตโนมัติด้วย WeasyPrint บนเครื่องนี้ได้ "
            "กรุณาใช้เมนูพิมพ์ (Print → Save as PDF) ของเบราว์เซอร์ชั่วคราว "
            "และเมื่อติดตั้ง dependency ของ WeasyPrint ครบแล้ว "
            "หน้านี้จะดาวน์โหลด PDF ให้อัตโนมัติ"
        )
        return render(request, "app_hr/employee_year_tax_pdf.html", context)

@hr_required
def employee_year_summary_view(request, pk):
    """
    HR ดูสรุปทั้งปีของพนักงานรายคน:
    - เงินเดือนรวม (gross / net)
    - ภาษีหัก ณ ที่จ่าย
    - ประกันสังคม
    - ยอดลาตามประเภท
    """
    emp = get_object_or_404(Employee, pk=pk)

    # ปีที่เลือก (ค่า default = ปีปัจจุบัน)
    try:
        year = int(request.GET.get("year", timezone.now().year))
    except ValueError:
        year = timezone.now().year

    # ดึง payslip ของปีนั้น
    payslips = Payslip.objects.filter(
        employee=emp,
        period__year=year,
    ).select_related("period").order_by("period__month")

    totals = payslips.aggregate(
        total_gross=Sum("gross_income"),
        total_deduct=Sum("total_deduction"),
        total_net=Sum("net_income"),
    )
    total_gross = totals["total_gross"] or Decimal("0.00")
    total_deduct = totals["total_deduct"] or Decimal("0.00")
    total_net = totals["total_net"] or Decimal("0.00")

    # หาภาษี + ประกันสังคม จาก PayslipItem (ใช้ code: WHT, SOCIAL_SEC)
    deduction_items = PayslipItem.objects.filter(
        payslip__employee=emp,
        payslip__period__year=year,
        item_type="deduction",
    ).select_related("deduction_type")

    wht_total = deduction_items.filter(
        deduction_type__code="WHT"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    ssf_total = deduction_items.filter(
        deduction_type__code="SOCIAL_SEC"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    # สรุปวันลา (เฉพาะที่อนุมัติแล้ว)
    leave_qs = LeaveRecord.objects.filter(
        employee=emp,
        status="approved",
        start_date__year=year,
    ).select_related("leave_type")

    leave_summary = (
        leave_qs
        .values("leave_type__name")
        .annotate(total_days=Sum("days"))
        .order_by("leave_type__name")
    )

    # list ปีที่เคยมี payslip / leave ให้ HR เลือกสลับปีได้
    year_from_payslip = (
        Payslip.objects.filter(employee=emp)
        .values_list("period__year", flat=True)
        .distinct()
    )
    year_from_leave = (
        LeaveRecord.objects.filter(employee=emp)
        .values_list("start_date__year", flat=True)
        .distinct()
    )
    year_choices = sorted(set(list(year_from_payslip) + list(year_from_leave)) or [year])

    context = {
        "employee": emp,
        "year": year,
        "year_choices": year_choices,
        "payslips": payslips,
        "total_gross": total_gross,
        "total_deduct": total_deduct,
        "total_net": total_net,
        "wht_total": wht_total,
        "ssf_total": ssf_total,
        "leave_summary": leave_summary,
    }
    return render(request, "app_hr/employee_year_summary.html", context)

@hr_required
def employee_edit_view(request, pk):
    """
    HR แก้ไขข้อมูลพนักงาน
    """
    emp = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=emp)
        if form.is_valid():
            form.save()
            messages.success(request, f"บันทึกข้อมูลพนักงาน {emp.code} เรียบร้อยแล้ว")
            return redirect('app_hr:employee_list')
    else:
        form = EmployeeForm(instance=emp)

    context = {
        'form': form,
        'employee': emp,
        'mode': 'edit',
    }
    return render(request, 'app_hr/employee_form.html', context)

@hr_required
def employee_upload_view(request):
    """
    นำเข้าพนักงานหลาย ๆ คนจากไฟล์ CSV
    - matching จาก field "code" (รหัสพนักงาน)
    - ถ้ามี code เดิม -> update
    - ถ้ายังไม่มี -> create ใหม่
    """
    created = 0
    updated = 0
    errors = []

    if request.method == "POST" and request.FILES.get("file"):
        file = request.FILES["file"]

        try:
            # รองรับไฟล์ที่ save จาก Excel เป็น UTF-8 (มี BOM)
            decoded = file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = file.read().decode("utf-8", errors="ignore")

        reader = csv.DictReader(decoded.splitlines())

        # คอลัมน์ที่รองรับ (ไม่ต้องมีครบทุกคอลัมน์ก็ได้ แต่ต้องมีอย่างน้อย code, first_name, last_name)
        required_cols = ["code", "first_name", "last_name"]
        missing_cols = [c for c in required_cols if c not in reader.fieldnames]

        if missing_cols:
            messages.error(
                request,
                f"ไฟล์ CSV ต้องมีหัวคอลัมน์อย่างน้อย: {', '.join(required_cols)} "
                f"(ขาด: {', '.join(missing_cols)})"
            )
        else:
            row_number = 1  # นับเริ่มจาก 1 = header
            for row in reader:
                row_number += 1

                try:
                    code = (row.get("code") or "").strip()
                    first_name = (row.get("first_name") or "").strip()
                    last_name = (row.get("last_name") or "").strip()

                    if not code or not first_name or not last_name:
                        raise ValueError("ต้องมี code, first_name, last_name ครบ")

                    # ฟิลด์อื่น ๆ (optional)
                    position = (row.get("position") or "").strip() or None
                    department = (row.get("department") or "").strip() or None
                    phone_number = (row.get("phone_number") or "").strip() or None
                    address = (row.get("address") or "").strip() or None
                    citizen_id = (row.get("citizen_id") or "").strip() or None
                    bank_name = (row.get("bank_name") or "").strip() or None
                    bank_account_no = (row.get("bank_account_no") or "").strip() or None

                    # status (active / inactive)
                    status_val = (row.get("status") or "").strip().lower()
                    if status_val not in ["active", "inactive", ""]:
                        raise ValueError("status ต้องเป็น active หรือ inactive หรือเว้นว่าง")
                    if not status_val:
                        status_val = "active"

                    # hire_date รูปแบบ YYYY-MM-DD
                    hire_date_raw = (row.get("hire_date") or "").strip()
                    hire_date = None
                    if hire_date_raw:
                        try:
                            hire_date = datetime.strptime(hire_date_raw, "%Y-%m-%d").date()
                        except ValueError:
                            raise ValueError("รูปแบบวันที่ hire_date ต้องเป็น YYYY-MM-DD")

                    # base_salary
                    base_salary_raw = (row.get("base_salary") or "").replace(",", "").strip()
                    base_salary = Decimal("0")
                    if base_salary_raw:
                        try:
                            base_salary = Decimal(base_salary_raw)
                        except Exception:
                            raise ValueError("base_salary ต้องเป็นตัวเลข เช่น 35000 หรือ 35000.00")

                    # สร้างหรืออัปเดต
                    obj, is_created = Employee.objects.update_or_create(
                        code=code,
                        defaults={
                            "first_name": first_name,
                            "last_name": last_name,
                            "position": position,
                            "department": department,
                            "phone_number": phone_number,
                            "address": address,
                            "citizen_id": citizen_id,
                            "bank_name": bank_name,
                            "bank_account_no": bank_account_no,
                            "status": status_val,
                            "hire_date": hire_date,
                            "base_salary": base_salary,
                        }
                    )

                    if is_created:
                        created += 1
                    else:
                        updated += 1

                except Exception as e:
                    errors.append(f"แถวที่ {row_number}: {e}")

            if errors:
                messages.warning(
                    request,
                    f"นำเข้าสำเร็จบางส่วน: เพิ่มใหม่ {created} คน, อัปเดต {updated} คน, มี error {len(errors)} แถว"
                )
            else:
                messages.success(
                    request,
                    f"นำเข้าพนักงานสำเร็จ: เพิ่มใหม่ {created} คน, อัปเดต {updated} คน"
                )

    context = {
        "created": created,
        "updated": updated,
        "errors": errors,
    }
    return render(request, "app_hr/employee_upload.html", context)

@login_required
def my_payslips_view(request):
    """
    แสดงรายการ payslip ของ user ที่ล็อกอินอยู่
    """
    try:
        employee = request.user.employee_profile
    except Employee.DoesNotExist:
        # ยังไม่ได้ผูก user กับ Employee
        return render(request, 'app_hr/no_employee_link.html', {})

    payslips = Payslip.objects.filter(employee=employee).select_related('period').order_by(
        '-period__year',
        '-period__month',
    )

    context = {
        'employee': employee,
        'payslips': payslips,
    }
    return render(request, 'app_hr/my_payslips.html', context)

@hr_required
def payslip_list_view(request):
    """
    รายการสลิปเงินเดือน (กรองตามงวด / แผนก / ค้นหาพนักงาน)
    """
    period_id = request.GET.get('period')
    q = request.GET.get('q', '').strip()
    dept = request.GET.get('dept', '').strip()

    payslips = Payslip.objects.select_related('employee', 'period').all()
    periods = PayrollPeriod.objects.all().order_by('-year', '-month')

    # ดึง list แผนกจาก Employee (distinct)
    from .models import Employee  # กันไว้ถ้ายังไม่ได้ import ด้านบน
    departments = (
        Employee.objects
        .exclude(department__isnull=True)
        .exclude(department__exact='')
        .values_list('department', flat=True)
        .distinct()
        .order_by('department')
    )

    if period_id:
        payslips = payslips.filter(period_id=period_id)

    if dept:
        payslips = payslips.filter(employee__department=dept)

    if q:
        payslips = payslips.filter(
            Q(employee__first_name__icontains=q) |
            Q(employee__last_name__icontains=q) |
            Q(employee__code__icontains=q)
        )

    payslips = payslips.order_by('employee__code')

    context = {
        'payslips': payslips,
        'periods': periods,
        'selected_period_id': period_id,
        'q': q,
        'departments': departments,
        'selected_dept': dept,
    }
    return render(request, 'app_hr/payslip_list.html', context)

@hr_required
def payroll_export_csv_view(request):
    """
    Export CSV รายการสลิปเงินเดือนในงวดที่เลือก
    คำนวณ GROSS / DEDUCTION / NET จาก PayslipItem โดยตรง
    """
    period_id = request.GET.get('period')
    if not period_id:
        return HttpResponse("กรุณาเลือกงวดเงินเดือนก่อนส่งออก CSV", status=400)

    period = get_object_or_404(PayrollPeriod, pk=period_id)

    dept = request.GET.get('dept', '').strip()

    payslips = Payslip.objects.filter(
        period=period
    ).select_related('employee', 'period').order_by('employee__code')

    if dept:
        payslips = payslips.filter(employee__department=dept)

    filename = f"payroll_{period.year}_{period.month}.csv"
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # หัวตาราง
    writer.writerow([
        "รหัสพนักงาน",
        "ชื่อ",
        "นามสกุล",
        "แผนก",
        "งวดเดือน",
        "งวดปี",
        "รายรับรวม (GROSS)",
        "รายหักรวม",
        "รับสุทธิ (NET)",
    ])

    for ps in payslips:
        emp = ps.employee

        # คำนวณ GROSS / DEDUCT / NET จาก PayslipItem
        total_earn = PayslipItem.objects.filter(
            payslip=ps,
            earning_type__isnull=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_deduct = PayslipItem.objects.filter(
            payslip=ps,
            deduction_type__isnull=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        net = total_earn - total_deduct

        writer.writerow([
            emp.code or "",
            emp.first_name or "",
            emp.last_name or "",
            emp.department or "",
            ps.period.month,
            ps.period.year,
            float(total_earn),
            float(total_deduct),
            float(net),
        ])

    return response 

@hr_required
def payroll_export_bank_view(request):
    """
    Export CSV สำหรับจ่ายเงินเดือนผ่านธนาคาร
    - ใช้ยอด NET ของแต่ละสลิป
    - รวมพนักงานที่มีเลขบัญชี (bank_account_no) เท่านั้น
    - สามารถกรองตามแผนกได้ (dept)
    """
    period_id = request.GET.get('period')
    dept = request.GET.get('dept', '').strip()

    if not period_id:
        return HttpResponse("กรุณาเลือกงวดเงินเดือนก่อนส่งออกไฟล์ธนาคาร", status=400)

    period = get_object_or_404(PayrollPeriod, pk=period_id)

    payslips = Payslip.objects.filter(
        period=period,
        employee__bank_account_no__isnull=False,
    ).exclude(
        employee__bank_account_no__exact=''
    ).select_related('employee', 'period').order_by('employee__code')

    if dept:
        payslips = payslips.filter(employee__department=dept)

    filename = f"bank_payroll_{period.year}_{period.month}.csv"
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # หัวคอลัมน์ – เบื้องต้นเป็น format กลาง ๆ
    writer.writerow([
        "ธนาคาร",
        "เลขบัญชี",
        "ชื่อพนักงาน",
        "รหัสพนักงาน",
        "ยอดจ่ายสุทธิ",
        "หมายเหตุ",
    ])

    for ps in payslips:
        emp = ps.employee

        # คำนวณ NET จาก PayslipItem (เหมือนใน export csv ตัวก่อนหน้า)
        total_earn = PayslipItem.objects.filter(
            payslip=ps,
            earning_type__isnull=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_deduct = PayslipItem.objects.filter(
            payslip=ps,
            deduction_type__isnull=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        net = total_earn - total_deduct

        full_name = f"{emp.first_name or ''} {emp.last_name or ''}".strip()

        writer.writerow([
            emp.bank_name or "",
            emp.bank_account_no or "",
            full_name,
            emp.code or "",
            float(net),
            f"งวด {period.month}/{period.year}",
        ])

    return response

@hr_required
def payslip_detail_view(request, pk):
    """
    ดูรายละเอียดสลิปเงินเดือนของพนักงาน 1 คน
    + สรุปวันทำงาน / วันหักไม่จ่าย จาก Attendance & Leave
    """
    payslip = get_object_or_404(
        Payslip.objects.select_related('employee', 'period'),
        pk=pk
    )
    items = PayslipItem.objects.filter(
        payslip=payslip
    ).select_related('earning_type', 'deduction_type')

    # หา item "หักวันไม่จ่าย" จาก Payslip (ถ้ามี)
    unpaid_item = None
    for it in items:
        if it.deduction_type and it.deduction_type.code == 'UNPAID':
            unpaid_item = it
            break

    emp = payslip.employee
    period = payslip.period

    # ===== 1) หาวันทำงาน (จันทร์–ศุกร์, ไม่ใช่วันหยุด) =====
    working_days = []
    current = period.start_date
    while current <= period.end_date:
        if current.weekday() < 5 and not Holiday.objects.filter(date=current).exists():
            working_days.append(current)
        current += timedelta(days=1)

    # ===== 2) Attendance ของพนักงานคนนี้ในงวดนี้ =====
    att_qs = AttendanceRecord.objects.filter(
        employee=emp,
        work_date__gte=period.start_date,
        work_date__lte=period.end_date,
    )
    att_map = {a.work_date: a for a in att_qs}

    # ===== 3) Leave ของพนักงานในงวดนี้ (เฉพาะที่อนุมัติแล้ว) =====
    leave_qs = LeaveRecord.objects.filter(
        employee=emp,
        status='approved',
        start_date__lte=period.end_date,
        end_date__gte=period.start_date,
    ).select_related('leave_type')

    # สร้าง set "วันลาที่ไม่จ่าย"
    unpaid_leave_days = set()
    for lr in leave_qs:
        if lr.leave_type and not lr.leave_type.is_paid:
            start = max(lr.start_date, period.start_date)
            end = min(lr.end_date, period.end_date)
            cur = start
            while cur <= end:
                if cur in working_days:
                    unpaid_leave_days.add(cur)
                cur += timedelta(days=1)

    # ===== 4) สร้าง list รายละเอียดวันหักไม่จ่าย =====
    unpaid_details = []
    unpaid_days_count = 0

    for d in working_days:
        reason = None
        if d in unpaid_leave_days:
            reason = 'ลา (ไม่จ่ายเงิน)'
        else:
            att = att_map.get(d)
            if not att:
                reason = 'ไม่มีบันทึกเข้างาน (ขาด)'
            elif att.status == 'absent':
                reason = 'ขาดงาน'

        if reason:
            unpaid_days_count += 1
            unpaid_details.append({
                'date': d,
                'reason': reason,
            })

    context = {
        'payslip': payslip,
        'items': items,
        'unpaid_item': unpaid_item,
        'working_day_count': len(working_days),
        'unpaid_days_count': unpaid_days_count,
        'unpaid_details': unpaid_details,
    }
    return render(request, 'app_hr/payslip_detail.html', context)

def render_to_pdf(template_src, context_dict):
    """
    helper ใช้ xhtml2pdf แปลง HTML -> PDF
    """
    template = get_template(template_src)
    html = template.render(context_dict)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="payslip.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse("เกิดข้อผิดพลาดในการสร้าง PDF", status=500)
    return response

@hr_required
def payslip_pdf_view(request, pk):
    """
    หน้า HTML สำหรับพิมพ์/Export เป็น PDF ของสลิปเงินเดือน
    (ใช้ browser กด Print -> Save as PDF)
    """
    payslip = get_object_or_404(
        Payslip.objects.select_related('employee', 'period'),
        pk=pk
    )

    # แยก Earning / Deduction จาก PayslipItem
    earning_qs = PayslipItem.objects.filter(
        payslip=payslip,
        earning_type__isnull=False
    ).select_related('earning_type')

    deduction_qs = PayslipItem.objects.filter(
        payslip=payslip,
        deduction_type__isnull=False
    ).select_related('deduction_type')

    total_earn = earning_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_deduct = deduction_qs.aggregate(total=Sum('amount'))['total'] or 0
    net = total_earn - total_deduct

    # หา item หักวันไม่จ่าย (ถ้ามี)
    unpaid_item = deduction_qs.filter(deduction_type__code='UNPAID').first()

    # company setting (ถ้ามีแถวในตาราง)
    company = CompanySetting.objects.first()

    context = {
        'payslip': payslip,
        'earning_items': earning_qs,
        'deduction_items': deduction_qs,
        'total_earn': total_earn,
        'total_deduct': total_deduct,
        'net_amount': net,
        'unpaid_item': unpaid_item,
        'company': company,
    }
    # ตรงนี้ยังเป็น HTML ปกติ ให้ browser print เป็น PDF เอา
    return render(request, 'app_hr/payslip_pdf.html', context)

@login_required
def payroll_dashboard_view(request):
    """
    Dashboard สำหรับผู้บริหาร/HR ดูภาพรวมเงินเดือนต่อรอบ
    """
    # จำกัดสิทธิ์: ขอให้เฉพาะ staff/superuser ดูได้
    if not request.user.is_staff:
        return HttpResponseForbidden("คุณไม่มีสิทธิ์เข้าดูหน้านี้")

    # เลือกงวดเงินเดือนจาก query param ?period=ID
    period_id = request.GET.get('period')

    if period_id:
        period = get_object_or_404(PayrollPeriod, pk=period_id)
    else:
        # ถ้าไม่ระบุ ให้ใช้งวดล่าสุด (ตาม Meta ordering ของ PayrollPeriod)
        period = PayrollPeriod.objects.order_by('-year', '-month').first()

    period_list = PayrollPeriod.objects.order_by('-year', '-month')

    payslips = Payslip.objects.none()
    summary = {}
    dept_summary = []
    ssf_total = 0
    wht_total = 0

    if period:
        payslips = Payslip.objects.filter(period=period).select_related('employee')

        # สรุปตัวเลขหลัก
        summary = payslips.aggregate(
            total_gross=Sum('gross_income'),
            total_deduction=Sum('total_deduction'),
            total_net=Sum('net_income'),
            count_payslips=Count('id'),
        )

        # สรุปตามแผนก
        dept_summary = (
            payslips
            .values('employee__department')
            .annotate(
                emp_count=Count('employee', distinct=True),
                dept_gross=Sum('gross_income'),
                dept_deduction=Sum('total_deduction'),
                dept_net=Sum('net_income'),
            )
            .order_by('employee__department')
        )

        # รวมยอดประกันสังคม + ภาษี (จาก PayslipItem)
        ss_type = DeductionType.objects.filter(code='SOCIAL_SEC').first()
        wht_type = DeductionType.objects.filter(code='WHT').first()

        if ss_type:
            ssf_total = (
                PayslipItem.objects
                .filter(payslip__period=period, deduction_type=ss_type)
                .aggregate(s=Sum('amount'))['s'] or 0
            )

        if wht_type:
            wht_total = (
                PayslipItem.objects
                .filter(payslip__period=period, deduction_type=wht_type)
                .aggregate(s=Sum('amount'))['s'] or 0
            )

    context = {
        'period': period,
        'period_list': period_list,
        'summary': summary,
        'dept_summary': dept_summary,
        'ssf_total': ssf_total,
        'wht_total': wht_total,
    }
    return render(request, 'app_hr/payroll_dashboard.html', context)

@hr_required
def attendance_daily_view(request):
    """
    ดูสรุปการเข้างานว่า ใคร ขาด / ลา / สาย / ปกติ ในวันหนึ่ง
    ?date=YYYY-MM-DD (ถ้าไม่ส่งมา ใช้วันนี้)
    """
    date_str = request.GET.get('date')
    if date_str:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    employees = Employee.objects.filter(status='active').order_by('code')

    # preload attendance ของวันนั้น
    attendance_map = {
        (a.employee_id): a
        for a in AttendanceRecord.objects.filter(work_date=target_date).select_related('employee')
    }

    rows = []
    for emp in employees:
        att = attendance_map.get(emp.id)

        # เดี๋ยวคำนวณสถานะให้ ถ้าไม่มี record ก็ลองประเมินจากวันหยุด/ลา
        status = 'absent'
        check_in = None
        check_out = None
        remark = ''

        # วันหยุด?
        if Holiday.objects.filter(date=target_date).exists():
            status = 'holiday'
        else:
            # ลา?
            leave_qs = LeaveRecord.objects.filter(
                employee=emp,
                status='approved',
                start_date__lte=target_date,
                end_date__gte=target_date,
            )
            if leave_qs.exists():
                status = 'leave'

        if att:
            # ใช้สถานะจาก AttendanceRecord (ซึ่งคำนวนไว้แล้ว)
            status = att.status
            check_in = att.check_in
            check_out = att.check_out
            remark = att.remark or ''

        rows.append({
            'employee': emp,
            'status': status,
            'check_in': check_in,
            'check_out': check_out,
            'remark': remark,
        })

    context = {
        'target_date': target_date,
        'rows': rows,
    }
    return render(request, 'app_hr/attendance_daily.html', context)

@hr_required
def attendance_settings_view(request):
    """
    ตั้งค่าเวลาเริ่มงาน + กี่นาทีถือว่าสาย + จัดการวันหยุด
    """
    settings_obj = CompanySetting.get_solo()

    if request.method == 'POST':
        # อัปเดต setting เวลาเข้างาน / นาทีสาย
        if 'update_settings' in request.POST:
            settings_form = CompanySettingForm(request.POST, instance=settings_obj)
            holiday_form = HolidayForm()  # ฟอร์มเปล่าเอาไว้แสดงด้านล่าง
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, "บันทึกการตั้งค่าเวลาเข้างานเรียบร้อยแล้ว")
                return redirect('app_hr:attendance_settings')

        # เพิ่มวันหยุดใหม่
        elif 'add_holiday' in request.POST:
            settings_form = CompanySettingForm(instance=settings_obj)
            holiday_form = HolidayForm(request.POST)
            if holiday_form.is_valid():
                holiday_form.save()
                messages.success(request, "เพิ่มวันหยุดใหม่เรียบร้อยแล้ว")
                return redirect('app_hr:attendance_settings')

        # ลบวันหยุด
        elif 'delete_holiday_id' in request.POST:
            settings_form = CompanySettingForm(instance=settings_obj)
            holiday_form = HolidayForm()
            holiday_id = request.POST.get('delete_holiday_id')
            if holiday_id:
                Holiday.objects.filter(id=holiday_id).delete()
                messages.success(request, "ลบวันหยุดเรียบร้อยแล้ว")
                return redirect('app_hr:attendance_settings')
    else:
        settings_form = CompanySettingForm(instance=settings_obj)
        holiday_form = HolidayForm()

    holidays = Holiday.objects.order_by('date')

    context = {
        'settings_form': settings_form,
        'holiday_form': holiday_form,
        'holidays': holidays,
    }
    return render(request, 'app_hr/attendance_settings.html', context)

@hr_required
def attendance_upload_view(request):
    """
    หน้าอัปโหลด CSV ลงเวลาเข้า–ออกงาน
    """
    form = AttendanceUploadForm(request.POST or None, request.FILES or None)
    report = None

    if request.method == 'POST' and form.is_valid():
        f = form.cleaned_data['file']
        decoded = TextIOWrapper(f.file, encoding='utf-8')
        reader = csv.DictReader(decoded)

        created = 0
        updated = 0
        skipped = 0
        errors = []

        with transaction.atomic():
            for i, row in enumerate(reader, start=2):  # เริ่มนับบรรทัดที่ 2 (ข้าม header)
                code = (row.get('employee_code') or '').strip()
                date_str = (row.get('date') or '').strip()
                ci_str = (row.get('check_in') or '').strip()
                co_str = (row.get('check_out') or '').strip()

                if not code or not date_str:
                    skipped += 1
                    errors.append(f"แถว {i}: ไม่มี employee_code หรือ date")
                    continue

                try:
                    work_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    skipped += 1
                    errors.append(f"แถว {i}: รูปแบบวันที่ไม่ถูกต้อง (ควรเป็น YYYY-MM-DD)")
                    continue

                try:
                    emp = Employee.objects.get(code=code)
                except Employee.DoesNotExist:
                    skipped += 1
                    errors.append(f"แถว {i}: ไม่พบพนักงาน code={code}")
                    continue

                def parse_time(t_str):
                    if not t_str:
                        return None
                    try:
                        return datetime.strptime(t_str, "%H:%M").time()
                    except ValueError:
                        return None

                ci = parse_time(ci_str)
                co = parse_time(co_str)

                att, is_created = AttendanceRecord.objects.get_or_create(
                    employee=emp,
                    work_date=work_date,
                    defaults={
                        'check_in': ci,
                        'check_out': co,
                        'source': 'csv',
                    }
                )
                if not is_created:
                    att.check_in = ci
                    att.check_out = co
                    att.source = 'csv'
                    updated += 1
                else:
                    created += 1

                # คำนวณสถานะจากกฎ
                att.auto_calculate_status()
                att.save()

        report = {
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
        }

    context = {
        'form': form,
        'report': report,
    }
    return render(request, 'app_hr/attendance_upload.html', context)

@hr_required
def attendance_employee_month_view(request):
    """
    หน้าแสดงประวัติการเข้างาน 'รายคน' แบบรายเดือน
    - เลือกพนักงาน
    - เลือกเดือน/ปี
    - แสดงทุกวันในเดือนนั้น + สถานะเข้างาน
    """
    employees = Employee.objects.order_by('code')

    if not employees.exists():
        messages.warning(request, "ยังไม่มีข้อมูลพนักงานในระบบ")
        return render(request, "app_hr/attendance_employee_month.html", {
            "employees": [],
        })

    today = timezone.localdate()
    # ดึงค่าจาก query string หรือใช้วันนี้เป็น default
    try:
        month = int(request.GET.get("month", today.month))
        year = int(request.GET.get("year", today.year))
    except ValueError:
        month = today.month
        year = today.year

    emp_code = request.GET.get("emp")
    if emp_code:
        employee = get_object_or_404(Employee, code=emp_code)
    else:
        employee = employees.first()

    # หาวันแรก / วันสุดท้ายของเดือน
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    # ดึง attendance ของพนักงานคนนี้ในเดือนนั้น
    qs = AttendanceRecord.objects.filter(
        employee=employee,
        work_date__range=(first_day, last_day),
    ).order_by('work_date')

    # แปลงเป็น list ก่อน เพื่อใช้ทั้งใน table และ summary
    records = list(qs)

    # map วันที่ -> record
    record_map = {r.work_date: r for r in records}

    # list วันในเดือน + record (หรือ None ถ้าไม่มี)
    days = []
    cur = first_day
    while cur <= last_day:
        days.append({
            "date": cur,
            "record": record_map.get(cur),
        })
        cur += timedelta(days=1)

    # ===== สรุปจำนวนสถานะต่าง ๆ (จาก records) =====
    present_count = sum(1 for r in records if r.status == "present")
    late_count = sum(1 for r in records if r.status == "late")
    absent_count = sum(1 for r in records if r.status == "absent")
    leave_count = sum(1 for r in records if r.status == "leave")
    holiday_count = sum(1 for r in records if r.status == "holiday")

    context = {
        "employees": employees,
        "employee": employee,
        "month": month,
        "year": year,
        "months": list(range(1, 13)),
        "years": [today.year - 1, today.year, today.year + 1],
        "days": days,

        "present_count": present_count,
        "late_count": late_count,
        "absent_count": absent_count,
        "leave_count": leave_count,
        "holiday_count": holiday_count,
    }
    return render(request, "app_hr/attendance_employee_month.html", context)

@hr_required
def attendance_employee_year_view(request):
    """
    หน้าแสดงประวัติการเข้างาน 'รายคน' แบบรายปี
    - เลือกพนักงาน
    - เลือกปี
    - แสดงสรุปทั้ง 12 เดือน: present / late / absent / leave / holiday
    """
    employees = Employee.objects.order_by('code')

    if not employees.exists():
        messages.warning(request, "ยังไม่มีข้อมูลพนักงานในระบบ")
        return render(request, "app_hr/attendance_employee_year.html", {
            "employees": [],
        })

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
    except ValueError:
        year = today.year

    emp_code = request.GET.get("emp")
    if emp_code:
        employee = get_object_or_404(Employee, code=emp_code)
    else:
        employee = employees.first()

    # ดึง attendance ทั้งปีของพนักงานคนนี้
    qs = AttendanceRecord.objects.filter(
        employee=employee,
        work_date__year=year,
    ).order_by('work_date')

    # เตรียมโครง summary 12 เดือน
    months_data = []
    # สร้าง map เดือน -> dict สถานะ
    month_status_map = {
        m: {
            "present": 0,
            "late": 0,
            "absent": 0,
            "leave": 0,
            "holiday": 0,
        }
        for m in range(1, 13)
    }

    for rec in qs:
        m = rec.work_date.month
        if rec.status in month_status_map[m]:
            month_status_map[m][rec.status] += 1

    # แปลงเป็น list สำหรับ template
    for m in range(1, 13):
        data = month_status_map[m]
        total = (
            data["present"]
            + data["late"]
            + data["absent"]
            + data["leave"]
            + data["holiday"]
        )
        months_data.append({
            "month": m,
            "present": data["present"],
            "late": data["late"],
            "absent": data["absent"],
            "leave": data["leave"],
            "holiday": data["holiday"],
            "total": total,
        })

    # รวมทั้งปี
    total_present = sum(d["present"] for d in months_data)
    total_late = sum(d["late"] for d in months_data)
    total_absent = sum(d["absent"] for d in months_data)
    total_leave = sum(d["leave"] for d in months_data)
    total_holiday = sum(d["holiday"] for d in months_data)
    total_days = sum(d["total"] for d in months_data)

    context = {
        "employees": employees,
        "employee": employee,
        "year": year,
        "years": [today.year - 1, today.year, today.year + 1],
        "months_data": months_data,

        "total_present": total_present,
        "total_late": total_late,
        "total_absent": total_absent,
        "total_leave": total_leave,
        "total_holiday": total_holiday,
        "total_days": total_days,
    }
    return render(request, "app_hr/attendance_employee_year.html", context)

@hr_required
def leave_settings_view(request):
    """
    ตั้งค่า LeaveType เช่น ลาป่วย / ลากิจ / พักร้อน + สิทธิ์วันต่อปี
    """
    if request.method == 'POST':
        if 'add_type' in request.POST:
            form = LeaveTypeForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "เพิ่มประเภทการลาเรียบร้อยแล้ว")
                return redirect('app_hr:leave_settings')
        elif 'delete_type_id' in request.POST:
            lt_id = request.POST.get('delete_type_id')
            if lt_id:
                LeaveType.objects.filter(id=lt_id).delete()
                messages.success(request, "ลบประเภทการลาเรียบร้อยแล้ว")
                return redirect('app_hr:leave_settings')
        form = LeaveTypeForm(request.POST or None)
    else:
        form = LeaveTypeForm()

    leave_types = LeaveType.objects.order_by('name')

    context = {
        'form': form,
        'leave_types': leave_types,
    }
    return render(request, 'app_hr/leave_settings.html', context)

@hr_required
def leave_manage_view(request):
    """
    HR ลงข้อมูลการลาของพนักงาน (โดยปกติจะอนุมัติเลย)
    """
    if request.method == 'POST':
        form = LeaveRecordForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"บันทึกการลาของ {obj.employee} เรียบร้อยแล้ว")
            return redirect('app_hr:leave_manage')
    else:
        # default: สถานะเป็น approved
        initial = {'status': 'approved'}
        form = LeaveRecordForm(initial=initial)

    # แสดงรายการลาล่าสุด 20 รายการ
    recent_leaves = (
        LeaveRecord.objects
        .select_related('employee', 'leave_type')
        .order_by('-start_date')[:20]
    )

    context = {
        'form': form,
        'recent_leaves': recent_leaves,
    }
    return render(request, 'app_hr/leave_manage.html', context)

@hr_required
def leave_summary_view(request):
    """
    สรุปการใช้สิทธิ์ลา ต่อพนักงาน ต่อประเภทลา ในปีที่เลือก
    """
    year_str = request.GET.get('year')
    today = date.today()
    year = int(year_str) if year_str else today.year

    employees = Employee.objects.filter(status='active').order_by('code')
    leave_types = LeaveType.objects.order_by('name')

    # รวมวันลาตาม employee + leave_type ในปีนั้น (เฉพาะ approved)
    usage_qs = (
        LeaveRecord.objects
        .filter(status='approved', start_date__year=year)
        .values('employee_id', 'leave_type_id')
        .annotate(total_days=Sum('days'))
    )

    usage_map = {}
    for row in usage_qs:
        key = (row['employee_id'], row['leave_type_id'])
        usage_map[key] = row['total_days'] or 0

    # list ปีให้เลือก (ย้อนหลัง 3 ปี + ปีหน้า)
    year_choices = [year - 1, year, year + 1]

    context = {
        'year': year,
        'year_choices': year_choices,
        'employees': employees,
        'leave_types': leave_types,
        'usage_map': usage_map,
    }
    return render(request, 'app_hr/leave_summary.html', context)

def _get_working_days_and_unpaid_days(employee, period):
    """
    คำนวณจำนวนวันทำงานในงวด และจำนวนวัน 'ไม่จ่าย'
    - วันทำงาน = วันธรรมดา (จ.-ศ.) ที่ไม่ใช่วันหยุดนักขัต (Holiday)
    - ถ้ามี LeaveRecord ที่ครอบวันนั้นและเป็น leave แบบจ่ายเงิน -> ไม่นับเป็นไม่จ่าย
    - ถ้ามี LeaveRecord แบบไม่จ่าย -> นับเป็นวันไม่จ่าย
    - ถ้ามี AttendanceRecord ในวันนั้น -> ถือว่ามาทำงาน
    - ถ้าไม่มี AttendanceRecord และไม่มีลาจ่าย -> นับเป็นไม่จ่าย
    """
    from .models import Holiday, AttendanceRecord, LeaveRecord  # กันชื่อซ้ำ

    start = period.start_date
    end = period.end_date

    # เตรียม set วันหยุด เพื่อ lookup เร็ว ๆ
    holiday_dates = set(
        Holiday.objects.filter(date__range=(start, end))
        .values_list('date', flat=True)
    )

    working_days = 0
    unpaid_days = 0

    current = start
    while current <= end:
        # ข้ามเสาร์-อาทิตย์
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        # ข้ามวันหยุดนักขัต
        if current in holiday_dates:
            current += timedelta(days=1)
            continue

        working_days += 1

        # เช็คว่ามีการลาไหม
        leave_qs = LeaveRecord.objects.filter(
            employee=employee,
            start_date__lte=current,
            end_date__gte=current,
        ).select_related('leave_type')

        if leave_qs.exists():
            # สมมติว่า leave_type มี field is_paid (ถ้าไม่มี ให้ถือว่าจ่าย)
            leave = leave_qs.first()
            is_paid = getattr(leave.leave_type, 'is_paid', True)
            if not is_paid:
                unpaid_days += 1
            # ถ้าลาแบบจ่ายเงิน -> ไม่ถือว่าไม่จ่าย
            current += timedelta(days=1)
            continue

        # ไม่มีลา → เช็คการเข้างาน
        att = AttendanceRecord.objects.filter(
            employee=employee,
            date=current,
        ).first()

        if att is None:
            # ไม่มีบันทึกเข้างานเลย -> ขาดงาน (ไม่จ่าย)
            unpaid_days += 1
        else:
            # ถ้า model คุณมี status เช่น 'absent' ให้เพิ่ม logic ตรงนี้ได้
            if getattr(att, 'status', 'present') == 'absent':
                unpaid_days += 1

        current += timedelta(days=1)

    return working_days, unpaid_days


def _get_unpaid_deduction_type():
    """
    คืน DeductionType สำหรับ 'หักวันไม่จ่าย'
    ถ้าไม่มีก็สร้างให้เลย (code = UNPAID)
    """
    from .models import DeductionType
    dt, created = DeductionType.objects.get_or_create(
        code='UNPAID',
        defaults={
            'name': 'หักวันไม่จ่าย',
        }
    )
    return dt

@hr_required
def payroll_run_view(request):
    """
    HR เลือกงวดเงินเดือน แล้วให้ระบบสร้าง Payslip ให้พนักงานทุกคนจาก base_salary
    + คำนวณหักวันไม่จ่ายจาก Attendance & Leave
    + คำนวณประกันสังคม + ภาษีหัก ณ ที่จ่าย จากยอดรายได้รวม (gross_income)
    """
    form = PayrollRunForm(request.POST or None)
    result = None

    if request.method == 'POST' and form.is_valid():
        period = form.cleaned_data['period']

        # ===== 1) ประเภท BASE / UNPAID =====
        base_type, _ = EarningType.objects.get_or_create(
            code='BASE_SALARY',
            defaults={
                'name': 'เงินเดือนพื้นฐาน',
                'is_taxable': True,
                'is_ssf': True,
            }
        )
        unpaid_type, _ = DeductionType.objects.get_or_create(
            code='UNPAID',
            defaults={
                'name': 'หักวันไม่จ่าย',
                'is_tax': False,
                'is_ssf': False,
            }
        )

        employees = Employee.objects.filter(status='active').order_by('code')

        # ===== 2) list วันทำงานจริงในงวดนี้ (จันทร์–ศุกร์ + ไม่ใช่วันหยุด) =====
        working_days = []
        current = period.start_date
        while current <= period.end_date:
            if current.weekday() < 5 and not Holiday.objects.filter(date=current).exists():
                working_days.append(current)
            current += timedelta(days=1)

        working_day_count = len(working_days) or 1  # กันหาร 0

        # ===== 3) preload Attendance & Leave =====
        att_qs = AttendanceRecord.objects.filter(
            work_date__gte=period.start_date,
            work_date__lte=period.end_date,
            employee__in=employees,
        ).select_related('employee')
        att_map = {(a.employee_id, a.work_date): a for a in att_qs}

        leave_qs = LeaveRecord.objects.filter(
            status='approved',
            employee__in=employees,
            start_date__lte=period.end_date,
            end_date__gte=period.start_date,
        ).select_related('employee', 'leave_type')

        # set สำหรับ “วันลาที่ไม่จ่าย” -> (emp_id, date)
        unpaid_leave_days = set()
        for lr in leave_qs:
            if lr.leave_type and not lr.leave_type.is_paid:
                start = max(lr.start_date, period.start_date)
                end = min(lr.end_date, period.end_date)
                cur = start
                while cur <= end:
                    if cur in working_days:
                        unpaid_leave_days.add((lr.employee_id, cur))
                    cur += timedelta(days=1)

        created = 0
        updated = 0
        skipped = 0

        # ===== 4) loop ทีละพนักงาน =====
        for emp in employees:
            if not emp.base_salary:
                skipped += 1
                continue

            base_salary = Decimal(emp.base_salary)

            # --- 4.1 นับจำนวน "unpaid days" ---
            unpaid_days = 0

            for d in working_days:
                # ลาแบบไม่จ่าย
                if (emp.id, d) in unpaid_leave_days:
                    unpaid_days += 1
                    continue

                att = att_map.get((emp.id, d))

                if not att:
                    # ไม่มี attendance, ไม่ลา, ไม่หยุด -> ขาด
                    unpaid_days += 1
                    continue

                if att.status == 'absent':
                    unpaid_days += 1
                elif att.status == 'leave':
                    # เคสนี่ส่วนใหญ่ถูกจัดการใน unpaid_leave_days แล้ว
                    pass
                else:
                    # present / late / holiday -> ไม่หัก
                    pass

            # --- 4.2 คำนวณเงินหักจากวันไม่จ่าย ---
            daily_rate = (base_salary / Decimal(working_day_count)).quantize(Decimal("0.01"))
            unpaid_deduction = (daily_rate * Decimal(unpaid_days)).quantize(Decimal("0.01"))

            # ===== 5) สร้าง/อัปเดต Payslip =====
            payslip, is_created = Payslip.objects.get_or_create(
                employee=emp,
                period=period,
            )

            # 5.1 รายรับ: ฐานเงินเดือน
            base_item, base_created = PayslipItem.objects.get_or_create(
                payslip=payslip,
                item_type='earning',
                earning_type=base_type,
                deduction_type=None,
                defaults={
                    'name': 'ฐานเงินเดือน',
                    'amount': base_salary,
                },
            )
            if not base_created:
                base_item.name = 'ฐานเงินเดือน'
                base_item.amount = base_salary
                base_item.earning_type = base_type
                base_item.deduction_type = None
                base_item.save(update_fields=['name', 'amount', 'earning_type', 'deduction_type'])

            # 5.2 รายหัก: หักวันไม่จ่าย
            unpaid_item, unpaid_created = PayslipItem.objects.get_or_create(
                payslip=payslip,
                item_type='deduction',
                earning_type=None,
                deduction_type=unpaid_type,
                defaults={
                    'name': f'หักวันไม่จ่าย {unpaid_days} วัน',
                    'amount': unpaid_deduction,
                },
            )
            if not unpaid_created:
                unpaid_item.name = f'หักวันไม่จ่าย {unpaid_days} วัน'
                unpaid_item.amount = unpaid_deduction
                unpaid_item.deduction_type = unpaid_type
                unpaid_item.earning_type = None
                unpaid_item.save(update_fields=['name', 'amount', 'deduction_type', 'earning_type'])

            # ===== 6) คำนวณประกันสังคม + ภาษีหัก ณ ที่จ่าย =====
            # เมธอดนี้จะ:
            #   - recalc_totals() เพื่อให้ gross_income เป็นยอดรายรับล่าสุด
            #   - สร้าง/อัปเดต PayslipItem สำหรับ SOCIAL_SEC และ WHT
            #   - recalc_totals() อีกครั้งเพื่ออัปเดต net_income
            payslip.update_social_security_and_tax()

            if is_created:
                created += 1
            else:
                updated += 1

        result = {
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'period': period,
            'employee_count': employees.count(),
            'working_days': working_day_count,
        }

        messages.success(
            request,
            f"สร้าง/อัปเดตสลิปเงินเดือนสำหรับงวด {period.month}/{period.year} "
            f"(วันทำงาน {working_day_count} วัน) เรียบร้อยแล้ว"
        )

    context = {
        'form': form,
        'result': result,
    }
    return render(request, 'app_hr/payroll_run.html', context)

@hr_required
def payroll_period_list_view(request):
    """
    HR จัดการงวดเงินเดือน: สร้าง / ลบ PayrollPeriod
    """
    periods = PayrollPeriod.objects.all().order_by('-year', '-month')

    if request.method == 'POST':
        # สร้างงวดใหม่
        if 'add_period' in request.POST:
            form = PayrollPeriodForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "สร้างงวดเงินเดือนใหม่เรียบร้อยแล้ว")
                return redirect('app_hr:payroll_periods')
        # ลบงวด
        elif 'delete_period_id' in request.POST:
            period_id = request.POST.get('delete_period_id')
            if period_id:
                PayrollPeriod.objects.filter(id=period_id).delete()
                messages.success(request, "ลบงวดเงินเดือนเรียบร้อยแล้ว")
                return redirect('app_hr:payroll_periods')
        else:
            form = PayrollPeriodForm(request.POST or None)
    else:
        form = PayrollPeriodForm()

    context = {
        'form': form,
        'periods': periods,
    }
    return render(request, 'app_hr/payroll_periods.html', context)

@hr_required
def system_reset_view(request):
    """
    ฟอร์แมตระบบ HR ทั้งก้อน

    - ลบ:
        Employee (พนักงานทั้งหมด)
        PayrollPeriod
        Payslip, PayslipItem
        AttendanceRecord
        LeaveRecord
        EarningType, DeductionType
        Holiday
        LeaveType
        CompanySetting

    เหลือ:
        เฉพาะ Django User / สิ่งนอก app_hr

    เฉพาะ superuser เท่านั้น
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("เฉพาะ superuser เท่านั้นที่เข้าหน้านี้ได้")

    # สถิติปัจจุบัน เอาไว้ให้ superuser เห็นก่อนกดลบ
    stats = {
        'employee_count': Employee.objects.count(),

        'payslip_count': Payslip.objects.count(),
        'payslip_item_count': PayslipItem.objects.count(),
        'attendance_count': AttendanceRecord.objects.count(),
        'leave_count': LeaveRecord.objects.count(),
        'period_count': PayrollPeriod.objects.count(),

        'earning_type_count': EarningType.objects.count(),
        'deduction_type_count': DeductionType.objects.count(),
        'holiday_count': Holiday.objects.count(),
        'leave_type_count': LeaveType.objects.count(),
        'company_setting_count': CompanySetting.objects.count(),
    }

    if request.method == 'POST':
        if request.POST.get('confirm') == 'yes':
            # ลบจากปลายทางก่อน (child → parent) กันปัญหา FK / PROTECT

            # 1) รายการในสลิป + สลิป
            PayslipItem.objects.all().delete()
            Payslip.objects.all().delete()

            # 2) ข้อมูลเข้างาน + การลา + งวดเงินเดือน
            AttendanceRecord.objects.all().delete()
            LeaveRecord.objects.all().delete()
            PayrollPeriod.objects.all().delete()

            # 3) ประเภทรายได้/รายหัก
            EarningType.objects.all().delete()
            DeductionType.objects.all().delete()

            # 4) วันหยุด + ประเภทลา + CompanySetting
            Holiday.objects.all().delete()
            LeaveType.objects.all().delete()
            CompanySetting.objects.all().delete()

            # 5) พนักงาน (สุดท้าย เพราะมี relation จาก Attendance / Leave / Payslip)
            Employee.objects.all().delete()

            messages.success(
                request,
                "ฟอร์แมตระบบ HR เรียบร้อยแล้ว: ลบข้อมูลทั้งหมดของ HR (รวมพนักงาน) สำเร็จ"
            )
            return redirect('app_hr:system_reset')
        else:
            messages.error(request, "กรุณาติ๊กเพื่อยืนยันการลบข้อมูลทั้งหมดก่อนดำเนินการ")

    context = {
        'stats': stats,
    }
    return render(request, 'app_hr/system_reset.html', context)

@hr_required
def tax_profile_view(request):
    """
    หน้าให้ HR เลือกพนักงาน แล้วกรอกรายละเอียดสิทธิ์ลดหย่อนภาษี (รายปี)
    ใช้สำหรับคำนวณภาษีหัก ณ ที่จ่ายรายเดือน
    """
    employees = Employee.objects.order_by("code")
    if not employees.exists():
        messages.warning(request, "ยังไม่มีข้อมูลพนักงานในระบบ")
        return render(request, "app_hr/tax_profile.html", {"employees": []})

    # เลือกพนักงานจาก query string ?emp=CODE
    emp_code = request.GET.get("emp")
    if emp_code:
        employee = get_object_or_404(Employee, code=emp_code)
    else:
        employee = employees.first()

    # เตรียม instance ของ TaxProfile (ถ้ายังไม่มีให้สร้างแต่ยังไม่ save)
    try:
        profile = employee.tax_profile
    except EmployeeTaxProfile.DoesNotExist:
        profile = EmployeeTaxProfile(employee=employee)

    if request.method == "POST":
        form = EmployeeTaxProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.instance.employee = employee
            form.save()
            messages.success(request, "บันทึกโปรไฟล์ลดหย่อนภาษีเรียบร้อยแล้ว")
            # redirect กลับมาที่ employee เดิม
            return redirect(f"{request.path}?emp={employee.code}")
    else:
        form = EmployeeTaxProfileForm(instance=profile)

    context = {
        "employees": employees,
        "employee": employee,
        "form": form,
    }
    return render(request, "app_hr/tax_profile.html", context)
