from django.urls import path
from . import views
from .views import fetch_transcripts_from_db, fetch_witnesses_from_db

urlpatterns = [
    path('fetch-transcripts/', views.fetch_transcripts, name='fetch_transcripts'),
    path("index-data/", views.fetch_and_index),
    path("search/", views.search_transcripts),
    path("api/fetch-transcripts/", fetch_transcripts_from_db, name="fetch_transcripts"),
    path("api/fetch-witness/", fetch_witnesses_from_db, name="fetch_witnesses_from_db"),
    path("api/search/", views.search_transcripts, name="search_transcripts"),
    path("api/getWitness", views.getWitness, name="get_witness"),
]
