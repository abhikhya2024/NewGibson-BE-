# routers.py
from rest_framework.routers import DefaultRouter
from project.views import ProjectViewSet,CommentViewSet, CommentViewSet,HighlightsViewSet, TranscriptViewSet,TestimonyViewSet, WitnessViewSet, WitnessTypeViewSet, WitnessAlignmentViewSet
from user.views import UserViewSet
router = DefaultRouter()
router.register(r'project', ProjectViewSet, basename='project')
router.register(r'transcript', TranscriptViewSet, basename='transcript')
router.register(r'witness', WitnessViewSet, basename='witness')
router.register(r'witness-type', WitnessTypeViewSet, basename='witness-type')
router.register(r'witness-alignment', WitnessAlignmentViewSet, basename='witness-alignment')
router.register(r'testimony', TestimonyViewSet, basename='testimony')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'users', UserViewSet, basename="users")
router.register(r'highlights', HighlightsViewSet, basename="highlights")


urlpatterns = router.urls
