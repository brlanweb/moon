from django.urls import path

from apps.database.views import ConnectionView, check_connection, get_metadata, run_command, cancel_command


urlpatterns = [
    path('connection/', ConnectionView.as_view()),
    path('connection/check/', check_connection),
    path('metadata/', get_metadata),
    path('execute/', run_command),
    path('cancel/', cancel_command),
]
