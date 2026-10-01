from django.urls import path

from apps.account.views import *
from apps.account.history import *

urlpatterns = [
    path('login/', login),
    path('logout/', logout),
    path('user/', UserView.as_view()),
    path('role/', RoleView.as_view()),
    path('self/', SelfView.as_view()),
    path('login/history/', HistoryView.as_view())
]
