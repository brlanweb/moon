from django.urls import path

from .views import *

urlpatterns = [
    path('', AppView.as_view()),
    path('kit/key/', kit_key),
    path('deploy/', DeployView.as_view()),
    path('deploy/<int:d_id>/versions/', get_versions),
]
