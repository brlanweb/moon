from django.urls import path

from .views import *

urlpatterns = [
    path('', DetectionView.as_view()),
    path('overview/', get_overview),
    path('test/', run_test),
]
