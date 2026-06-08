"""
URL Configuration for Backend
"""
from django.contrib import admin
from core.admin import admin_site
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import JsonResponse


def health_check(request):
    """Simple health check for Render deployment"""
    return JsonResponse({"status": "ok"})


@api_view(['GET'])
def api_root(request):
    """API root - list available endpoints"""
    return Response({
        'message': 'Zainussunna Academy API',
        'version': '1.0.0',
        'endpoints': {
            'programs': '/api/programs/',
            'admissions': '/api/admissions/',
            'content': '/api/content/',
            'achievements': '/api/achievements/',
            'gallery': '/api/gallery/',
            'enquiries': '/api/enquiries/',
            'analytics': '/api/analytics/',
            'auth': '/api/auth/',
            'health': '/api/health/',
        },
        'documentation': '/api/docs/',
    })


urlpatterns = [
    path('admin/', admin.site.urls),
    path('zainussunna-admin/', admin_site.urls),
    path('api/', api_root),
    path('api/core/', include('core.urls')),
    path('health/', health_check),
]

# Serve media files in development AND production
# Note: static() only works when DEBUG=True, so we add a manual re_path for production
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Manual media and static serving for production environments (DEBUG=False)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
]

