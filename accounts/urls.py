from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import TemplateView

from . import views

app_name = "accounts"

urlpatterns = [
    # Authentication URLs
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "locked/",
        TemplateView.as_view(template_name="accounts/lockout.html"),
        name="locked",
    ),
    path(
        "password_reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            email_template_name="accounts/password_reset_email.html",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url="/accounts/password_reset/done/",
        ),
        name="password_reset",
    ),
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url="/accounts/reset/done/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # Employee management URLs
    path("first-login/<str:token>/", views.first_login_view, name="first_login"),
    path("create-employee/", views.create_employee_view, name="create_employee"),
    # Time entry URLs (US-C01, US-C02, US-C03)
    path("time-entries/", views.time_entry_list, name="time_entry_list"),
    path("time-entries/new/", views.time_entry_create, name="time_entry_create"),
    path(
        "time-entries/<int:entry_id>/edit/",
        views.time_entry_edit,
        name="time_entry_edit",
    ),
    path(
        "time-entries/<int:entry_id>/delete/",
        views.time_entry_delete,
        name="time_entry_delete",
    ),
]
