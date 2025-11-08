from django import forms

class ImageUploadForm(forms.Form):
    image_file = forms.ImageField(label='Choose Image')
    quality = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=80,
        widget=forms.NumberInput(attrs={'type': 'range', 'class': 'quality-slider'})
    )
    preserve_exif = forms.BooleanField(required=False, initial=True)
    auto_rotate = forms.BooleanField(required=False, initial=True)

class ImageResizeToKBForm(forms.Form):
    image_file = forms.ImageField(
        label='Choose Image',
        help_text='Upload JPEG, PNG, or WebP images (max 10MB)'
    )
    target_size_kb = forms.IntegerField(
        min_value=5,
        max_value=1000,
        initial=20,
        label='Target Size (KB)',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '20'
        }),
        help_text='Enter desired file size in KB (5-1000 KB)'
    )
    preserve_exif = forms.BooleanField(
        required=False, 
        initial=False,
        label='Preserve EXIF Data',
        help_text='Keep original photo metadata (may increase file size)'
    )
    auto_rotate = forms.BooleanField(
        required=False, 
        initial=True,
        label='Auto-rotate Image',
        help_text='Automatically rotate based on EXIF orientation'
    )
    
    def clean_target_size_kb(self):
        target_size = self.cleaned_data.get('target_size_kb')
        if target_size and (target_size < 5 or target_size > 1000):
            raise forms.ValidationError('Target size must be between 5 KB and 1000 KB')
        return target_size
