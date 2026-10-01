from django.urls import path

from apps.pipeline.views import PipeView, DoView, handle_data_upload

urlpatterns = [
    path('', PipeView.as_view()),
    path('upload/', handle_data_upload),
    path('do/', DoView.as_view()),
]
