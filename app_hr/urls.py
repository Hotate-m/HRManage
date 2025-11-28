from django.urls import path
from . import views

app_name = 'app_hr'

urlpatterns = [
    path('hr/employees/', views.employee_list_view, name='employee_list'),
    path('login/', views.hr_login_view, name='hr_login'),
    path('logout/', views.hr_logout_view, name='hr_logout'),
    path('hr/employees/new/', views.employee_create_view, name='employee_create'),
    path('employees/<int:pk>/', views.employee_detail_view, name='employee_detail'), 
    path('employees/<int:pk>/year-summary/', views.employee_year_summary_view, name='employee_year_summary'),
    path('employees/upload/', views.employee_upload_view, name='employee_upload'),
    path('employees/<int:pk>/year-summary/tax-pdf/', views.employee_year_tax_pdf_view, name='employee_year_tax_pdf'),
    path('hr/employees/<int:pk>/', views.employee_edit_view, name='employee_edit'),
    path('hr/payslips/', views.payslip_list_view, name='payslip_list'),
    path('hr/payslips/<int:pk>/', views.payslip_detail_view, name='payslip_detail'),
    path('hr/payslips/<int:pk>/pdf/', views.payslip_pdf_view, name='payslip_pdf'),
    path('hr/dashboard/', views.payroll_dashboard_view, name='payroll_dashboard'),
    path('hr/attendance/upload/', views.attendance_upload_view, name='attendance_upload'),
    path('hr/attendance/daily/', views.attendance_daily_view, name='attendance_daily'),
    path('hr/attendance/settings/', views.attendance_settings_view, name='attendance_settings'),
    path('attendance/employee-month/', views.attendance_employee_month_view, name='attendance_employee_month'),
    path('attendance/employee-year/', views.attendance_employee_year_view, name='attendance_employee_year'),
    path('hr/leave/settings/', views.leave_settings_view, name='leave_settings'),
    path('hr/leave/manage/', views.leave_manage_view, name='leave_manage'),
    path('hr/leave/summary/', views.leave_summary_view, name='leave_summary'),
    path('hr/payroll/run/', views.payroll_run_view, name='payroll_run'),
    path('hr/payroll/periods/', views.payroll_period_list_view, name='payroll_periods'),
    path('hr/payroll/export-csv/', views.payroll_export_csv_view, name='payroll_export_csv'),
    path('hr/payroll/export-bank/', views.payroll_export_bank_view, name='payroll_export_bank'),
    path('hr/system/reset/', views.system_reset_view, name='system_reset'),
    path('tax/profile/', views.tax_profile_view, name='tax_profile'),
    path('dashboard/', views.payroll_dashboard_view, name='payroll_dashboard'),
]
