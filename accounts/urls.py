from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("first-login/<str:token>/", views.first_login_view, name="first_login"),
    path("create-employee/", views.create_employee_view, name="create_employee"),
]
