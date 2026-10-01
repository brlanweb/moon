from django.urls import path

from .views import *

urlpatterns = [
    path('', RepositoryView.as_view()),
    path('<int:r_id>/', get_detail),
    path('request/', get_requests),
]
