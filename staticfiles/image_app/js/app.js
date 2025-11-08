const elements = {
    dragArea: document.getElementById('dragArea'),
    fileInput: document.getElementById('fileInput'),
    previewContainer: document.getElementById('previewContainer'),
    uploadForm: document.getElementById('uploadForm'),
    progressContainer: document.getElementById('progressContainer'),
    progressBar: document.getElementById('progressBar'),
    compressingMessage: document.getElementById('compressingMessage'),
    qualitySlider: document.getElementById('qualitySlider'),
    qualityValue: document.getElementById('qualityValue'),
    qualityBubble: document.querySelector('.quality-bubble'),
    themeToggle: document.getElementById('themeToggle'),
    compressionCount: document.getElementById('compressionCount'),
    totalSaved: document.getElementById('totalSaved'),
    fileQueue: document.getElementById('fileQueue'),
    queueList: document.getElementById('queueList'),
    resultsList: document.getElementById('resultsList'),
    resultsContainer: document.getElementById('resultsContainer')
};

// State Management
const state = {
    files: [],
    totalCompressed: 0,
    totalSaved: 0,
    isDarkMode: false,
    quality: 80
};

// Theme Management
class ThemeManager {
    constructor() {
        this.isDarkMode = localStorage.getItem('darkMode') === 'true';
        this.applyTheme();
        this.bindEvents();
    }

    toggleTheme() {
        this.isDarkMode = !this.isDarkMode;
        localStorage.setItem('darkMode', this.isDarkMode);
        this.applyTheme();
    }

    applyTheme() {
        document.body.classList.toggle('dark-mode', this.isDarkMode);
        const icon = elements.themeToggle.querySelector('i');
        icon.className = this.isDarkMode ? 'fas fa-sun' : 'fas fa-moon';
    }

    bindEvents() {
        elements.themeToggle.addEventListener('click', () => this.toggleTheme());
    }
}

// Toast Notification System
class ToastNotification {
    static show(message, type = 'success', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
            <span>${message}</span>
        `;
        
        document.getElementById('toastContainer').appendChild(toast);
        
        // Trigger reflow for animation
        void toast.offsetWidth;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
}

// File Manager
class FileManager {
    constructor() {
        this.files = new Map();
        this.bindEvents();
    }

    addFiles(fileList) {
        [...fileList].forEach(file => {
            if (file.type.startsWith('image/')) {
                this.files.set(file.name, {
                    file,
                    status: 'pending',
                    originalSize: file.size
                });
            } else {
                ToastNotification.show(`${file.name} is not an image file`, 'error');
            }
        });
        this.updateUI();
    }

    removeFile(fileName) {
        this.files.delete(fileName);
        this.updateUI();
        ToastNotification.show(`${fileName} removed from queue`);
    }

    updateUI() {
        this.updatePreviewContainer();
        this.updateQueueList();
    }

    updatePreviewContainer() {
        elements.previewContainer.innerHTML = '';
        this.files.forEach((fileData, fileName) => {
            this.createPreviewElement(fileData.file);
        });
    }

    createPreviewElement(file) {
        const reader = new FileReader();
        reader.onloadend = () => {
            const preview = document.createElement('div');
            preview.className = 'relative group';
            preview.innerHTML = `
                <div class="relative overflow-hidden rounded-lg shadow-md image-preview">
                    <img src="${reader.result}" class="w-32 h-32 object-cover" alt="Preview">
                    <div class="absolute inset-0 bg-black bg-opacity-40 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col items-center justify-center">
                        <p class="text-white text-sm mb-2">${this.formatBytes(file.size)}</p>
                        <button class="bg-red-500 text-white px-2 py-1 rounded-md text-xs hover:bg-red-600 transition-colors duration-300"
                                onclick="fileManager.removeFile('${file.name}')">
                            Remove
                        </button>
                    </div>
                </div>
            `;
            elements.previewContainer.appendChild(preview);
        };
        reader.readAsDataURL(file);
    }

    updateQueueList() {
        elements.fileQueue.classList.toggle('hidden', this.files.size === 0);
        elements.queueList.innerHTML = '';
        
        this.files.forEach((fileData, fileName) => {
            const queueItem = document.createElement('div');
            queueItem.className = 'flex items-center justify-between bg-gray-50 p-2 rounded';
            queueItem.innerHTML = `
                <span class="text-sm">${fileName}</span>
                <span class="text-xs text-gray-500">${this.formatBytes(fileData.originalSize)}</span>
                <span class="text-xs ${this.getStatusColor(fileData.status)}">${fileData.status}</span>
            `;
            elements.queueList.appendChild(queueItem);
        });
    }

    getStatusColor(status) {
        const colors = {
            pending: 'text-yellow-500',
            processing: 'text-blue-500',
            completed: 'text-green-500',
            error: 'text-red-500'
        };
        return colors[status] || colors.pending;
    }

    formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    bindEvents() {
        // Drag and Drop Events
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            elements.dragArea.addEventListener(eventName, this.preventDefaults);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            elements.dragArea.addEventListener(eventName, () => {
                elements.dragArea.classList.add('active');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            elements.dragArea.addEventListener(eventName, () => {
                elements.dragArea.classList.remove('active');
            });
        });

        elements.dragArea.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            this.addFiles(files);
        });

        elements.fileInput.addEventListener('change', (e) => {
            this.addFiles(e.target.files);
        });
    }

    preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
}

// Compression Manager
class CompressionManager {
    constructor() {
        this.bindEvents();
    }

    async compressImage(file) {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');
                    
                    // Calculate new dimensions while maintaining aspect ratio
                    let width = img.width;
                    let height = img.height;
                    const maxDimension = 1920; // Max dimension for compressed image
                    
                    if (width > maxDimension || height > maxDimension) {
                        if (width > height) {
                            height = (height / width) * maxDimension;
                            width = maxDimension;
                        } else {
                            width = (width / height) * maxDimension;
                            height = maxDimension;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob((blob) => {
                        resolve(blob);
                    }, 'image/jpeg', state.quality / 100);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }

    async processFiles() {
        const files = Array.from(fileManager.files.values());
        let processed = 0;
        
        for (const fileData of files) {
            try {
                fileData.status = 'processing';
                fileManager.updateUI();
                
                const compressedBlob = await this.compressImage(fileData.file);
                const savedBytes = fileData.file.size - compressedBlob.size;
                state.totalSaved += savedBytes;
                
                fileData.status = 'completed';
                fileData.compressedSize = compressedBlob.size;
                fileData.savedBytes = savedBytes;
                
                processed++;
                this.updateProgress(processed / files.length * 100);
                
            } catch (error) {
                fileData.status = 'error';
                ToastNotification.show(`Failed to compress ${fileData.file.name}`, 'error');
            }
            
            fileManager.updateUI();
        }

        this.showResults();
    }

    updateProgress(percent) {
        elements.progressBar.style.width = `${percent}%`;
        elements.compressingMessage.textContent = `Processing... ${Math.round(percent)}%`;
    }

    showResults() {
        state.totalCompressed += fileManager.files.size;
        elements.compressionCount.textContent = `Compressed: ${state.totalCompressed} images`;
        elements.totalSaved.textContent = this.formatBytes(state.totalSaved);
        
        elements.resultsContainer.classList.remove('hidden');
        ToastNotification.show('Compression completed successfully!');
    }

    bindEvents() {
        elements.uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (fileManager.files.size === 0) {
                ToastNotification.show('Please add some images first', 'error');
                return;
            }
            
            elements.progressContainer.classList.remove('hidden');
            await this.processFiles();
            elements.progressContainer.classList.add('hidden');
        });

        // Quality slider events
        elements.qualitySlider.addEventListener('input', (e) => {
            state.quality = e.target.value;
            elements.qualityValue.textContent = `${state.quality}%`;
            elements.qualityBubble.textContent = `${state.quality}%`;
            elements.qualityBubble.style.left = `${state.quality}%`;
            elements.qualityBubble.classList.remove('hidden');
        });

        elements.qualitySlider.addEventListener('mouseenter', () => {
            elements.qualityBubble.classList.remove('hidden');
        });

        elements.qualitySlider.addEventListener('mouseleave', () => {
            elements.qualityBubble.classList.add('hidden');
        });
    }

    formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
}

// Initialize
const themeManager = new ThemeManager();
const fileManager = new FileManager();
const compressionManager = new CompressionManager();

// Register Service Worker for PWA support
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/service-worker.js')
            .then(registration => {
                console.log('ServiceWorker registration successful');
            })
            .catch(err => {
                console.log('ServiceWorker registration failed: ', err);
            });
    });
}