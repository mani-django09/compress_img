from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.core.files.storage import default_storage
from django.views.generic import View
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from .forms import ImageUploadForm, ImageResizeToKBForm
from PIL import Image, ExifTags
import io
import os
import logging
from typing import Tuple
import magic
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

class ImageProcessingError(Exception):
    """Custom exception for image processing errors"""
    pass

def get_mime_type(file) -> str:
    """Determine MIME type of uploaded file using python-magic"""
    mime = magic.Magic(mime=True)
    file.seek(0)
    mime_type = mime.from_buffer(file.read(2048))
    file.seek(0)
    return mime_type

def process_image_orientation(image: Image.Image) -> Image.Image:
    """Process image orientation based on EXIF data"""
    if not hasattr(image, '_getexif') or not image._getexif():
        return image
    
    try:
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break
        
        exif = dict(image._getexif().items())
        if orientation in exif:
            if exif[orientation] == 3:
                return image.rotate(180, expand=True)
            elif exif[orientation] == 6:
                return image.rotate(270, expand=True)
            elif exif[orientation] == 8:
                return image.rotate(90, expand=True)
    except Exception as e:
        logger.warning(f"Error processing image orientation: {str(e)}")
    
    return image

def compress_image(
    image: Image.Image,
    max_dimension: int = 3000,
    quality: int = 85,
    preserve_exif: bool = True
) -> Tuple[bytes, dict]:
    """Compress image while maintaining aspect ratio"""
    ratio = min(max_dimension / float(image.size[0]), 
                max_dimension / float(image.size[1]))
    
    if ratio < 1:  # Only resize if image is larger than max dimension
        new_size = tuple(int(dim * ratio) for dim in image.size)
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    
    if image.mode in ('RGBA', 'P'):
        image = image.convert('RGB')
    
    output_buffer = io.BytesIO()
    save_params = {
        'format': 'JPEG',
        'quality': quality,
        'optimize': True
    }
    
    if preserve_exif and hasattr(image, 'info') and 'exif' in image.info:
        save_params['exif'] = image.info['exif']
    
    image.save(output_buffer, **save_params)
    
    compressed_data = output_buffer.getvalue()
    stats = {
        'final_width': image.size[0],
        'final_height': image.size[1],
        'compressed_size': len(compressed_data)
    }
    
    return compressed_data, stats

def compress_image_to_kb(
    image: Image.Image,
    target_size_kb: int,
    preserve_exif: bool = False,
    max_iterations: int = 10
) -> Tuple[bytes, dict]:
    """Compress image to specific file size in KB"""
    target_size_bytes = target_size_kb * 1024
    
    # Convert to RGB if necessary
    if image.mode in ('RGBA', 'P'):
        image = image.convert('RGB')
    
    # Start with high quality and reduce iteratively
    quality = 95
    min_quality = 10
    best_result = None
    best_stats = None
    
    # Try different dimensions if quality reduction isn't enough
    original_size = image.size
    dimension_reductions = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]
    
    for dimension_factor in dimension_reductions:
        # Resize image if needed
        if dimension_factor < 1.0:
            new_size = (
                int(original_size[0] * dimension_factor),
                int(original_size[1] * dimension_factor)
            )
            working_image = image.resize(new_size, Image.Resampling.LANCZOS)
        else:
            working_image = image.copy()
        
        # Binary search for optimal quality
        low_quality = min_quality
        high_quality = quality
        
        for iteration in range(max_iterations):
            current_quality = (low_quality + high_quality) // 2
            
            output_buffer = io.BytesIO()
            save_params = {
                'format': 'JPEG',
                'quality': current_quality,
                'optimize': True
            }
            
            if preserve_exif and hasattr(image, 'info') and 'exif' in image.info:
                save_params['exif'] = image.info['exif']
            
            working_image.save(output_buffer, **save_params)
            compressed_data = output_buffer.getvalue()
            compressed_size = len(compressed_data)
            
            # Check if we hit our target
            if abs(compressed_size - target_size_bytes) <= target_size_bytes * 0.05:  # 5% tolerance
                stats = {
                    'final_width': working_image.size[0],
                    'final_height': working_image.size[1],
                    'compressed_size': compressed_size,
                    'quality_used': current_quality,
                    'dimension_factor': dimension_factor
                }
                return compressed_data, stats
            
            # Store best result so far
            if best_result is None or abs(compressed_size - target_size_bytes) < abs(best_stats['compressed_size'] - target_size_bytes):
                best_result = compressed_data
                best_stats = {
                    'final_width': working_image.size[0],
                    'final_height': working_image.size[1],
                    'compressed_size': compressed_size,
                    'quality_used': current_quality,
                    'dimension_factor': dimension_factor
                }
            
            # Adjust quality range
            if compressed_size > target_size_bytes:
                high_quality = current_quality - 1
            else:
                low_quality = current_quality + 1
            
            if low_quality >= high_quality:
                break
        
        # If we found a good result with current dimensions, return it
        if best_result and abs(best_stats['compressed_size'] - target_size_bytes) <= target_size_bytes * 0.1:
            return best_result, best_stats
    
    # Return best result found
    if best_result:
        return best_result, best_stats
    
    # Fallback - shouldn't reach here
    output_buffer = io.BytesIO()
    image.save(output_buffer, format='JPEG', quality=min_quality, optimize=True)
    compressed_data = output_buffer.getvalue()
    stats = {
        'final_width': image.size[0],
        'final_height': image.size[1],
        'compressed_size': len(compressed_data),
        'quality_used': min_quality,
        'dimension_factor': 1.0
    }
    return compressed_data, stats

def compress_single_image(request):
    """Handle single image compression for both home and upload pages"""
    try:
        image_file = request.FILES.get('image_file')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

        # Check file size
        if image_file.size > 10 * 1024 * 1024:  # 10MB limit
            return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 10MB'}, status=400)

        # Check file type
        if not image_file.content_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
        
        # Get compression settings
        quality = int(request.POST.get('quality', 80))
        preserve_exif = request.POST.get('preserve_exif') == 'true'
        auto_rotate = request.POST.get('auto_rotate') == 'true'
        
        # Validate quality range
        quality = max(10, min(100, quality))
        
        # Open and process image
        with Image.open(image_file) as image:
            if auto_rotate:
                image = process_image_orientation(image)
            
            compressed_data, stats = compress_image(
                image,
                quality=quality,
                preserve_exif=preserve_exif
            )
        
        # Generate unique filename
        base_filename = os.path.splitext(image_file.name)[0]
        output_filename = f"{base_filename}_compressed_{quality}.jpg"
        
        # Prepare response for download
        response = HttpResponse(compressed_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(compressed_data)
        response['X-Original-Size'] = str(image_file.size)
        response['X-Compressed-Size'] = str(len(compressed_data))

        return response

    except Exception as e:
        logger.error(f"Compression error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred while processing the image.'}, status=500)

def home(request):
    """Home page view with compression functionality"""
    if request.method == 'POST':
        return compress_single_image(request)
    
    # GET request - show homepage
    context = {
        'page_title': 'Free Online Image Compressor | Reduce Photo File Size | ImageResizer.Pro',
        'meta_description': 'Compress JPEG, PNG, WebP images online for free. Reduce photo file sizes by up to 90% while maintaining quality. Fast batch compression tool for web optimization.',
        'keywords': 'image compressor, photo compressor, reduce image size, compress photos online, optimize images for web, batch image compression, JPEG compressor, PNG compressor'
    }
    return render(request, 'image_app/home.html', context)

class UploadView(View):
    """Class-based view for handling image uploads and compression"""
    template_name = 'image_app/upload.html'

    def get(self, request, *args, **kwargs):
        context = {
            'page_title': 'Professional Image Compressor Tool | Compress JPEG, PNG, WebP Images Online | ImageResizer.Pro',
            'meta_description': 'Advanced online image compressor tool for professionals. Compress JPEG, PNG, WebP images with intelligent quality control. Reduce file sizes by up to 90% while preserving image quality.',
            'keywords': 'image compressor, professional image compression, compress JPEG online, PNG compressor tool, WebP image optimizer, batch image compressor, lossless image compression, photo size reducer'
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        return compress_single_image(request)

class ResizeToKBView(View):
    """View for resizing images to specific KB size"""
    template_name = 'image_app/resize_to_kb.html'

    def get(self, request, *args, **kwargs):
        form = ImageResizeToKBForm()
        context = {
            'form': form,
            'page_title': 'Resize Image to 20KB Online Free | Compress Photos to Exact File Size | resizeimages.tools',
            'meta_description': 'Resize images to exactly 20KB or any specific file size online for free. Perfect for email attachments, web uploads, and file size requirements. Fast and accurate compression.',
            'keywords': 'resize image to 20kb, compress image to specific size, reduce photo to 20kb, image file size reducer, compress photo to kb, resize picture to exact size',
            'canonical_url': 'https://resizeimages.tools/resize-image-to-20kb/',
            'focus_keyword': 'resize image to 20kb'
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        try:
            image_file = request.FILES.get('image_file')
            if not image_file:
                return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

            # Check file size (10MB limit)
            if image_file.size > 10 * 1024 * 1024:
                return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 10MB'}, status=400)

            # Check file type
            if not image_file.content_type.startswith('image/'):
                return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
            
            # Get form data with proper default handling
            target_size_kb = request.POST.get('target_size_kb', '20')
            
            # Convert to integer and validate
            try:
                target_size_kb = int(target_size_kb)
            except (ValueError, TypeError):
                target_size_kb = 20  # Fallback to default
            
            # Ensure target size is within valid range
            if target_size_kb < 5:
                target_size_kb = 5
            elif target_size_kb > 1000:
                target_size_kb = 1000
            
            preserve_exif = request.POST.get('preserve_exif') == 'on'
            auto_rotate = request.POST.get('auto_rotate', 'on') == 'on'  # Default to 'on' if not provided
            
            logger.info(f"Processing image with target size: {target_size_kb}KB")
            
            # Open and process image
            with Image.open(image_file) as image:
                if auto_rotate:
                    image = process_image_orientation(image)
                
                compressed_data, stats = compress_image_to_kb(
                    image,
                    target_size_kb=target_size_kb,
                    preserve_exif=preserve_exif
                )
            
            # Generate filename
            base_filename = os.path.splitext(image_file.name)[0]
            output_filename = f"{base_filename}_resized_{target_size_kb}kb.jpg"
            
            # Prepare response
            response = HttpResponse(compressed_data, content_type='image/jpeg')
            response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
            response['Content-Length'] = len(compressed_data)
            response['X-Original-Size'] = str(image_file.size)
            response['X-Compressed-Size'] = str(len(compressed_data))
            response['X-Target-Size'] = str(target_size_kb * 1024)
            response['X-Quality-Used'] = str(stats.get('quality_used', 'unknown'))
            
            logger.info(f"Successfully processed image: {output_filename}, final size: {len(compressed_data)} bytes")

            return response

        except Exception as e:
            logger.error(f"KB compression error: {str(e)}", exc_info=True)
            return JsonResponse({'success': False, 'error': 'An error occurred while processing the image.'}, status=500)
        
        

def dynamic_features(request):
    """Dynamic features page view"""
    features_data = {
        'ai_features': [
            {
                'title': 'Smart Quality Detection',
                'description': 'AI analyzes image content for optimal compression',
                'icon': 'fas fa-brain',
                'benefits': [
                    'Automatic scene analysis',
                    'Edge detection and preservation', 
                    'Texture-aware compression',
                    'Color space optimization'
                ]
            },
            {
                'title': 'Content-Aware Processing',
                'description': 'Different algorithms for photos vs graphics',
                'icon': 'fas fa-eye',
                'benefits': [
                    'Photo-specific optimization',
                    'Graphics and logo handling',
                    'Text preservation',
                    'Gradient smoothing'
                ]
            }
        ],
        'batch_features': [
            {
                'title': 'Parallel Processing',
                'description': 'Process multiple images simultaneously',
                'icon': 'fas fa-layer-group',
                'benefits': [
                    'Upload up to 50 images',
                    'Consistent quality settings',
                    'Real-time progress tracking',
                    'Bulk download as ZIP'
                ]
            }
        ],
        'format_features': [
            {
                'title': 'Smart Format Selection',
                'description': 'Automatic format optimization',
                'icon': 'fas fa-exchange-alt',
                'benefits': [
                    'JPEG for photos',
                    'PNG for transparency',
                    'WebP for modern browsers',
                    'HEIC for mobile'
                ]
            }
        ]
    }
    
    context = {
        'features_data': features_data,
        'page_title': 'Advanced Image Compression Features | AI-Powered Tools | ImageResizer.Pro',
        'meta_description': 'Discover powerful image compression features including AI optimization, batch processing, format conversion, EXIF preservation, and more.',
        'keywords': 'image compression features, AI image optimization, batch image processing, EXIF data preservation, format conversion'
    }
    return render(request, 'image_app/dynamic_features.html', context)

def about(request):
    return render(request, 'image_app/about.html')

def privacy_policy(request):
    return render(request, 'image_app/privacy.html')

def terms_of_service(request):
    return render(request, 'image_app/terms.html')

def contact_us(request):
    """Contact Us page"""
    return render(request, 'image_app/contact.html')

from django.http import HttpResponse
from django.template import loader
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

# XML Sitemap view
@cache_page(60 * 60 * 24)  # Cache for 24 hours
def sitemap_xml(request):
    """Generate XML sitemap"""
    template = loader.get_template('sitemap.xml')
    context = {
        'current_date': timezone.now(),
        'base_url': 'https://resizeimages.tools',
    }
    return HttpResponse(
        template.render(context, request),
        content_type='application/xml'
    )

class StaticViewSitemap(Sitemap):
    """Sitemap for static pages"""
    priority = 0.5
    changefreq = 'monthly'
    protocol = 'https'

    def items(self):
        return [
            'home',
            'upload', 
            'gallery',
            'dynamic_features',
            'about',
            'privacy',
            'terms',
            'contact',
            'login',
            'resize_to_kb',      # 20KB page
            'resize_to_50kb',    # 50KB page
            'resize_to_100kb',   # 100KB page - Add this
        ]

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        return timezone.now().date()

    def priority(self, item):
        priorities = {
            'home': 1.0,
            'upload': 0.9,
            'resize_to_kb': 0.95,      # High priority
            'resize_to_50kb': 0.95,    # High priority
            'resize_to_100kb': 0.95,   # High priority - Add this
            'dynamic_features': 0.8,
            'gallery': 0.7,
            'about': 0.6,
            'contact': 0.5,
            'privacy': 0.4,
            'terms': 0.4,
            'login': 0.3,
        }
        return priorities.get(item, 0.5)

    def changefreq(self, item):
        frequencies = {
            'home': 'weekly',
            'upload': 'monthly',
            'resize_to_kb': 'monthly',
            'resize_to_50kb': 'monthly',
            'resize_to_100kb': 'monthly',  # Add this
            'gallery': 'weekly',
            'dynamic_features': 'monthly',
            'about': 'monthly',
            'contact': 'monthly',
            'privacy': 'quarterly',
            'terms': 'quarterly',
            'login': 'yearly',
        }
        return frequencies.get(item, 'monthly')
@cache_page(60 * 60 * 24)  # Cache for 24 hours
def robots_txt(request):
    """Generate robots.txt"""
    template = loader.get_template('robots.txt')
    return HttpResponse(
        template.render({}, request),
        content_type='text/plain'
    )


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def resize_to_50kb_view(request):
    """Function-based view for resizing images to 50KB"""
    
    if request.method == 'GET':
        context = {
            'page_title': 'Resize Image to 50KB Online Free | Compress Photos to 50KB | resizeimages.tools',
            'meta_description': 'Resize images to exactly 50KB online for free. Perfect for job applications, email attachments, and document uploads. Fast, accurate, and secure compression.',
            'keywords': 'resize image to 50kb, compress image to 50kb, reduce photo to 50kb, image file size reducer, compress photo to 50 kilobytes',
            'canonical_url': 'https://resizeimages.tools/resize-image-to-50kb/',
            'focus_keyword': 'resize image to 50kb'
        }
        return render(request, 'image_app/resize_to_50kb.html', context)
    
    # POST request - Image processing
    try:
        image_file = request.FILES.get('image_file')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

        # Check file size (10MB limit)
        if image_file.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 10MB'}, status=400)

        # Check file type
        if not image_file.content_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
        
        # Get form data with proper default handling (50KB for this page)
        target_size_kb = request.POST.get('target_size_kb', '50')
        
        # Convert to integer and validate
        try:
            target_size_kb = int(target_size_kb)
        except (ValueError, TypeError):
            target_size_kb = 50  # Fallback to default for 50KB page
        
        # Ensure target size is within valid range
        if target_size_kb < 5:
            target_size_kb = 5
        elif target_size_kb > 1000:
            target_size_kb = 1000
        
        preserve_exif = request.POST.get('preserve_exif') == 'on'
        auto_rotate = request.POST.get('auto_rotate', 'on') == 'on'
        
        logger.info(f"Processing image with target size: {target_size_kb}KB")
        
        # Open and process image
        with Image.open(image_file) as image:
            if auto_rotate:
                image = process_image_orientation(image)
            
            compressed_data, stats = compress_image_to_kb(
                image,
                target_size_kb=target_size_kb,
                preserve_exif=preserve_exif
            )
        
        # Generate filename
        base_filename = os.path.splitext(image_file.name)[0]
        output_filename = f"{base_filename}_resized_{target_size_kb}kb.jpg"
        
        # Prepare response
        response = HttpResponse(compressed_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(compressed_data)
        response['X-Original-Size'] = str(image_file.size)
        response['X-Compressed-Size'] = str(len(compressed_data))
        response['X-Target-Size'] = str(target_size_kb * 1024)
        response['X-Quality-Used'] = str(stats.get('quality_used', 'unknown'))
        
        logger.info(f"Successfully processed image: {output_filename}, final size: {len(compressed_data)} bytes")

        return response

    except Exception as e:
        logger.error(f"KB compression error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred while processing the image.'}, status=500)
    
logger = logging.getLogger(__name__)

@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def resize_to_100kb_view(request):
    """Function-based view for resizing images to 100KB"""
    
    if request.method == 'GET':
        context = {
            'page_title': 'Resize Image to 100KB Online Free | Compress Photos to 100KB | resizeimages.tools',
            'meta_description': 'Resize images to exactly 100KB online for free. Perfect for high-quality professional profiles, portfolios, and premium document submissions.',
            'keywords': 'resize image to 100kb, compress image to 100kb, reduce photo to 100kb, 100 kilobyte image, high quality compression',
            'canonical_url': 'https://resizeimages.tools/resize-image-to-100kb/',
            'focus_keyword': 'resize image to 100kb'
        }
        return render(request, 'image_app/resize_to_100kb.html', context)
    
    # POST request - Image processing
    try:
        image_file = request.FILES.get('image_file')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

        # Check file size (10MB limit)
        if image_file.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 10MB'}, status=400)

        # Check file type
        if not image_file.content_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
        
        # Get form data with proper default handling (100KB for this page)
        target_size_kb = request.POST.get('target_size_kb', '100')
        
        # Convert to integer and validate
        try:
            target_size_kb = int(target_size_kb)
        except (ValueError, TypeError):
            target_size_kb = 100  # Fallback to default for 100KB page
        
        # Ensure target size is within valid range
        if target_size_kb < 5:
            target_size_kb = 5
        elif target_size_kb > 1000:
            target_size_kb = 1000
        
        preserve_exif = request.POST.get('preserve_exif') == 'on'
        auto_rotate = request.POST.get('auto_rotate', 'on') == 'on'
        
        logger.info(f"Processing image with target size: {target_size_kb}KB")
        
        # Open and process image
        with Image.open(image_file) as image:
            if auto_rotate:
                image = process_image_orientation(image)
            
            compressed_data, stats = compress_image_to_kb(
                image,
                target_size_kb=target_size_kb,
                preserve_exif=preserve_exif
            )
        
        # Generate filename
        base_filename = os.path.splitext(image_file.name)[0]
        output_filename = f"{base_filename}_resized_{target_size_kb}kb.jpg"
        
        # Prepare response
        response = HttpResponse(compressed_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(compressed_data)
        response['X-Original-Size'] = str(image_file.size)
        response['X-Compressed-Size'] = str(len(compressed_data))
        response['X-Target-Size'] = str(target_size_kb * 1024)
        response['X-Quality-Used'] = str(stats.get('quality_used', 'unknown'))
        
        logger.info(f"Successfully processed image: {output_filename}, final size: {len(compressed_data)} bytes")

        return response

    except Exception as e:
        logger.error(f"KB compression error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred while processing the image.'}, status=500)


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def compress_to_50kb(request):
    """Function-based view for compressing images to 50KB with quality options
    
    SEO Keywords: compress image to 50kb, compress jpeg to 50kb, 
    photo compressor to 50kb, photo resize 50 kb, image compressor to 50kb

    """
    
    if request.method == 'GET':
        context = {
            'page_title': 'Compress Image to 50KB Online Free | Photo Compressor 50KB | JPEG to 50KB',
            'meta_description': 'Compress image to 50KB, compress JPEG to 50KB, and photo resize 50KB online free. Professional photo compressor to 50KB for job applications, resumes, and uploads. Instant results!',
            'keywords': 'compress image to 50kb, compress jpeg to 50kb, photo compressor to 50kb, photo resize 50 kb, reduce image to 50kb, compress photo to 50kb, 50kb image compressor',
            'canonical_url': 'https://resizeimages.tools/compress-to-50kb/',
            'focus_keyword': 'compress image to 50kb',
            'schema_markup': {
                '@context': 'https://schema.org',
                '@type': 'WebApplication',
                'name': 'Compress Image to 50KB - Photo Compressor',
                'description': 'Free online photo compressor to 50KB. Compress image to 50KB, compress JPEG to 50KB, and photo resize 50KB instantly for job applications and uploads.',
                'url': 'https://resizeimages.tools/compress-to-50kb/',
                'applicationCategory': 'MultimediaApplication',
                'operatingSystem': 'Any',
                'offers': {
                    '@type': 'Offer',
                    'price': '0',
                    'priceCurrency': 'USD'
                },
                'featureList': [
                    'Compress image to 50KB',
                    'Compress JPEG to 50KB', 
                    'Photo compressor to 50KB',
                    'Photo resize 50 KB',
                    'Free online compression',
                    'No registration required',
                    'Instant results'
                ]
            }
        }
        return render(request, 'image_app/compress-to-50kb.html', context)
    
    # POST request - Image processing
    try:
        image_file = request.FILES.get('image_file')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

        # Check file size (10MB limit)
        if image_file.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 10MB'}, status=400)

        # Check file type
        if not image_file.content_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
        
        # Get form data with proper default handling (50KB for this page)
        target_size_kb = request.POST.get('target_size_kb', '50')
        quality_mode = request.POST.get('quality_mode', 'balanced')  # high, balanced, maximum
        
        # Convert to integer and validate
        try:
            target_size_kb = int(target_size_kb)
        except (ValueError, TypeError):
            target_size_kb = 50  # Fallback to default for 50KB page
        
        # Ensure target size is within valid range
        if target_size_kb < 5:
            target_size_kb = 5
        elif target_size_kb > 1000:
            target_size_kb = 1000
        
        # Quality mode affects the compression strategy
        preserve_exif = request.POST.get('preserve_exif') == 'on'
        auto_rotate = request.POST.get('auto_rotate', 'on') == 'on'
        
        logger.info(f"Compressing image to 50KB with quality mode: {quality_mode}")
        
        # Open and process image
        with Image.open(image_file) as image:
            if auto_rotate:
                image = process_image_orientation(image)
            
            # Use compression with quality mode consideration
            compressed_data, stats = compress_image_to_kb(
                image,
                target_size_kb=target_size_kb,
                preserve_exif=preserve_exif,
                max_iterations=15 if quality_mode == 'high' else 10  # More iterations for better quality
            )
        
        # Generate SEO-friendly filename with keywords
        base_filename = os.path.splitext(image_file.name)[0]
        output_filename = f"{base_filename}_compressed_50kb.jpg"
        
        # Prepare response
        response = HttpResponse(compressed_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(compressed_data)
        response['X-Original-Size'] = str(image_file.size)
        response['X-Compressed-Size'] = str(len(compressed_data))
        response['X-Target-Size'] = str(target_size_kb * 1024)
        response['X-Quality-Used'] = str(stats.get('quality_used', 'unknown'))
        response['X-Quality-Mode'] = quality_mode
        
        logger.info(f"Successfully compressed image to 50KB: {output_filename}, final size: {len(compressed_data)} bytes, mode: {quality_mode}")

        return response

    except Exception as e:
        logger.error(f"50KB compression error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred while compressing the image to 50KB.'}, status=500)


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def compress_to_100kb(request):
    """Function-based view for compressing images to 100KB with quality options
    
    SEO Keywords: compress image to 100kb, compress jpeg to 100kb, 
    image compressor to 100kb, resize image to 100kb, photo compressor 100kb
    """
    
    if request.method == 'GET':
        context = {
            'page_title': 'Compress Image to 100KB Online Free | JPEG to 100KB Compressor | Image Compressor 100KB',
            'meta_description': 'Compress image to 100KB, compress JPEG to 100KB, and resize image to 100KB online free. Professional image compressor to 100KB for high-quality photos, portfolios, and premium uploads.',
            'keywords': 'compress image to 100kb, compress jpeg to 100kb, image compressor to 100kb, resize image to 100kb, photo compressor 100kb, reduce image to 100kb, 100kb image compressor',
            'canonical_url': 'https://resizeimages.tools/compress-to-100kb/',
            'focus_keyword': 'compress image to 100kb',
            'schema_markup': {
                '@context': 'https://schema.org',
                '@type': 'WebApplication',
                'name': 'Compress Image to 100KB - Professional Image Compressor',
                'description': 'Free online image compressor to 100KB. Compress image to 100KB, compress JPEG to 100KB, and resize image to 100KB with premium quality retention.',
                'url': 'https://resizeimages.tools/compress-to-100kb/',
                'applicationCategory': 'MultimediaApplication',
                'operatingSystem': 'Any',
                'offers': {
                    '@type': 'Offer',
                    'price': '0',
                    'priceCurrency': 'USD'
                },
                'featureList': [
                    'Compress image to 100KB',
                    'Compress JPEG to 100KB',
                    'Image compressor to 100KB',
                    'Resize image to 100KB',
                    'High-quality compression',
                    'Free unlimited use',
                    'No watermarks'
                ]
            }
        }
        return render(request, 'image_app/compress-to-100kb.html', context)
    
    # POST request - Image processing
    try:
        image_file = request.FILES.get('image_file')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

        # Check file size (10MB limit)
        if image_file.size > 10 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 10MB'}, status=400)

        # Check file type
        if not image_file.content_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
        
        # Get form data with proper default handling (100KB for this page)
        target_size_kb = request.POST.get('target_size_kb', '100')
        quality_mode = request.POST.get('quality_mode', 'balanced')  # premium, balanced, maximum
        
        # Convert to integer and validate
        try:
            target_size_kb = int(target_size_kb)
        except (ValueError, TypeError):
            target_size_kb = 100  # Fallback to default for 100KB page
        
        # Ensure target size is within valid range
        if target_size_kb < 5:
            target_size_kb = 5
        elif target_size_kb > 1000:
            target_size_kb = 1000
        
        # Quality mode affects the compression strategy
        preserve_exif = request.POST.get('preserve_exif') == 'on'
        auto_rotate = request.POST.get('auto_rotate', 'on') == 'on'
        
        logger.info(f"Compressing image to 100KB with quality mode: {quality_mode}")
        
        # Open and process image
        with Image.open(image_file) as image:
            if auto_rotate:
                image = process_image_orientation(image)
            
            # Use compression with quality mode consideration
            # More iterations for better quality at 100KB
            max_iterations = 20 if quality_mode == 'premium' else 15
            compressed_data, stats = compress_image_to_kb(
                image,
                target_size_kb=target_size_kb,
                preserve_exif=preserve_exif,
                max_iterations=max_iterations
            )
        
        # Generate SEO-friendly filename with keywords
        base_filename = os.path.splitext(image_file.name)[0]
        output_filename = f"{base_filename}_compressed_100kb.jpg"
        
        # Prepare response
        response = HttpResponse(compressed_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(compressed_data)
        response['X-Original-Size'] = str(image_file.size)
        response['X-Compressed-Size'] = str(len(compressed_data))
        response['X-Target-Size'] = str(target_size_kb * 1024)
        response['X-Quality-Used'] = str(stats.get('quality_used', 'unknown'))
        response['X-Quality-Mode'] = quality_mode
        
        logger.info(f"Successfully compressed image to 100KB: {output_filename}, final size: {len(compressed_data)} bytes, mode: {quality_mode}")

        return response

    except Exception as e:
        logger.error(f"100KB compression error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred while compressing the image to 100KB.'}, status=500)


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def compress_to_200kb(request):
    """Function-based view for compressing images to 200KB with quality options
    
    SEO Keywords: compress image to 200kb, compress jpeg to 200kb, 
    image compressor to 200kb, resize image to 200kb, photo compressor 200kb,
    reduce pdf size to 200kb
    """
    
    if request.method == 'GET':
        context = {
            'page_title': 'Compress Image to 200KB Online Free | JPEG to 200KB | Photo Compressor 200KB',
            'meta_description': 'Compress image to 200KB, compress JPEG to 200KB, and resize image to 200KB online free. Professional photo compressor to 200KB for high-quality images, presentations, and documents.',
            'keywords': 'compress image to 200kb, compress jpeg to 200kb, image compressor to 200kb, resize image to 200kb, photo compressor to 200kb, reduce pdf size to 200kb, 200kb image compressor',
            'canonical_url': 'https://resizeimages.tools/compress-to-200kb/',
            'focus_keyword': 'compress image to 200kb',
            'schema_markup': {
                '@context': 'https://schema.org',
                '@type': 'WebApplication',
                'name': 'Compress Image to 200KB - Premium Image Compressor',
                'description': 'Free online image compressor to 200KB. Compress image to 200KB, compress JPEG to 200KB, and resize image to 200KB with exceptional quality retention for professional use.',
                'url': 'https://resizeimages.tools/compress-to-200kb/',
                'applicationCategory': 'MultimediaApplication',
                'operatingSystem': 'Any',
                'offers': {
                    '@type': 'Offer',
                    'price': '0',
                    'priceCurrency': 'USD'
                },
                'featureList': [
                    'Compress image to 200KB',
                    'Compress JPEG to 200KB',
                    'Image compressor to 200KB',
                    'Resize image to 200KB',
                    'Photo compressor to 200KB',
                    'Premium quality compression',
                    'Free unlimited use',
                    'No watermarks',
                    'Professional results'
                ]
            }
        }
        return render(request, 'image_app/compress-to-200kb.html', context)
    
    # POST request - Image processing
    try:
        image_file = request.FILES.get('image_file')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image file provided'}, status=400)

        # Check file size (15MB limit for larger target size)
        if image_file.size > 15 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File too large. Maximum size is 15MB'}, status=400)

        # Check file type
        if not image_file.content_type.startswith('image/'):
            return JsonResponse({'success': False, 'error': 'Invalid file type. Please upload an image.'}, status=400)
        
        # Get form data with proper default handling (200KB for this page)
        target_size_kb = request.POST.get('target_size_kb', '200')
        quality_mode = request.POST.get('quality_mode', 'premium')  # premium, balanced, maximum
        
        # Convert to integer and validate
        try:
            target_size_kb = int(target_size_kb)
        except (ValueError, TypeError):
            target_size_kb = 200  # Fallback to default for 200KB page
        
        # Ensure target size is within valid range
        if target_size_kb < 5:
            target_size_kb = 5
        elif target_size_kb > 1000:
            target_size_kb = 1000
        
        # Quality mode affects the compression strategy
        preserve_exif = request.POST.get('preserve_exif') == 'on'
        auto_rotate = request.POST.get('auto_rotate', 'on') == 'on'
        
        logger.info(f"Compressing image to 200KB with quality mode: {quality_mode}")
        
        # Open and process image
        with Image.open(image_file) as image:
            if auto_rotate:
                image = process_image_orientation(image)
            
            # Use compression with quality mode consideration
            # More iterations for better quality at 200KB
            max_iterations = 25 if quality_mode == 'premium' else 20
            compressed_data, stats = compress_image_to_kb(
                image,
                target_size_kb=target_size_kb,
                preserve_exif=preserve_exif,
                max_iterations=max_iterations
            )
        
        # Generate SEO-friendly filename with keywords
        base_filename = os.path.splitext(image_file.name)[0]
        output_filename = f"{base_filename}_compressed_200kb.jpg"
        
        # Prepare response
        response = HttpResponse(compressed_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(compressed_data)
        response['X-Original-Size'] = str(image_file.size)
        response['X-Compressed-Size'] = str(len(compressed_data))
        response['X-Target-Size'] = str(target_size_kb * 1024)
        response['X-Quality-Used'] = str(stats.get('quality_used', 'unknown'))
        response['X-Quality-Mode'] = quality_mode
        
        logger.info(f"Successfully compressed image to 200KB: {output_filename}, final size: {len(compressed_data)} bytes, mode: {quality_mode}")

        return response

    except Exception as e:
        logger.error(f"200KB compression error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred while compressing the image to 200KB.'}, status=500)