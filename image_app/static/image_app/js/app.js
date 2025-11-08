document.addEventListener('DOMContentLoaded', () => {
    const dragArea = document.getElementById('dragArea');
    const fileInput = document.getElementById('fileInput');
    const previewContainer = document.getElementById('previewContainer');
    const uploadForm = document.getElementById('uploadForm');
    const qualitySlider = document.getElementById('qualitySlider');
    const qualityValue = document.getElementById('qualityValue');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const compressedImagesContainer = document.getElementById('compressedImagesContainer');
    const compressedPreviewGrid = document.getElementById('compressedPreviewGrid');
    const darkModeToggle = document.getElementById('darkModeToggle');
    const totalSavedElement = document.getElementById('totalSaved');

    // Dark mode toggle
    darkModeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        const isDarkMode = document.body.classList.contains('dark-mode');
        localStorage.setItem('darkMode', isDarkMode);
        darkModeToggle.innerHTML = isDarkMode ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';
    });

    // Check for saved dark mode preference
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
        darkModeToggle.innerHTML = '<i class="fas fa-sun"></i>';
    }

    // Quality slider
    qualitySlider.addEventListener('input', (e) => {
        qualityValue.textContent = `${e.target.value}%`;
    });

    // Drag and drop functionality
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dragArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dragArea.addEventListener(eventName, () => {
            dragArea.classList.add('active');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dragArea.addEventListener(eventName, () => {
            dragArea.classList.remove('active');
        });
    });

    dragArea.addEventListener('drop', handleFiles);
    fileInput.addEventListener('change', handleFiles);

    function handleFiles(e) {
        let files = e.dataTransfer ? e.dataTransfer.files : e.target.files;
        previewFiles(files);
    }

    function previewFiles(files) {
        previewContainer.innerHTML = '';
        [...files].forEach(file => {
            if (file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = e => {
                    const preview = createImagePreview(e.target.result, file.name, file.size);
                    previewContainer.appendChild(preview);
                };
                reader.readAsDataURL(file);
            }
        });
    }

    function createImagePreview(src, name, size) {
        const div = document.createElement('div');
        div.className = 'image-preview fade-in';
        div.innerHTML = `
            <img src="${src}" alt="${name}" class="w-full h-32 object-cover">
            <div class="preview-overlay">
                <p class="text-white text-sm">${name}</p>
                <p class="text-white text-xs">${formatBytes(size)}</p>
            </div>
        `;
        return div;
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(uploadForm);
        
        progressContainer.classList.remove('hidden');
        progressBar.style.width = '0%';

        try {
            const response = await fetch('/compress/', {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const result = await response.json();
                displayCompressedImages(result.compressed_images);
                updateCompressionStats(result.total_saved);
                showToast('Images compressed successfully!', 'success');
            } else {
                throw new Error('Compression failed');
            }
        } catch (error) {
            showToast('An error occurred during compression', 'error');
        } finally {
            progressContainer.classList.add('hidden');
        }
    });

    function displayCompressedImages(images) {
        compressedImagesContainer.classList.remove('hidden');
        compressedPreviewGrid.innerHTML = '';

        images.forEach(image => {
            const card = document.createElement('div');
            card.className = 'relative group bg-white rounded-lg shadow-md overflow-hidden fade-in';
            card.innerHTML = `
                <img src="${image.url}" alt="Compressed image" 
                     class="w-full h-32 object-cover transition-transform duration-300 group-hover:scale-105">
                <div class="absolute inset-0 bg-black bg-opacity-50 opacity-0 group-hover:opacity-100 
                            transition-opacity duration-300 flex flex-col items-center justify-center text-white">
                    <p class="text-sm mb-2">Original: ${formatBytes(image.original_size)}</p>
                    <p class="text-sm mb-2">Compressed: ${formatBytes(image.compressed_size)}</p>
                    <p class="text-sm">Saved: ${formatBytes(image.saved_bytes)}</p>
                    <a href="${image.url}" download class="mt-2 bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-md transition-colors duration-300">
                        Download
                    </a>
                </div>
            `;
            compressedPreviewGrid.appendChild(card);
        });
    }

    function updateCompressionStats(totalSaved) {
        totalSavedElement.textContent = formatBytes(totalSaved);
        totalSavedElement.classList.add('animate-pulse');
        setTimeout(() => {
            totalSavedElement.classList.remove('animate-pulse');
        }, 1000);
    }

    function showToast(message, type) {
        const toast = document.createElement('div');
        toast.className = `fixed bottom-4 right-4 p-4 rounded-lg shadow-lg z-50 ${
            type === 'success' ? 'bg-green-500' : 'bg-red-500'
        } text-white transform translate-y-full opacity-0 transition-all duration-300`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.classList.remove('translate-y-full', 'opacity-0');
        }, 100);

        setTimeout(() => {
            toast.classList.add('translate-y-full', 'opacity-0');
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 3000);
    }

    // Feature cards
    const features = [
        { icon: 'fas fa-star', title: 'High Quality', description: 'Compress images without significant quality loss' },
        { icon: 'fas fa-bolt', title: 'Fast Processing', description: 'Quick compression for multiple images' },
        { icon: 'fas fa-lock', title: 'Secure', description: 'Your images are processed securely and not stored' },
        { icon: 'fas fa-desktop', title: 'Any Device', description: 'Works on desktop, tablet, and mobile' },
        { icon: 'fas fa-download', title: 'Batch Download', description: 'Download all compressed images at once' },
        { icon: 'fas fa-cog', title: 'Customizable', description: 'Adjust compression settings to your needs' }
    ];

    const featureCards = document.getElementById('featureCards');
    features.forEach(feature => {
        const card = document.createElement('div');
        card.className = 'feature-card bg-white p-6 rounded-lg shadow-md transition-all duration-300 hover:shadow-lg';
        card.innerHTML = `
            <i class="${feature.icon} text-4xl text-blue-500 mb-4"></i>
            <h3 class="text-xl font-semibold mb-2">${feature.title}</h3>
            <p class="text-gray-600">${feature.description}</p>
        `;
        featureCards.appendChild(card);
    });

    // Update copyright year
    document.getElementById('currentYear').textContent = new Date().getFullYear();
});

