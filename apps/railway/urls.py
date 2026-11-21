from django.urls import path

from . import views

app_name = "railway"

urlpatterns = [
    path("trains/search/", views.search, name="search"),
    path("trains/", views.train_list, name="train_list"),
    path("trains/<str:number>/", views.train_detail, name="train_detail"),
]
