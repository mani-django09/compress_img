from django.urls import path
from .views import UploadView, dynamic_features, home, ResizeToKBView
from .views import about, privacy_policy, terms_of_service, contact_us
from django.contrib.sitemaps.views import sitemap
from . import views
from .views import resize_to_50kb_view
from .views import resize_to_100kb_view

sitemaps = {
    'static': views.StaticViewSitemap,
}

urlpatterns = [
    path('', home, name='home'),
    path('image-compressor/', UploadView.as_view(), name='upload'),
    path('features/', dynamic_features, name='dynamic_features'),
    
    path('about/', about, name='about'),
    path('privacy-policy/', privacy_policy, name='privacy'),
    path('terms-of-service/', terms_of_service, name='terms'),
    path('contact/', contact_us, name='contact'),
    
    path('resize-image-to-20kb/', ResizeToKBView.as_view(), name='resize_to_kb'),
    path('resize-image-to-50kb/', resize_to_50kb_view, name='resize_to_50kb'),
    path('resize-image-to-100kb/', resize_to_100kb_view, name='resize_to_100kb'),
    path('compress-to-50kb/', views.compress_to_50kb, name='compress_50kb'),
    path('compress-to-100kb/', views.compress_to_100kb, name='compress_100kb'),
    path('compress-to-200kb/', views.compress_to_200kb, name='compress_200kb'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('sitemap.xml', views.sitemap_xml, name='sitemap_xml'),
]