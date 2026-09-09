# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
# from django.urls import path
from django.urls import path
from apps.setting.views import *
from apps.setting.user import UserSettingView

urlpatterns = [
    path('', SettingView.as_view()),
    path('user/', UserSettingView.as_view()),
    path('email_test/', email_test),
    path('about/', get_about),
]
