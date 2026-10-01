from django.urls import path

from apps.mcp_ops.views import AuditView, RegenerateView, TokenView

urlpatterns = [
    path('tokens/', TokenView.as_view()),
    path('tokens/regenerate/', RegenerateView.as_view()),
    path('logs/', AuditView.as_view()),
]
