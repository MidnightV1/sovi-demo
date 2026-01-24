// 图片处理工具模块
class ImageProcessor {
    constructor(options = {}) {
        this.maxWidth = options.maxWidth || 800;
        this.maxHeight = options.maxHeight || 800;
        this.targetFileSize = options.targetFileSize || 200 * 1024; // 200KB
        this.webpQuality = options.webpQuality || 0.8;
        this.jpegQuality = options.jpegQuality || 0.85;
        this.maxFileSize = options.maxFileSize || 20 * 1024 * 1024; // 20MB
        
        // 支持的图片格式
        this.supportedFormats = [
            'image/jpeg',
            'image/jpg', 
            'image/png',
            'image/webp',
            'image/heic',
            'image/heif'
        ];
        
        this.webpSupported = null;
        this.checkWebPSupport();
    }
    
    // 检测WebP支持
    async checkWebPSupport() {
        if (this.webpSupported !== null) return this.webpSupported;
        
        return new Promise((resolve) => {
            const webP = new Image();
            webP.onload = webP.onerror = () => {
                this.webpSupported = (webP.height === 2);
                resolve(this.webpSupported);
            };
            webP.src = 'data:image/webp;base64,UklGRjoAAABXRUJQVlA4IC4AAACyAgCdASoCAAIALmk0mk0iIiIiIgBoSygABc6WWgAA/veff/0PP8bA//LwYAAA';
        });
    }
    
    // 验证文件
    isValidImageFile(file) {
        // 检查文件类型
        if (!this.supportedFormats.includes(file.type.toLowerCase())) {
            throw new Error(`不支持的文件格式: ${file.type}。支持的格式: JPG, PNG, WebP, HEIC`);
        }
        
        // 检查文件大小
        if (file.size > this.maxFileSize) {
            throw new Error(`文件太大: ${(file.size / 1024 / 1024).toFixed(1)}MB。最大支持: ${this.maxFileSize / 1024 / 1024}MB`);
        }
        
        return true;
    }
    
    // 获取文件大小（字节）
    getDataUrlSize(dataUrl) {
        const base64 = dataUrl.split(',')[1];
        return Math.round(base64.length * 3 / 4);
    }
    
    // 计算目标尺寸
    calculateTargetSize(originalWidth, originalHeight, maxSize) {
        if (originalWidth <= maxSize && originalHeight <= maxSize) {
            return { width: originalWidth, height: originalHeight };
        }
        
        const ratio = Math.min(maxSize / originalWidth, maxSize / originalHeight);
        return {
            width: Math.round(originalWidth * ratio),
            height: Math.round(originalHeight * ratio)
        };
    }
    
    // 获取EXIF方向信息
    getImageOrientation(file) {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const view = new DataView(e.target.result);
                    const length = view.byteLength;
                    
                    // 检查是否是JPEG文件
                    if (length < 2 || view.getUint16(0, false) !== 0xFFD8) {
                        resolve(1); // 不是JPEG，返回正常方向
                        return;
                    }
                    
                    let offset = 2;
                    
                    while (offset < length - 1) {
                        // 确保有足够的字节读取marker
                        if (offset + 4 > length) {
                            break;
                        }
                        
                        if (view.getUint16(offset + 2, false) <= 8) {
                            resolve(1);
                            return;
                        }
                        
                        const marker = view.getUint16(offset, false);
                        offset += 2;
                        
                        if (marker === 0xFFE1) {
                            // EXIF段
                            if (offset + 8 > length) break;
                            
                            const segmentLength = view.getUint16(offset, false);
                            if (offset + segmentLength > length) break;
                            
                            const little = offset + 6 < length && view.getUint16(offset + 6, false) === 0x4949;
                            offset += segmentLength;
                            
                            if (offset + 2 > length) break;
                            const tags = view.getUint16(offset, little);
                            offset += 2;
                            
                            for (let i = 0; i < tags; i++) {
                                const tagOffset = offset + i * 12;
                                if (tagOffset + 12 > length) break;
                                
                                const tag = view.getUint16(tagOffset, little);
                                if (tag === 0x0112) {
                                    const orientationOffset = tagOffset + 8;
                                    if (orientationOffset + 2 <= length) {
                                        resolve(view.getUint16(orientationOffset, little));
                                        return;
                                    }
                                }
                            }
                        } else if ((marker & 0xFF00) !== 0xFF00) {
                            break;
                        } else {
                            // 跳过其他段
                            if (offset + 2 > length) break;
                            const segmentLength = view.getUint16(offset, false);
                            offset += segmentLength;
                        }
                    }
                    
                    resolve(1); // 默认方向
                } catch (error) {
                    console.warn('EXIF解析出错，使用默认方向:', error);
                    resolve(1); // 出错时返回默认方向
                }
            };
            reader.readAsArrayBuffer(file.slice(0, 64 * 1024));
        });
    }
    
    // 应用EXIF方向旋转
    applyImageRotation(canvas, ctx, orientation) {
        const { width, height } = canvas;
        
        switch (orientation) {
            case 2:
                ctx.transform(-1, 0, 0, 1, width, 0);
                break;
            case 3:
                ctx.transform(-1, 0, 0, -1, width, height);
                break;
            case 4:
                ctx.transform(1, 0, 0, -1, 0, height);
                break;
            case 5:
                canvas.width = height;
                canvas.height = width;
                ctx.transform(0, 1, 1, 0, 0, 0);
                break;
            case 6:
                canvas.width = height;
                canvas.height = width;
                ctx.transform(0, 1, -1, 0, height, 0);
                break;
            case 7:
                canvas.width = height;
                canvas.height = width;
                ctx.transform(0, -1, -1, 0, height, width);
                break;
            case 8:
                canvas.width = height;
                canvas.height = width;
                ctx.transform(0, -1, 1, 0, 0, width);
                break;
        }
    }
    
    // 主处理函数
    async processImage(file, options = {}) {
        try {
            // 验证文件
            this.isValidImageFile(file);
            
            const processingOptions = { ...options };
            const onProgress = processingOptions.onProgress || (() => {});
            
            onProgress(10, '开始处理图片...');
            
            // 获取EXIF方向信息
            const orientation = await this.getImageOrientation(file);
            onProgress(20, '分析图片信息...');
            
            // 创建Image对象
            const img = new Image();
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            
            return new Promise((resolve, reject) => {
                img.onload = async () => {
                    try {
                        onProgress(40, '处理图片尺寸...');
                        
                        // 计算目标尺寸
                        const targetSize = this.calculateTargetSize(
                            img.width, 
                            img.height, 
                            Math.max(this.maxWidth, this.maxHeight)
                        );
                        
                        // 设置Canvas尺寸
                        canvas.width = targetSize.width;
                        canvas.height = targetSize.height;
                        
                        // 应用EXIF旋转
                        if (orientation > 1) {
                            this.applyImageRotation(canvas, ctx, orientation);
                        }
                        
                        // 绘制图片
                        ctx.drawImage(img, 0, 0, targetSize.width, targetSize.height);
                        
                        onProgress(60, '优化图片质量...');
                        
                        // 确定输出格式
                        const useWebP = await this.checkWebPSupport();
                        const outputFormat = useWebP ? 'image/webp' : 'image/jpeg';
                        let quality = useWebP ? this.webpQuality : this.jpegQuality;
                        
                        // 调整质量以控制文件大小
                        let dataUrl;
                        let attempts = 0;
                        const maxAttempts = 8;
                        
                        do {
                            dataUrl = canvas.toDataURL(outputFormat, quality);
                            const currentSize = this.getDataUrlSize(dataUrl);
                            
                            if (currentSize <= this.targetFileSize || quality <= 0.3) {
                                break;
                            }
                            
                            quality -= 0.1;
                            attempts++;
                            
                            onProgress(60 + (attempts / maxAttempts) * 30, `优化中... (${Math.round(currentSize / 1024)}KB)`);
                        } while (attempts < maxAttempts);
                        
                        onProgress(95, '生成预览...');
                        
                        // 生成缩略图（用于预览）
                        const thumbCanvas = document.createElement('canvas');
                        const thumbCtx = thumbCanvas.getContext('2d');
                        const thumbSize = 150;
                        
                        thumbCanvas.width = thumbSize;
                        thumbCanvas.height = thumbSize;
                        
                        // 计算缩略图裁剪区域（居中裁剪）
                        const scale = Math.max(thumbSize / targetSize.width, thumbSize / targetSize.height);
                        const scaledWidth = targetSize.width * scale;
                        const scaledHeight = targetSize.height * scale;
                        const offsetX = (thumbSize - scaledWidth) / 2;
                        const offsetY = (thumbSize - scaledHeight) / 2;
                        
                        thumbCtx.drawImage(canvas, offsetX, offsetY, scaledWidth, scaledHeight);
                        const thumbnailDataUrl = thumbCanvas.toDataURL('image/jpeg', 0.8);
                        
                        onProgress(100, '处理完成');
                        
                        // 返回处理结果
                        const result = {
                            success: true,
                            originalFile: file,
                            processedDataUrl: dataUrl,
                            thumbnailDataUrl: thumbnailDataUrl,
                            metadata: {
                                originalSize: file.size,
                                processedSize: this.getDataUrlSize(dataUrl),
                                originalDimensions: { width: img.width, height: img.height },
                                processedDimensions: targetSize,
                                format: outputFormat,
                                quality: quality,
                                compressionRatio: (1 - this.getDataUrlSize(dataUrl) / file.size).toFixed(2),
                                orientation: orientation
                            }
                        };
                        
                        // 清理Canvas
                        canvas.width = 1;
                        canvas.height = 1;
                        thumbCanvas.width = 1;
                        thumbCanvas.height = 1;
                        
                        resolve(result);
                        
                    } catch (error) {
                        reject(new Error(`图片处理失败: ${error.message}`));
                    }
                };
                
                img.onerror = () => {
                    reject(new Error('无法加载图片，请检查文件是否损坏'));
                };
                
                // 开始加载图片
                img.src = URL.createObjectURL(file);
            });
            
        } catch (error) {
            return {
                success: false,
                error: error.message
            };
        }
    }
    
    // 批量处理图片
    async processBatchImages(files, options = {}) {
        const results = [];
        const onProgress = options.onProgress || (() => {});
        
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            onProgress(i, files.length, `处理第 ${i + 1} 张图片...`);
            
            const result = await this.processImage(file, {
                onProgress: (progress, message) => {
                    onProgress(i, files.length, message, progress);
                }
            });
            
            results.push(result);
        }
        
        onProgress(files.length, files.length, '所有图片处理完成');
        return results;
    }
}

// 创建全局实例
window.ImageProcessor = ImageProcessor;
window.imageProcessor = new ImageProcessor({
    maxWidth: 800,
    maxHeight: 800,
    targetFileSize: 200 * 1024, // 200KB
    webpQuality: 0.8,
    jpegQuality: 0.85,
    maxFileSize: 20 * 1024 * 1024 // 20MB
});
