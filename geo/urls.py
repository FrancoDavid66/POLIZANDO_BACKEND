# geo/urls.py
from rest_framework.routers import DefaultRouter
from .views import GeoItemViewSet

router = DefaultRouter()
router.register(r"geoitems", GeoItemViewSet)

urlpatterns = router.urls
