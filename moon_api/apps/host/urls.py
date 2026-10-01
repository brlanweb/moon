from django.urls import path

from apps.host.views import *
from apps.host.group import GroupView
from apps.host.extend import ExtendView
from apps.host.overview_metrics import overview_metrics
from apps.host.metrics import MetricsView, get_net_metrics
from apps.host.add import get_regions, cloud_import

urlpatterns = [
    path('', HostView.as_view()),
    path('extend/', ExtendView.as_view()),
    path('group/', GroupView.as_view()),
    path('metrics/overview/', overview_metrics),
    path('metrics/', MetricsView.as_view()),
    path('metrics/net/', get_net_metrics),
    path('import/', post_import),
    path('export/', post_export),
    path('import/cloud/', cloud_import),
    path('import/region/', get_regions),
    path('parse/', post_parse),
    path('valid/', batch_valid),
]
