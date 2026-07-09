# ranking/urls.py
from django.urls import path

from .views import RankingView

app_name = "ranking"

urlpatterns = [
    path("ranking/", RankingView.as_view(), name="ranking"),
]