from django.urls import path

from apps.credential.views import CredView, handle_check

urlpatterns = [
    path('', CredView.as_view()),
    path('check/', handle_check),
]
