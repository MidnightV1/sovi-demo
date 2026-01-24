// 聊天页面 JavaScript (简洁版)
document.addEventListener('DOMContentLoaded', function() {
    
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesContainer = document.getElementById('messages-container');
    const historyBtn = document.getElementById('history-btn');
    const historySidebar = document.getElementById('history-sidebar');
    const historyOverlay = document.getElementById('history-overlay');
    const closeHistoryBtn = document.getElementById('close-history');
    const newChatBtn = document.getElementById('new-chat-btn');
    const loadingOverlay = document.getElementById('loading-overlay');
    const imageUpload = document.getElementById('image-upload');
    const cameraUpload = document.getElementById('camera-upload');
    const imageUploadBtn = document.getElementById('image-upload-btn');
    const uploadMenuOverlay = document.getElementById('upload-menu-overlay');
    const cameraOption = document.getElementById('camera-option');
    const fileOption = document.getElementById('file-option');
    const uploadMenuCancel = document.getElementById('upload-menu-cancel');
    const imagePreview = document.getElementById('image-preview');
    const removeImageBtn = document.getElementById('remove-image');
    const imageProcessing = document.getElementById('image-processing');
    const inputBar = document.getElementById('input-bar');
    const textInputWrapper = document.getElementById('text-input-wrapper');
    // 跟随方案的追问UI元素
    const followupSheet = document.getElementById('followup-input-sheet');
    const followupCloseBtn = document.getElementById('followup-close-btn');
    const followupQuoteText = document.getElementById('followup-quote-text');
    const followupTextarea = document.getElementById('followup-textarea');
    const followupCancelBtn = document.getElementById('followup-cancel-btn');
    const followupSendBtn = document.getElementById('followup-send-btn');
    // 悬浮按钮与工具栏（动态创建）
    let followBtn = null;
    let toolbar = null;
    let selectionTimer = null;
    let selectionStartTime = 0;
    let currentSelectedText = '';
    let currentSelectionRange = null;
    
    // 配置常量（支持 window.* 覆盖）
    const MAGIC_EFFECT_ENABLED = (typeof window !== 'undefined' && typeof window.MAGIC_EFFECT_ENABLED !== 'undefined') ? window.MAGIC_EFFECT_ENABLED : true;
    const TYPE_SPEED_CN = (typeof window !== 'undefined' && typeof window.TYPE_SPEED_CN !== 'undefined') ? window.TYPE_SPEED_CN : 18;
    const TYPE_SPEED_EN = (typeof window !== 'undefined' && typeof window.TYPE_SPEED_EN !== 'undefined') ? window.TYPE_SPEED_EN : 40;
    const MD_RENDER_INTERVAL = (typeof window !== 'undefined' && typeof window.MD_RENDER_INTERVAL !== 'undefined') ? window.MD_RENDER_INTERVAL : 100;
    const AUTO_SCROLL_THRESHOLD = (typeof window !== 'undefined' && typeof window.AUTO_SCROLL_THRESHOLD !== 'undefined') ? window.AUTO_SCROLL_THRESHOLD : 4; // px

    // 设备类型检测（仅在明确为 boolean 的情况下接受 window.isMobileDevice 覆盖）；
    // 移除触控/粗指针启发，避免桌面触屏被误判为移动端；采用保守 UA 检测。
    const isMobileDevice = (() => {
        try {
            if (typeof window !== 'undefined' && typeof window.isMobileDevice === 'boolean') {
                return window.isMobileDevice;
            }
            const ua = (navigator.userAgent || navigator.vendor || window.opera || '').toLowerCase();
            const isIphone = /iphone|ipod/.test(ua);
            const isAndroidPhone = /android/.test(ua) && /mobile/.test(ua);
            // 将平板也视为“移动端”以使用弹出菜单
            const isIpad = /ipad/.test(ua);
            const isAndroidTablet = /android/.test(ua) && !/mobile/.test(ua);
            const isGenericTablet = /tablet/.test(ua);
            return isIphone || isAndroidPhone || isIpad || isAndroidTablet || isGenericTablet;
        } catch (e) {
            return false;
        }
    })();

    let selectedImage = null;
    let processingState = 'idle'; // idle, processing, completed, error
    // 智能滚动控制标志（需在使用前定义）
    let autoScrollEnabled = true;
    let userScrolledUp = false;
    class TypingRenderer {
        constructor(targetEl, options = {}) {
            this.el = targetEl;
            this.cnDelay = options.cnDelay ?? TYPE_SPEED_CN;
            this.enDelay = options.enDelay ?? TYPE_SPEED_EN;
            this.isFinalized = false;
            this.timer = null;
            this.lastRenderTime = 0;
            this.renderInterval = MD_RENDER_INTERVAL || 200;

            // 尾部缓冲：未形成稳定块的文本
            this.rawBuffer = '';
            
            // 当前正在显示的内容（用于打字效果）
            this.displayedContent = '';

            // 解析状态（用于判定“稳定边界”）：围栏代码/数学公式是否闭合
            this._state = {
                fenceOpen: false,  // ``` ... ```
                // 仅做成对计数的启发式判断；在代码围栏内不解析数学
                mathDisplayOpen: false, // $$...$$
                // inline 使用简单配对启发；足够满足常见用法
                // 这里不单独维护 inline 开关，使用闭合下标检测
            };

            // 绑定
            this._schedule = this._schedule.bind(this);
            this._processBuffer = this._processBuffer.bind(this);
            this._findStableBoundary = this._findStableBoundary.bind(this);
            this.markCompleted = this.markCompleted.bind(this);
        }

        static tokenize(text) {
            const tokens = [];
            let i = 0;
            while (i < text.length) {
                const ch = text[i];
                if (ch === '\n') { tokens.push('\n'); i++; continue; }
                if (/^[\u4e00-\u9fff]$/.test(ch)) { tokens.push(ch); i++; continue; }
                if (/\s/.test(ch)) {
                    let j = i + 1; while (j < text.length && /\s/.test(text[j]) && text[j] !== '\n') j++;
                    tokens.push(text.slice(i, j)); i = j; continue;
                }
                if (/[A-Za-z0-9_'\-]/.test(ch)) {
                    let j = i + 1; while (j < text.length && /[A-Za-z0-9_'\-]/.test(text[j])) j++;
                    tokens.push(text.slice(i, j)); i = j; continue;
                }
                tokens.push(ch); i++;
            }
            return tokens;
        }

        pushChunk(text) {
            if (!text || this.isFinalized) return;
            
            // 如果是第一次接收内容，跳过开头的空白字符
            if (!this.rawBuffer && !this.displayedContent) {
                text = text.replace(/^\s+/, '');
                if (!text) return; // 如果全是空白，直接返回
            }
            
            // 直接把文本加入尾部缓冲，同时立即触发调度
            this.rawBuffer += text;
            if (!this.timer) this._schedule();
        }

        _schedule() {
            if (this.isFinalized) { this.timer = null; return; }
            if (!this.rawBuffer || this.rawBuffer.length === 0) { this.timer = null; return; }

            // 逐字符“打字”到尾巴
            const ch = this.rawBuffer[0];
            this.rawBuffer = this.rawBuffer.slice(1);
            this.displayedContent += ch;

            // 立即更新显示当前打字内容
            this._updateDisplay();

            // 更频繁的渲染触发条件：
            // 1. 双换行（段落完成）- 立即渲染
            // 2. 单换行（行完成） - 立即渲染
            // 3. 特定标点符号后 - 适当延迟渲染
            let shouldRender = false;
            
            if (this.displayedContent.endsWith('\n\n')) {
                // 段落完成，立即渲染
                shouldRender = true;
            } else if (this.displayedContent.endsWith('\n')) {
                // 行完成，立即渲染（这是用户要求的功能）
                shouldRender = true;
            } else if (ch === '。' || ch === '!' || ch === '?' || ch === '；' || ch === '：') {
                // 中文标点句子结束，立即渲染
                shouldRender = true;
            } else if (ch === '.' || ch === '!' || ch === '?' || ch === ';' || ch === ':') {
                // 英文标点，适当延迟渲染
                const now = Date.now();
                if (now - this.lastRenderTime >= Math.max(200, this.renderInterval / 2)) {
                    shouldRender = true;
                }
            } else {
                // 节流增量渲染（保持原有逻辑）
                const now = Date.now();
                if (now - this.lastRenderTime >= this.renderInterval) {
                    shouldRender = true;
                }
            }
            
            if (shouldRender) {
                this._processBuffer();
                this.lastRenderTime = Date.now();
            }

            const isCn = /^[\u4e00-\u9fff]$/.test(ch);
            const delay = isCn ? this.cnDelay : Math.max(8, Math.floor(this.enDelay / 4));
            this.timer = setTimeout(this._schedule, delay);
        }

        // 将已形成稳定块的内容渲染为DOM并稳定追加
        _processBuffer() {
            if (!this.displayedContent) return;

            // 查找稳定边界（双换行、围栏代码闭合、LaTeX闭合）
            const stableIdx = this._findStableBoundary(this.displayedContent);
            if (stableIdx < 0) {
                // 没有稳定块，只更新临时显示
                return;
            }

            const contentToRender = this.displayedContent.slice(0, stableIdx);
            const remaining = this.displayedContent.slice(stableIdx);

            // 先移除临时显示元素，避免干扰
            const tempContent = this.el.querySelector('.temp-content');
            if (tempContent) {
                tempContent.remove();
            }

            // 只处理非空内容
            if (contentToRender && contentToRender.trim()) {
                // 在内存中渲染稳定内容，再一次性追加
                const temp = document.createElement('div');
                try { 
                    renderMarkdown(temp, contentToRender, false); 
                } catch (e) { 
                    // 如果Markdown渲染失败，直接作为文本显示
                    temp.textContent = contentToRender;
                }

                // 清理可能的空段落
                const allPs = temp.querySelectorAll('p');
                allPs.forEach(p => {
                    if (!p.textContent.trim() || p.innerHTML === '&nbsp;' || p.innerHTML.trim() === '') {
                        p.remove();
                    }
                });

                // 对新增的稳定块先做数学渲染，避免挂载后闪动
                try {
                    if (typeof window.renderMathInElementSafe === 'function') {
                        window.renderMathInElementSafe(temp);
                    }
                } catch (e) {}

                const frag = document.createDocumentFragment();
                while (temp.firstChild) frag.appendChild(temp.firstChild);
                this.el.appendChild(frag);

                // 强制重排，确保新增内容正确布局
                this.el.offsetHeight;
            }

            // 更新显示内容为剩余未渲染部分
            this.displayedContent = remaining;
            
            // 重新显示剩余的临时内容
            this._updateDisplay();

            // DOM已更新，尝试滚动到底
            if (typeof scrollToBottom === 'function') scrollToBottom();
        }

        // 计算稳定渲染边界：
        // - 优先使用“闭合事件”边界：``` 结束、$$ 结束、\) 或 \] 结束
        // - 其次使用段落边界：最后一次出现的双换行
        _findStableBoundary(text) {
            if (!text) return -1;

            // 1) 段落边界（双换行）- 最高优先级
            let boundary = -1;
            const dbl = text.lastIndexOf('\n\n');
            if (dbl !== -1) boundary = Math.max(boundary, dbl + 2);

            // 在代码围栏内部不考虑数学闭合，避免误判
            const fenceCount = (text.match(/```/g) || []).length;
            const fenceOpen = fenceCount % 2 === 1;

            // 2) 代码围栏闭合：若围栏数量为偶数，认为最后一个 ``` 是闭合点
            if (!fenceOpen) {
                const lastFence = text.lastIndexOf('```');
                if (lastFence !== -1) {
                    boundary = Math.max(boundary, lastFence + 3);
                }
            }

            // 3) 数学闭合（仅当不在围栏内时考虑）
            if (!fenceOpen) {
                // $$ display math
                const ddCount = (text.match(/\$\$/g) || []).length;
                if (ddCount % 2 === 0 && ddCount > 0) {
                    const lastDD = text.lastIndexOf('$$');
                    if (lastDD !== -1) boundary = Math.max(boundary, lastDD + 2);
                }
                // \) 与 \]
                const lastInlineClose = Math.max(text.lastIndexOf('\\)'), text.lastIndexOf('\\]'));
                if (lastInlineClose !== -1) boundary = Math.max(boundary, lastInlineClose + 2);
            }

            // 4) 单换行边界 - 支持逐行渲染
            if (boundary === -1) {
                const singleNl = text.lastIndexOf('\n');
                if (singleNl !== -1) {
                    // 检查单换行后是否有完整的行内容
                    const afterNewline = text.substring(singleNl + 1);
                    // 如果换行后的内容长度合理且不是列表项开头，则可以作为边界
                    if (afterNewline.length >= 5 && !afterNewline.match(/^\s*([\*\-\+]|\d+\.)\s/)) {
                        boundary = Math.max(boundary, singleNl + 1);
                    } else if (afterNewline.length === 0) {
                        // 空行也可以作为边界
                        boundary = Math.max(boundary, singleNl + 1);
                    }
                }
            }

            // 5) 列表完整性检查：避免在列表项中间切断
            if (boundary > 0) {
                const textUpToBoundary = text.substring(0, boundary);
                const remainingText = text.substring(boundary);
                
                // 检查边界后的文本是否以列表项开始
                const nextLineMatch = remainingText.match(/^(\s*)([\*\-\+]|\d+\.)\s+/);
                if (nextLineMatch) {
                    // 检查边界前是否有未完成的列表结构
                    const lines = textUpToBoundary.split('\n');
                    const lastLine = lines[lines.length - 1] || '';
                    const lastLineIsListItem = /^\s*([\*\-\+]|\d+\.)\s+/.test(lastLine);
                    
                    if (lastLineIsListItem && lastLine.trim().length > 0) {
                        // 如果最后一行是列表项但内容较短，等待更多内容
                        const listItemContent = lastLine.replace(/^\s*([\*\-\+]|\d+\.)\s+/, '');
                        if (listItemContent.length < 3) { // 降低阈值，允许更频繁渲染
                            return -1; // 不设边界，继续等待
                        }
                    }
                }
            }

            return boundary;
        }

        // 标记输入已完成：不再接收新内容；等缓冲打字结束后再统一 flush，维持“输出节奏”
        markCompleted() {
            this._completed = true;
            // 若当前没有定时器且缓冲已空，则尽快做最终收尾
            if (!this.timer && (!this.rawBuffer || this.rawBuffer.length === 0)) {
                // 轻微延迟，确保最后一次 _processBuffer 机会
                setTimeout(() => { 
                    if (!this.isFinalized) {
                        // 在最终flush前，清理尾部空白
                        this.displayedContent = this.displayedContent.trim();
                        this.rawBuffer = this.rawBuffer.trim();
                        this.flush(); 
                    }
                }, 80);
            }
        }

        // 更新临时显示内容
        _updateDisplay() {
            // 移除之前的临时元素
            const prevTemp = this.el.querySelector('.temp-content');
            if (prevTemp) {
                prevTemp.remove();
            }
            
            // 如果有内容需要显示，创建临时元素显示当前打字的内容
            if (this.displayedContent && this.displayedContent.trim()) {
                const tempSpan = document.createElement('span');
                tempSpan.textContent = this.displayedContent;
                tempSpan.className = 'temp-content';
                // 确保临时内容不会影响父容器的布局计算
                tempSpan.style.display = 'inline';
                tempSpan.style.whiteSpace = 'pre-wrap';
                tempSpan.style.opacity = '0.85';
                // 添加最小高度确保气泡不会收缩
                tempSpan.style.minHeight = '1.2em';
                this.el.appendChild(tempSpan);
                
                // 强制父容器重新计算布局
                this.el.style.minHeight = 'auto';
                this.el.offsetHeight; // 强制重排
            }
        }

        flush() {
            if (this.isFinalized) return;
            this.isFinalized = true;
            if (this.timer) { clearTimeout(this.timer); this.timer = null; }

            // 把尚未处理的显示内容与缓冲合并
            const finalContent = this.displayedContent + (this.rawBuffer || '');
            this.rawBuffer = '';
            this.displayedContent = '';

            // 移除临时内容元素
            const tempContent = this.el.querySelector('.temp-content');
            if (tempContent) {
                tempContent.remove();
            }

            // 重置父容器的样式
            this.el.style.minHeight = '';

            if (finalContent && finalContent.trim()) {
                const temp = document.createElement('div');
                try { renderMarkdown(temp, finalContent, false); } catch (e) { temp.textContent = finalContent; }
                
                // 清理可能的空段落
                const allPs = temp.querySelectorAll('p');
                allPs.forEach(p => {
                    if (!p.textContent.trim() || p.innerHTML === '&nbsp;' || p.innerHTML.trim() === '') {
                        p.remove();
                    }
                });
                
                const frag = document.createDocumentFragment();
                while (temp.firstChild) frag.appendChild(temp.firstChild);
                this.el.appendChild(frag);
                
                // 确保内容渲染后强制重排，避免布局异常
                this.el.offsetHeight;
            }

            // 最终统一渲染 LaTeX，避免过程抖动；并等待高度稳定后再做最终滚动
            setTimeout(() => {
                try {
                    if (typeof window.renderMathInElementSafe === 'function') {
                        window.renderMathInElementSafe(this.el);
                    }
                } catch (e) {}
                // 等待外层容器高度稳定后再滚动，避免“先到底后再被顶起”
                if (typeof waitForHeightStability === 'function' && messagesContainer) {
                    waitForHeightStability(messagesContainer, { timeout: 800, idleFrames: 2 })
                        .then(() => {
                            if (typeof scrollToBottomSettled === 'function') scrollToBottomSettled();
                            else if (typeof scrollToBottom === 'function') scrollToBottom();
                        });
                } else {
                    if (typeof scrollToBottomSettled === 'function') scrollToBottomSettled();
                    else if (typeof scrollToBottom === 'function') scrollToBottom();
                }
            }, 80);
        }
    }
    
    // 初始化字符计数功能
    initializeCharacterLimit();
    
    // 初始化不活跃检测
    initializeInactivityDetection();
    
    // 检查是否需要显示欢迎消息
    initializeChat();
    
    // 处理页面加载时已存在的历史消息的LaTeX渲染
    processExistingMessages();
    // 页面载入后若已有多条消息，滚动到底部
    setTimeout(() => { scrollToBottom(); }, 50);
    
    // 初始化时间格式化
    initializeTimeFormatting();

    // 初始化划词追问控制器
    initializeFollowUpController();
    
    // 注意：textarea高度调整已在initializeCharacterLimit()中处理
    
    // Enter 发送消息
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // 发送消息
    sendBtn.addEventListener('click', sendMessage);
    
    // 格式化用户本地时间
    function formatUserDateTime() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}`;
    }
    
    // 获取用户语言设置
    function getUserLanguage() {
        return navigator.language || navigator.userLanguage || 'en';
    }
    
    function getTimezoneOffset() {
        // 返回时区偏移量（分钟），注意JavaScript的getTimezoneOffset()返回的是相反的值
        return -new Date().getTimezoneOffset();
    }
    
    async function sendMessage() {
        const message = messageInput.value.trim();
        
        if (!message && !selectedImage) {
            return;
        }
        
        // 清空输入
        messageInput.value = '';
        messageInput.style.height = 'auto';
        sendBtn.disabled = true;
        
        // 立即显示用户消息（包括图片预览）
        const userMessageDiv = addMessage(message, 'user', selectedImage);
        
    // 立即显示AI消息占位符（loading状态）
        const aiMessageDiv = addMessage('', 'assistant');
        const contentDiv = aiMessageDiv.querySelector('.message-content');
    enableAutoScroll();
        
        // 保存当前图片信息
        const currentImageInfo = selectedImage;
        
        // 清除选中的图片（UI状态）
        if (selectedImage) {
            clearSelectedImage();
        }
        
        // 如果有图片，智能处理上传状态
        if (currentImageInfo) {
            if (currentImageInfo.uploading) {
                // 正在上传，等待完成
                try {
                    await currentImageInfo.uploadPromise;
                } catch (error) {
                    console.error('❌ 等待上传失败:', error);
                    showErrorToast('图片上传失败，请重试');
                    
                    // 移除AI消息占位符
                    if (aiMessageDiv) {
                        aiMessageDiv.remove();
                    }
                    
                    // 为用户消息添加重试按钮
                    addRetryButton(userMessageDiv, message, currentImageInfo);
                    sendBtn.disabled = false;
                    return;
                }
            } else if (!currentImageInfo.uploaded) {
                // 未上传且未在上传，立即上传
                // 图片未上传，立即上传
                try {
                    const uploadResult = await uploadImageToServer(currentImageInfo.result, currentImageInfo.originalName);
                    if (uploadResult.success) {
                        currentImageInfo.uploaded = true;
                        currentImageInfo.fileInfo = uploadResult.file_info;
                    } else {
                        throw new Error(uploadResult.message || '图片上传失败');
                    }
                } catch (error) {
                    console.error('❌ 立即上传失败:', error);
                    showErrorToast('图片上传失败，请重试');
                    
                    // 移除AI消息占位符
                    if (aiMessageDiv) {
                        aiMessageDiv.remove();
                    }
                    
                    // 为用户消息添加重试按钮
                    addRetryButton(userMessageDiv, message, currentImageInfo);
                    sendBtn.disabled = false;
                    return;
                }
            }
            // 如果已上传完成，直接继续
        }
        
        // 开始流式请求
        startStreaming(message, contentDiv, currentImageInfo ? currentImageInfo.fileInfo : null, userMessageDiv, currentImageInfo);
    }
    
    function sendMessageWithImageInfo(message, imageFileInfo, userMessageDiv = null, imageInfo = null) {
        // 如果没有传入用户消息div，则创建一个（兼容旧逻辑）
        if (!userMessageDiv) {
            userMessageDiv = addMessage(message, 'user', imageInfo);
            
            // 清除选中的图片
            if (selectedImage) {
                clearSelectedImage();
            }
            
            // 显示AI消息占位符
        const aiMessageDiv = addMessage('', 'assistant');
            const contentDiv = aiMessageDiv.querySelector('.message-content');
        enableAutoScroll();
            
            // 开始流式请求
            startStreaming(message, contentDiv, imageFileInfo, userMessageDiv, imageInfo);
        }
        // 注意：如果传入了userMessageDiv，说明是新的优化流程，AI消息已经在调用方创建了
    }
    
    function addMessage(content, type, imageData = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        
        let messageContent;
        let imageHtml = '';
        
        // 处理图片显示
        if (imageData) {
            let imgSrc;
            if (typeof imageData === 'string') {
                // 如果是字符串，直接使用作为图片URL
                imgSrc = imageData;
            } else if (imageData.dataUrl) {
                // 如果是对象，使用dataUrl属性
                imgSrc = imageData.dataUrl;
            } else {
                imgSrc = imageData;
            }
            
            if (type === 'user' && imgSrc) {
                imageHtml = `
                    <div class="message-image">
                        <img src="${imgSrc}" 
                             alt="用户上传的图片" 
                             onclick="showImageModal(this)"
                             onerror="handleImageError(this)"
                             loading="lazy"
                             data-original-src="${imgSrc}">
                    </div>
                `;
            }
        }
        
        if (type === 'user') {
            messageContent = content; // 移除默认文本，如果为空就显示为空
        } else if (typeof content === 'string' && content.trim()) {
            // Assistant消息有内容时显示内容
            messageContent = content;
        } else {
            // Assistant消息无内容时显示loading
            messageContent = '<div class="loading">正在思考<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span></div>';
        }
        
        messageDiv.innerHTML = `
            <div class="message-bubble">
                ${imageHtml}
                <div class="message-content">
                    ${messageContent}
                </div>
            </div>
        `;
        
        messagesContainer.appendChild(messageDiv);
        
    // 对用户消息也进行LaTeX渲染
    if (type === 'user' && typeof content === 'string' && content.trim()) {
            const contentDiv = messageDiv.querySelector('.message-content');
            renderMarkdown(contentDiv, content, true);
        }
        
        scrollToBottom();
        
        return messageDiv;
    }
    
    // 删除对话功能
    function deleteConversation(convId, title) {
        if (!confirm(`确定要删除对话"${title || '未命名对话'}"吗？此操作不可撤销。`)) {
            return;
        }
        
        fetch(`/api/chat/${convId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // 重新加载历史列表
                loadChatHistory();
                
                // 如果删除的是当前对话，重定向到全新页面
                if (parseInt(window.currentConvId) === parseInt(convId)) {
                    // 清空当前状态
                    window.currentConvId = null;
                    // 重定向到全新页面（这会触发页面刷新和新对话创建）
                    window.location.href = '/chat';
                }
            } else {
                alert('删除失败: ' + (data.message || '未知错误'));
            }
        })
        .catch(error => {
            console.error('删除对话失败:', error);
            alert('删除失败: ' + error.message);
        });
    }

    function startStreaming(message, contentDiv, imageFileInfo, userMessageDiv, imageInfo) {
        let accumulatedContent = '';
        let typer = null;
        let firstChunkArrived = false; // 保留loading直至首个内容块
        
        const requestData = {
            message: message,
            datetime: formatUserDateTime(),    // 添加用户本地时间
            language: getUserLanguage(),      // 添加用户语言
            timezone_offset: getTimezoneOffset() // 添加时区偏移（分钟）
        };
        
        // 检查是否为新对话
        if (typeof window.currentConvId !== 'undefined' && window.currentConvId) {
            requestData.conversation_id = window.currentConvId;
        } else {
            // 标记为新对话
            requestData.is_new_conversation = true;
        }
        
        if (imageFileInfo) {
            requestData.image_file_info = imageFileInfo;
            requestData.image_data_url = imageInfo ? imageInfo.dataUrl : null; // 用于前端显示
        }
        
        // 添加超时控制
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
            controller.abort();
        }, 60000); // 60秒超时
        
        fetch('/api/chat/send', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestData),
            signal: controller.signal
        }).then(response => {
            if (!response.ok) {
                throw new Error('网络错误');
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            // 添加心跳检测
            let lastDataTime = Date.now();
            const heartbeatInterval = setInterval(() => {
                if (Date.now() - lastDataTime > 30000) { // 30秒无数据
                    clearInterval(heartbeatInterval);
                    clearTimeout(timeoutId);
                    reader.cancel();
                    // 触发超时错误处理
                    showErrorToast('响应超时，请检查网络连接');
                    const aiMessageDiv = contentDiv.closest('.message');
                    if (aiMessageDiv) {
                        aiMessageDiv.remove();
                    }
                    addRetryButton(userMessageDiv, message, imageInfo);
                    sendBtn.disabled = false;
                }
            }, 5000); // 每5秒检查一次
            
            function readStream() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        clearTimeout(timeoutId);
                        clearInterval(heartbeatInterval);
                        return;
                    }
                    
                    // 更新数据接收时间
                    lastDataTime = Date.now();
                    
                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.substring(6));
                                
                                if (data.type === 'chunk') {
                                    // 确保数据内容存在且不为空
                                    if (data.content && data.content.length > 0) {
                                        if (MAGIC_EFFECT_ENABLED && !firstChunkArrived) {
                                            // 首块到达，清除loading并初始化打字器
                                            contentDiv.innerHTML = '';
                                            typer = new TypingRenderer(contentDiv);
                                            firstChunkArrived = true;
                                        }
                                        accumulatedContent += data.content;
                                        if (MAGIC_EFFECT_ENABLED && typer) {
                                            typer.pushChunk(data.content);
                                            // TypingRenderer 内部会在实际插入DOM后滚动
                                        } else {
                                            renderMarkdown(contentDiv, accumulatedContent);
                                            scrollToBottom();
                                        }
                                    }
                                } else if (data.type === 'complete') {
                                    // 更新当前对话ID（重要：确保后续消息发送到正确的对话）
                                    if (data.conversation_id && data.conversation_id !== window.currentConvId) {
                                        window.currentConvId = data.conversation_id;
                                        
                                        // 对话开始后，清除欢迎消息缓存
                                        // 因为欢迎消息已被激活（round_num从-1变为0），下次新对话需要重新生成
                                        if (window.welcomeCacheManager) {
                                            window.welcomeCacheManager.clearCache();
                                        }
                                    }
                                    
                                    // 最终渲染，确保内容完整和格式正确
                                    if (MAGIC_EFFECT_ENABLED && typer) {
                                        // 标记完成，保持缓冲节奏收尾；由 TypingRenderer 自行最终 flush 与滚动
                                        try { typer.markCompleted(); } catch (e) { console.warn('typer.markCompleted() 失败:', e); }
                                    } else {
                                        renderMarkdown(contentDiv, accumulatedContent, true);
                                        if (typeof waitForHeightStability === 'function' && messagesContainer) {
                                            waitForHeightStability(messagesContainer, { timeout: 800, idleFrames: 2 })
                                                .then(() => scrollToBottomSettled());
                                        } else {
                                            scrollToBottomSettled();
                                        }
                                    }
                                    // 刷新侧栏标题（若开启）
                                    try {
                                        const sidebarOpen = historySidebar && historySidebar.classList.contains('active');
                                        if (sidebarOpen) { loadChatHistory(); }
                                    } catch (e) {}
                                    
                                    // 非打字模式下，上面已做完整 LaTeX 与稳定滚动，无需重复
                                } else if (data.type === 'error') {
                                    console.error('流式响应错误:', data.message);
                                    
                                    // 显示错误提示
                                    showErrorToast('消息发送失败，请检查网络设置');
                                    
                                    // 移除AI消息占位符
                                    const aiMessageDiv = contentDiv.closest('.message');
                                    if (aiMessageDiv) {
                                        aiMessageDiv.remove();
                                    }
                                    
                                    // 为用户消息添加重试按钮
                                    addRetryButton(userMessageDiv, message, imageInfo);
                                    
                                    // 启用发送按钮
                                    sendBtn.disabled = false;
                                }
                            } catch (e) {
                                console.error('解析响应数据错误:', e);
                            }
                        }
                    }
                    
                    return readStream();
                }).catch(error => {
                    console.error('读取流错误:', error);
                    
                    // 清理资源
                    clearTimeout(timeoutId);
                    clearInterval(heartbeatInterval);
                    
                    // 显示错误提示
                    showErrorToast('消息发送失败，请检查网络设置');
                    
                    // 移除AI消息占位符
                    const aiMessageDiv = contentDiv.closest('.message');
                    if (aiMessageDiv) {
                        aiMessageDiv.remove();
                    }
                    
                    // 为用户消息添加重试按钮
                    addRetryButton(userMessageDiv, message, imageInfo);
                    
                    // 启用发送按钮
                    sendBtn.disabled = false;
                });
            }
            
            readStream();
        }).catch(error => {
            console.error('发送请求错误:', error);
            
            // 清理超时定时器
            clearTimeout(timeoutId);
            
            // 区分错误类型
            let errorMessage = '消息发送失败，请检查网络设置';
            if (error.name === 'AbortError') {
                errorMessage = '请求超时，请检查网络连接';
            }
            
            // 显示错误提示
            showErrorToast(errorMessage);
            
            // 移除AI消息占位符
            const aiMessageDiv = contentDiv.closest('.message');
            if (aiMessageDiv) {
                aiMessageDiv.remove();
            }
            
            // 为用户消息添加重试按钮
            addRetryButton(userMessageDiv, message, imageInfo);
            
            // 启用发送按钮
            sendBtn.disabled = false;
        });
    }

    // 追问：发送请求（SSE至 /api/ask-follow-up）
    function startFollowUpStreaming(quote, question, contentDiv) {
        let accumulated = '';
        let typer = null;
        let firstChunk = false;
        const requestData = {
            quote: quote,
            question: question,
            conversation_id: window.currentConvId,
            datetime: formatUserDateTime(),
            language: getUserLanguage(),
            timezone_offset: getTimezoneOffset(),
        };
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000);
        fetch('/api/ask-follow-up', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData), signal: controller.signal
        }).then(resp => {
            if (!resp.ok) throw new Error('网络错误');
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let lastDataTime = Date.now();
            const hb = setInterval(() => {
                if (Date.now() - lastDataTime > 30000) { clearInterval(hb); clearTimeout(timeoutId); reader.cancel(); showErrorToast('响应超时，请检查网络连接'); }
            }, 5000);
            function read() { return reader.read().then(({done, value}) => {
                if (done) { clearInterval(hb); clearTimeout(timeoutId); return; }
                lastDataTime = Date.now();
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.substring(6));
                        if (data.type === 'chunk') {
                            if (data.content && data.content.length > 0) {
                                if (MAGIC_EFFECT_ENABLED && !firstChunk) { contentDiv.innerHTML = ''; typer = new TypingRenderer(contentDiv); firstChunk = true; }
                                accumulated += data.content;
                                if (MAGIC_EFFECT_ENABLED && typer) { typer.pushChunk(data.content); }
                                else { renderMarkdown(contentDiv, accumulated); scrollToBottom(); }
                            }
                        } else if (data.type === 'complete') {
                            if (MAGIC_EFFECT_ENABLED && typer) { try { typer.markCompleted(); } catch(e){} }
                            else { renderMarkdown(contentDiv, accumulated, true); scrollToBottomSettled(); }
                        } else if (data.type === 'error') {
                            showErrorToast(data.message || '追问失败');
                        }
                    } catch (e) { console.error('解析追问SSE失败:', e); }
                }
                return read();
            }).catch(err => { console.error('追问SSE错误:', err); showErrorToast('追问失败，请检查网络'); }); }
            return read();
        }).catch(err => { console.error('追问请求错误:', err); showErrorToast(err.name==='AbortError'?'请求超时，请检查网络连接':'追问请求失败'); });
    }

    function initializeFollowUpController() {
        const area = document.getElementById('messages-container');
        if (!area) return;
        // 创建浮动按钮与工具栏容器
        followBtn = document.createElement('button');
        followBtn.className = 'followup-button';
        followBtn.style.display = 'none';
        followBtn.title = '发起追问';
        followBtn.setAttribute('aria-label','发起追问');
    followBtn.textContent = '？';
    document.body.appendChild(followBtn);

        toolbar = document.createElement('div');
        toolbar.className = 'selection-toolbar';
        toolbar.style.display = 'none';
        toolbar.innerHTML = `
            <button class="selection-action-btn primary" title="追问" aria-label="追问">？</button>
            <button class="selection-action-btn" title="复制" aria-label="复制">⧉</button>
        `;
        document.body.appendChild(toolbar);

        const askBtn = toolbar.children[0];
        const copyBtn = toolbar.children[1];

        function clearSelectionUI() {
            if (followBtn) followBtn.style.display = 'none';
            if (toolbar) toolbar.style.display = 'none';
        }

        function getSelectedTextInAssistant() {
            const sel = window.getSelection();
            if (!sel || sel.rangeCount === 0) return { text: '', range: null };
            const range = sel.getRangeAt(0);
            const common = range.commonAncestorContainer;
            const assistantContainers = document.querySelectorAll('.message.assistant .message-content');
            let within = false;
            assistantContainers.forEach(node => { if (node.contains(common)) within = true; });
            if (!within) return { text: '', range: null };
            const text = sel.toString();
            return { text, range };
        }

        function positionElementNearRange(el, range, offset = {x:8, y:8}) {
            try {
                const rect = range.getBoundingClientRect();
                const x = Math.min(Math.max(rect.right + offset.x, 8), window.innerWidth - 48);
                const y = Math.min(Math.max(rect.bottom + offset.y, 8), window.innerHeight - 48);
                el.style.left = x + 'px';
                el.style.top = y + 'px';
            } catch (e) {}
        }

        function openFollowupSheet(quote) {
            followupQuoteText.textContent = quote.length > 280 ? (quote.slice(0, 280) + '...') : quote;
            followupTextarea.value = '';
            followupSendBtn.disabled = true;
            followupSheet.classList.add('active');
            followupSheet.setAttribute('aria-hidden','false');
            setTimeout(() => { try { followupTextarea.focus(); } catch(e){} }, 20);
        }

        const isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);

        if (!isTouch) {
            // 桌面：鼠标事件
            area.addEventListener('mousedown', () => { selectionStartTime = performance.now(); });
            area.addEventListener('mouseup', () => {
                if (selectionTimer) clearTimeout(selectionTimer);
                selectionTimer = setTimeout(() => {
                    const { text, range } = getSelectedTextInAssistant();
                    currentSelectedText = (text || '').trim();
                    currentSelectionRange = range || null;
                    if (!currentSelectedText || currentSelectedText.length > 1500) { clearSelectionUI(); return; }
                    const elapsed = performance.now() - selectionStartTime;
                    if (elapsed < 500) {
                        // 短选择：仅显示追问按钮
                        positionElementNearRange(followBtn, range);
                        followBtn.style.display = 'flex';
                        toolbar.style.display = 'none';
                    } else {
                        // 长选择：显示工具栏
                        positionElementNearRange(toolbar, range, {x:8, y:8});
                        toolbar.style.display = 'flex';
                        followBtn.style.display = 'none';
                    }
                }, 200);
            });
        } else {
            // 移动端：使用 touch + selectionchange
            let touchStartTs = 0;
            area.addEventListener('touchstart', () => { touchStartTs = performance.now(); }, { passive: true });
            let selChangeTimer = null;
            const evalSelection = () => {
                const { text, range } = getSelectedTextInAssistant();
                currentSelectedText = (text || '').trim();
                currentSelectionRange = range || null;
                if (!currentSelectedText || currentSelectedText.length > 1500) { clearSelectionUI(); return; }
                // 移动端一律展示工具栏（长按触发选择）
                positionElementNearRange(toolbar, range || (window.getSelection() && window.getSelection().getRangeAt(0)), {x:8, y:8});
                toolbar.style.display = 'flex';
                followBtn.style.display = 'none';
            };
            document.addEventListener('selectionchange', () => {
                if (selChangeTimer) clearTimeout(selChangeTimer);
                selChangeTimer = setTimeout(evalSelection, 150);
            });
            area.addEventListener('touchend', () => {
                if (selChangeTimer) clearTimeout(selChangeTimer);
                selChangeTimer = setTimeout(evalSelection, 200);
            });
        }

        document.addEventListener('mousedown', (e) => {
            // 点击空白处隐藏
            const targets = [followBtn, toolbar, followupSheet];
            const inside = targets.some(t => t && t.contains(e.target));
            if (!inside) clearSelectionUI();
        });

        // 点击追问（浮动按钮）
        followBtn.addEventListener('click', () => {
            const quote = currentSelectedText;
            if (!quote) return;
            clearSelectionUI();
            openFollowupSheet(quote);
        });

        // 工具栏：追问/复制
        askBtn.addEventListener('click', () => {
            const quote = currentSelectedText;
            if (!quote) return;
            clearSelectionUI();
            openFollowupSheet(quote);
        });
        copyBtn.addEventListener('click', async () => {
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(currentSelectedText || '');
                } else {
                    const ta = document.createElement('textarea'); ta.value = currentSelectedText || ''; ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
                }
                showSuccessToast('已复制到剪贴板');
            } catch (e) {
                showErrorToast('复制失败');
            }
        });

        // 面板交互
        followupTextarea.addEventListener('input', () => {
            followupSendBtn.disabled = !(followupTextarea.value && followupTextarea.value.trim());
        });
        const closeSheet = () => { followupSheet.classList.remove('active'); followupSheet.setAttribute('aria-hidden','true'); };
        followupCloseBtn.addEventListener('click', closeSheet);
        followupCancelBtn.addEventListener('click', closeSheet);
        followupSendBtn.addEventListener('click', () => {
            const question = (followupTextarea.value || '').trim();
            const quote = currentSelectedText;
            if (!question) return;
            closeSheet();
            // 在消息区追加一条“用户追问”与AI占位
            const userMsgDiv = addMessage(question, 'user');
            const aiDiv = addMessage('', 'assistant');
            const contentDiv = aiDiv.querySelector('.message-content');
            enableAutoScroll();
            // 发送追问SSE
            startFollowUpStreaming(quote, question, contentDiv);
        });
    }
    
    // 为失败的用户消息添加重试按钮
    function addRetryButton(userMessageDiv, originalMessage, imageInfo) {
        // 检查是否已经有重试按钮
        const existingRetryButton = userMessageDiv.querySelector('.retry-button');
        if (existingRetryButton) {
            // 如果已经存在重试按钮，直接显示它
            existingRetryButton.style.display = 'flex';
            return;
        }
        
        // 不再添加失败样式到用户气泡，只通过重试按钮表示错误状态
        
        // 创建重试按钮
        const retryButton = document.createElement('button');
        retryButton.className = 'retry-button';
        retryButton.innerHTML = '↻';
        retryButton.title = '重试发送';
        retryButton.style.cssText = `
            position: absolute;
            left: -35px;
            top: 50%;
            transform: translateY(-50%);
            width: 28px;
            height: 28px;
            border: 2px solid #ff4757;
            background: white;
            color: #ff4757;
            border-radius: 50%;
            cursor: pointer;
            font-size: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
            z-index: 10;
        `;
        
        // 添加悬停效果
        retryButton.addEventListener('mouseenter', function() {
            this.style.background = '#ff4757';
            this.style.color = 'white';
        });
        
        retryButton.addEventListener('mouseleave', function() {
            this.style.background = 'white';
            this.style.color = '#ff4757';
        });
        
        // 添加点击事件
        retryButton.addEventListener('click', function() {
            retryMessage(userMessageDiv, originalMessage, imageInfo);
        });
        
        // 添加到消息气泡容器
        const messageBubble = userMessageDiv.querySelector('.message-bubble');
        if (messageBubble) {
            messageBubble.style.position = 'relative';
            messageBubble.appendChild(retryButton);
        }
    }
    
    // 重试发送消息
    async function retryMessage(userMessageDiv, originalMessage, imageInfo) {
        try {
            // 隐藏重试按钮
            const retryButton = userMessageDiv.querySelector('.retry-button');
            if (retryButton) {
                retryButton.style.display = 'none';
            }
            
            // 如果有图片信息，智能处理上传状态
            if (imageInfo) {
                if (imageInfo.uploading && imageInfo.uploadPromise) {
                    // 正在上传，等待完成
                    try {
                        const uploadResult = await imageInfo.uploadPromise;
                        imageInfo.uploaded = true;
                        imageInfo.fileInfo = uploadResult.file_info;
                    } catch (error) {
                        console.error('重试时等待上传失败:', error);
                        showErrorToast('消息发送失败，请检查网络设置');
                        
                        // 恢复重试按钮
                        if (retryButton) {
                            retryButton.style.display = 'flex';
                        }
                        return;
                    }
                } else if (!imageInfo.uploaded) {
                    // 未上传，立即上传
                    try {
                        const uploadResult = await uploadImageToServer(imageInfo.result, imageInfo.originalName);
                        if (uploadResult.success) {
                            imageInfo.uploaded = true;
                            imageInfo.fileInfo = uploadResult.file_info;
                        } else {
                            throw new Error(uploadResult.message || '图片上传失败');
                        }
                    } catch (error) {
                        console.error('重试时图片上传失败:', error);
                        showErrorToast('消息发送失败，请检查网络设置');
                        
                        // 恢复重试按钮
                        if (retryButton) {
                            retryButton.style.display = 'flex';
                        }
                        return;
                    }
                }
                // 如果已上传完成，直接继续
            }
            
            // 显示新的AI消息占位符
            const aiMessageDiv = addMessage('', 'assistant');
            const contentDiv = aiMessageDiv.querySelector('.message-content');
            
            // 重新开始流式请求
            startStreaming(originalMessage, contentDiv, imageInfo ? imageInfo.fileInfo : null, userMessageDiv, imageInfo);
            
        } catch (error) {
            console.error('重试失败:', error);
            showErrorToast('消息发送失败，请检查网络设置');
            
            // 恢复重试按钮
            const retryButton = userMessageDiv.querySelector('.retry-button');
            if (retryButton) {
                retryButton.style.display = 'flex';
            }
        }
    }

    function renderMarkdown(element, content, isComplete = false) {
        // --- 预处理：处理可能已经HTML格式化的内容 ---
        let processedContent = content || '';
        
        // 如果内容包含HTML实体，先解码
        if (processedContent.includes('&gt;') || processedContent.includes('&lt;') || processedContent.includes('&quot;')) {
            processedContent = processedContent
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&quot;/g, '"')
                .replace(/&amp;/g, '&');
        }
        
        // 如果内容包含<br>标签，转换回换行符
        if (processedContent.includes('<br>')) {
            processedContent = processedContent.replace(/<br\s*\/?>/gi, '\n');
        }
        
        // --- 预处理：保护代码块，避免其内容被行内规则误伤 ---
        const codeBlocks = [];
        let protectedContent = processedContent
            // ```lang\n...\n```
            .replace(/```(\w+)?\n([\s\S]*?)\n```/g, (match, lang, code) => {
                const index = codeBlocks.length;
                const escaped = String(code).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                codeBlocks.push({ lang: lang || '', code: escaped });
                return `__CODE_BLOCK_${index}__`;
            })
            // ```...```
            .replace(/```([\s\S]*?)```/g, (match, code) => {
                const index = codeBlocks.length;
                const escaped = String(code).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                codeBlocks.push({ lang: '', code: escaped });
                return `__CODE_BLOCK_${index}__`;
            });

        // --- 块级分割：用空行作为段落/块分隔 ---
        const blocks = protectedContent.trim().split(/\n{2,}/);

        // --- 语义合并：处理“有序项 + 下一块无序说明”的常见结构，
        //     如：
        //       1. 标题\n\n* 说明A\n* 说明B\n\n2. 标题...
        //     将其合并为：
        //       1. 标题\n        (8空格)* 说明A\n        (8空格)* 说明B
        //     以保证无序说明嵌套在上一有序项下。
        const normalizedBlocks = [];
        for (let i = 0; i < blocks.length; i++) {
            const cur = (blocks[i] || '').trim();
            const next = (blocks[i + 1] || '').trim();
            // 当前为“单行有序项”，下一块为“纯无序列表”
            if (/^\d+\.\s+.+$/.test(cur) && !cur.includes('\n') && next && 
                next.split(/\n/).every(l => /^\s{4,}([\*\-\+])\s+/.test(l)) && // 至少4空格缩进
                !next.split(/\n/).some(l => /^\s*\d+\.\s+/.test(l))) { // 不包含有序项
                // 保持原有缩进，不额外添加空格
                normalizedBlocks.push(cur + '\n' + next);
                i++; // 跳过 next
                continue;
            }
            normalizedBlocks.push(cur);
        }
    const htmlBlocks = normalizedBlocks.map(rawBlock => {
            const block = rawBlock.trim();
            if (!block) return ''; // 空块返回空字符串，不生成段落

            // 代码块占位
            if (/^__CODE_BLOCK_\d+__$/.test(block)) {
                const idx = parseInt(block.replace('__CODE_BLOCK_', '').replace('__', ''), 10);
                const b = codeBlocks[idx];
                const langClass = b.lang ? `language-${b.lang}` : '';
                return `<pre><code class="${langClass}">${b.code}</code></pre>`;
            }

            // 标题
            if (block.startsWith('#')) {
                if (block.startsWith('### ')) return `<h3>${_renderInline(block.slice(4))}</h3>`;
                if (block.startsWith('## ')) return `<h2>${_renderInline(block.slice(3))}</h2>`;
                if (block.startsWith('# ')) return `<h1>${_renderInline(block.slice(2))}</h1>`;
            }

            // 引用块：支持多行，> 前缀
            if (block.startsWith('>')) {
                const lines = block.split(/\n/).map(l => l.replace(/^>\s?/, ''));
                const inner = lines.join('\n').split(/\n{2,}/).map(seg => `<p>${_renderInline(seg.replace(/\n/g, '<br>'))}</p>`).join('');
                return `<blockquote>${inner}</blockquote>`;
            }

            // 列表块（无序/有序）
            if (/^(\*|\-|\+|\d+\.)\s/.test(block)) {
                return _renderListBlock(block);
            }

            // 段落中途出现列表（例如：前面一两句介绍，随后换行以 * 或 1. 开头）
            if (block.includes('\n')) {
                const lines = block.split(/\n/);
                const firstListIdx = lines.findIndex(l => /^(\s*)(\*|\-|\+|\d+\.)\s+/.test(l));
                if (firstListIdx > 0) {
                    const before = lines.slice(0, firstListIdx).join('\n');
                    const listPart = lines.slice(firstListIdx).join('\n');
                    const beforeHtml = `<p>${_renderInline(before.replace(/\n/g, '<br>'))}</p>`;
                    const listHtml = _renderListBlock(listPart);
                    return beforeHtml + listHtml;
                }
            }

            // 默认段落：段内换行保留为 <br>
            return `<p>${_renderInline(block.replace(/\n/g, '<br>'))}</p>`;
        });

        // 过滤掉空字符串，避免生成空白内容
        const filteredBlocks = htmlBlocks.filter(block => block && block.trim());
        element.innerHTML = filteredBlocks.join('');

        // 完成后统一触发 LaTeX（非打字模式会在此处执行；打字模式在 flush 内执行）
        if (isComplete && typeof window.renderMathInElementSafe === 'function') {
            try { window.renderMathInElementSafe(element); } catch (e) { console.error('LaTeX 渲染失败:', e); }
        }
    }

    // 行内渲染：先处理行内代码，再处理加粗/斜体/链接，避免互相干扰
    function _renderInline(text) {
        if (!text) return '';
        
        // 先保护LaTeX内容，避免被其他规则误伤
        const latexBlocks = [];
        let protectedText = String(text)
            // 保护行内LaTeX: $...$
            .replace(/\$([^$\n]+?)\$/g, (match, latex) => {
                const index = latexBlocks.length;
                latexBlocks.push(latex);
                return `__LATEX_INLINE_${index}__`;
            })
            // 保护块级LaTeX: $$...$$
            .replace(/\$\$([^$]+?)\$\$/g, (match, latex) => {
                const index = latexBlocks.length;
                latexBlocks.push(latex);
                return `__LATEX_BLOCK_${index}__`;
            });
        
        // 处理其他行内语法
        let result = protectedText
            // 行内代码：若反引号内包含 LaTeX 占位符或 \\(...\\)/\\[...\\]，则不包 <code>，以便后续 KaTeX 识别；否则按代码处理并转义
            .replace(/`([^`]+?)`/g, (m, inner) => {
                // 命中占位符（$...$ / $$...$$ 已在上面被保护为占位符）
                if (/__LATEX_(INLINE|BLOCK)_\d+__/.test(inner)) {
                    return inner; // 去掉反引号，保留占位符供后续还原为 LaTeX
                }
                // 兜底：支持 \\(...\\) 与 \\[...\\] 形式
                if (/\\\(|\\\[|\\\)|\\\]/.test(inner)) {
                    return inner;
                }
                // 其他情况按真正行内代码处理并进行 HTML 转义
                const escaped = String(inner)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
                return `<code>${escaped}</code>`;
            })
            // 粗体
            .replace(/\*\*([^\s*](?:[\s\S]*?[^\s*])?)\*\*/g, '<strong>$1</strong>')
            // 斜体（避免匹配到 ** 内部以及跨行）
            .replace(/(^|[^*])\*([^\s][^*\n]*?[^\s])\*(?!\*)/g, '$1<em>$2</em>')
            // 链接
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
        
        // 恢复LaTeX内容
        result = result
            .replace(/__LATEX_INLINE_(\d+)__/g, (match, index) => {
                return `$${latexBlocks[index]}$`;
            })
            .replace(/__LATEX_BLOCK_(\d+)__/g, (match, index) => {
                return `$$${latexBlocks[index]}$$`;
            });
        
        return result;
    }

    // 列表块渲染（支持缩进嵌套的 ul/ol，并保留非匹配行作为当前项正文）
    function _renderListBlock(block) {
        const lines = block.split(/\n/);
        let html = '';
        const stack = []; // 形如 [{type:'ol'|'ul'}]

        // 改进的缩进计算：更精确的列表层级判定
        let minIndent = null;
        const listItemIndents = [];
        
        for (const raw of lines) {
            const m = raw.match(/^(\s*)(\*|\d+\.)\s+/);
            if (m) {
                const indLen = (m[1] || '').length;
                listItemIndents.push(indLen);
                if (minIndent === null || indLen < minIndent) minIndent = indLen;
            }
        }
        if (minIndent === null) minIndent = 0;
        
        // 计算实际使用的缩进级别，避免过度嵌套
        const uniqueIndents = [...new Set(listItemIndents)].sort((a, b) => a - b);
        const indentLevelMap = new Map();
        uniqueIndents.forEach((indent, index) => {
            indentLevelMap.set(indent, index);
        });

        // 当前缩进深度：基于实际使用的缩进级别
        const depthOf = (indent) => {
            // 找到最接近的缩进级别
            let closestIndent = uniqueIndents[0] || 0;
            for (const level of uniqueIndents) {
                if (level <= indent) {
                    closestIndent = level;
                } else {
                    break;
                }
            }
            return indentLevelMap.get(closestIndent) || 0;
        };

        const openList = (type, startNum = null) => {
            if (type === 'ol') {
                const startAttr = startNum && startNum !== '1' ? ` start="${startNum}"` : '';
                html += `<ol${startAttr}>`;
            } else {
                html += '<ul>';
            }
            stack.push({ type });
        };
        const closeList = () => {
            const cur = stack.pop();
            if (!cur) return;
            html += `</${cur.type}>`;
        };
        const ensureDepthAndType = (depth, type, startNum) => {
            // 调整到目标深度
            while (stack.length > depth) closeList();
            while (stack.length < depth) openList('ul'); // 默认用 ul 填充层级
            // 该层级若类型不同则切换
            const cur = stack[stack.length - 1];
            if (!cur || cur.type !== type) {
                // 关闭再打开
                if (cur) closeList();
                openList(type, startNum);
            }
        };

        // 追踪当前 li 是否已打开（为了拼接后续正文行）
        let openLi = false;
        const closeLi = () => { if (openLi) { html += '</li>'; openLi = false; } };

        for (const raw of lines) {
            // 分析缩进与标记
            const mOl = raw.match(/^(\s*)(\d+)\.\s+(.*)$/);
            const mUl = raw.match(/^(\s*)([\*\-\+])\s+(.*)$/);
            const indent = (raw.match(/^\s*/)[0] || '').length;
            let depth = depthOf(indent);

            if (mOl || mUl) {
                const isOl = !!mOl;
                const type = isOl ? 'ol' : 'ul';
                const startNum = isOl ? mOl[2] : null;
                const content = isOl ? mOl[3] : mUl[3];

                // 改进的嵌套约束：基于实际层级数量而不是固定限制
                if (type === 'ul') {
                    // 限制无序列表最大嵌套深度为3级，但基于实际缩进情况
                    depth = Math.min(depth, Math.min(2, uniqueIndents.length - 1));
                }

                // 确保列表容器就位
                ensureDepthAndType(depth, type, startNum);

                // 结束上一项
                closeLi();

                // 打开新项
                html += `<li>${_renderInline(content)}`;
                openLi = true;
            } else {
                // 非列表行：如果处于列表中，则作为当前项附加段落/换行
                if (stack.length > 0) {
                    if (!openLi) { html += '<li>'; openLi = true; }
                    const text = raw.trim();
                    if (text) {
                        // 保留行内换行
                        html += `<br>${_renderInline(text)}`;
                    }
                }
                // 若不在列表中则忽略（该函数仅处理列表块）
            }
        }
        // 关闭尾项与所有列表
        closeLi();
        while (stack.length) closeList();
        return html;
    }
    
    // 智能自动滚动函数（变量已在顶部声明）
    function enableAutoScroll() { autoScrollEnabled = true; userScrolledUp = false; }
    function disableAutoScrollTemporarily() { userScrolledUp = true; }
    function shouldAutoScroll() {
        if (!autoScrollEnabled) return false;
        if (!messagesContainer) return false;
        // 使用统一阈值（小阈值更接近“真·底部”感受）
        const distanceToBottom = messagesContainer.scrollHeight - messagesContainer.clientHeight - messagesContainer.scrollTop;
        return !userScrolledUp || distanceToBottom <= AUTO_SCROLL_THRESHOLD;
    }
    function scrollToBottom() {
        if (!messagesContainer) return;
        if (!shouldAutoScroll()) return;
        const prevBehavior = messagesContainer.style.scrollBehavior;
        messagesContainer.style.scrollBehavior = 'auto';
        const doScroll = () => {
            messagesContainer.scrollTop = messagesContainer.scrollHeight - messagesContainer.clientHeight;
        };
        requestAnimationFrame(() => {
            doScroll();
            requestAnimationFrame(() => {
                doScroll();
                messagesContainer.style.scrollBehavior = prevBehavior || '';
            });
        });
    }
    function scrollToBottomSettled() {
        scrollToBottom();
        setTimeout(scrollToBottom, 60);
        setTimeout(scrollToBottom, 120);
    }

    // 等待容器高度在连续若干帧内保持不变，或超时
    function waitForHeightStability(container, options = {}) {
        const timeout = options.timeout ?? 600;
        const idleFrames = options.idleFrames ?? 2;
        return new Promise((resolve) => {
            let last = container.scrollHeight;
            let stableFrames = 0;
            let cancelled = false;
            const onFrame = () => {
                if (cancelled) return;
                const cur = container.scrollHeight;
                if (cur === last) {
                    stableFrames += 1;
                } else {
                    stableFrames = 0;
                    last = cur;
                }
                if (stableFrames >= idleFrames) {
                    resolve();
                } else {
                    requestAnimationFrame(onFrame);
                }
            };
            const to = setTimeout(() => {
                cancelled = true; // 超时则直接认为稳定
                resolve();
            }, timeout);
            requestAnimationFrame(onFrame);
        });
    }
    if (messagesContainer) {
        let scrollDebounce;
        messagesContainer.addEventListener('scroll', () => {
            clearTimeout(scrollDebounce);
            // 如果用户上滑（非接近底部），暂停自动滚动
            const distance = messagesContainer.scrollHeight - messagesContainer.clientHeight - messagesContainer.scrollTop;
            const atBottom = distance <= AUTO_SCROLL_THRESHOLD; // 与判断保持一致
            if (!atBottom) userScrolledUp = true; else userScrolledUp = false;
            // 停止后短暂保留状态
            scrollDebounce = setTimeout(() => {}, 150);
        }, { passive: true });
    }
    
    // 历史记录相关功能
    if (historyBtn) {
        historyBtn.addEventListener('click', loadChatHistory);
    }
    
    if (closeHistoryBtn) {
        closeHistoryBtn.addEventListener('click', closeHistory);
    }
    
    if (historyOverlay) {
        historyOverlay.addEventListener('click', closeHistory);
    }
    
    if (newChatBtn) {
        newChatBtn.addEventListener('click', startNewChat);
    }
    
    // 智能图片上传按钮
    if (imageUploadBtn) {
        imageUploadBtn.addEventListener('click', handleUploadButtonClick);
    }
    
    // 图片上传相关
    if (imageUpload) {
        imageUpload.addEventListener('change', (e) => handleImageSelect(e, 'file'));
    }
    
    if (cameraUpload) {
        cameraUpload.addEventListener('change', (e) => handleImageSelect(e, 'camera'));
    }
    
    // 移动端上传菜单
    if (cameraOption) {
        cameraOption.addEventListener('click', () => {
            hideUploadMenu();
            cameraUpload.click();
        });
    }
    
    if (fileOption) {
        fileOption.addEventListener('click', () => {
            hideUploadMenu();
            imageUpload.click();
        });
    }
    
    if (uploadMenuCancel) {
        uploadMenuCancel.addEventListener('click', hideUploadMenu);
    }
    
    if (uploadMenuOverlay) {
        uploadMenuOverlay.addEventListener('click', (e) => {
            if (e.target === uploadMenuOverlay) {
                hideUploadMenu();
            }
        });
    }
    
    if (removeImageBtn) {
        removeImageBtn.addEventListener('click', clearSelectedImage);
    }
    
    // 拖拽上传功能
    if (textInputWrapper && messageInput) {
        // 防止默认的拖拽行为
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            textInputWrapper.addEventListener(eventName, preventDefaults, false);
            messageInput.addEventListener(eventName, preventDefaults, false);
        });
        
        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        // 拖拽视觉反馈
        ['dragenter', 'dragover'].forEach(eventName => {
            textInputWrapper.addEventListener(eventName, () => {
                textInputWrapper.classList.add('drag-over');
            });
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            textInputWrapper.addEventListener(eventName, () => {
                textInputWrapper.classList.remove('drag-over');
            });
        });
        
        // 处理文件拖拽
        textInputWrapper.addEventListener('drop', handleDrop);
        messageInput.addEventListener('drop', handleDrop);
    }
    
    // 剪贴板粘贴图片
    if (messageInput) {
        messageInput.addEventListener('paste', handlePaste);
    }
    
    // 处理拖拽文件
    function handleDrop(event) {
        const files = event.dataTransfer.files;
        if (files.length > 0) {
            const imageFiles = Array.from(files).filter(file => 
                file.type.startsWith('image/')
            );
            
            if (imageFiles.length > 0) {
                handleImageSelect({ target: { files: [imageFiles[0]] } }, 'drop');
            } else {
                showImageError('请拖拽图片文件');
            }
        }
    }
    
    // 处理剪贴板粘贴
    function handlePaste(event) {
        const items = event.clipboardData.items;
        
        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (file) {
                    handleImageSelect({ target: { files: [file] } }, 'paste');
                    event.preventDefault(); // 防止粘贴到文本框
                }
                break;
            }
        }
    }
    
    // 智能上传按钮点击处理
    function handleUploadButtonClick() {
        if (isMobileDevice) {
            // 移动端：显示选择菜单
            showUploadMenu();
        } else {
            // PC端：直接打开文件选择器
            imageUpload.click();
        }
    }
    
    // 显示上传选择菜单（移动端）
    function showUploadMenu() {
        if (uploadMenuOverlay) {
            uploadMenuOverlay.style.display = 'flex';
            // 添加动画效果
            setTimeout(() => {
                uploadMenuOverlay.style.opacity = '1';
            }, 10);
        }
    }
    
    // 隐藏上传选择菜单
    function hideUploadMenu() {
        if (uploadMenuOverlay) {
            uploadMenuOverlay.style.opacity = '0';
            setTimeout(() => {
                uploadMenuOverlay.style.display = 'none';
            }, 300);
        }
    }
    
    // 增强的图片选择处理函数
    async function handleImageSelect(event, source = 'file') {
        const file = event.target.files[0];
        if (!file) return;
        
        try {
            // 显示处理状态
            showImageProcessing();
            processingState = 'processing';
            
            // 使用图片处理器处理图片
            const result = await window.imageProcessor.processImage(file, {
                onProgress: updateProcessingProgress
            });
            
            if (result.success) {
                // 处理成功，保存本地数据并立即开始后台上传
                selectedImage = {
                    dataUrl: result.processedDataUrl,
                    result: result,
                    originalName: file.name,
                    uploaded: false,  // 标记为未上传
                    uploading: false, // 是否正在上传
                    uploadPromise: null // 上传的Promise对象
                };
                showImagePreview(result);
                processingState = 'completed';
                updateProcessingProgress(100, '图片准备完成');
                
                // 立即开始后台上传（并发优化）
                startBackgroundUpload(selectedImage);
                
            } else {
                // 处理失败
                throw new Error(result.error);
            }
            
        } catch (error) {
            console.error('❌ 图片处理失败:', error);
            showErrorToast('消息发送失败，请检查网络设置');
            processingState = 'error';
        } finally {
            // 隐藏处理状态
            setTimeout(() => {
                hideImageProcessing();
            }, processingState === 'completed' ? 1000 : 2000);
        }
    }
    
    // 后台上传函数（并发优化）
    async function startBackgroundUpload(imageInfo) {
        if (imageInfo.uploading || imageInfo.uploaded) {
            return; // 避免重复上传
        }
        
        imageInfo.uploading = true;
        
        // 创建上传Promise
        imageInfo.uploadPromise = uploadImageToServer(imageInfo.result, imageInfo.originalName)
            .then(uploadResult => {
                if (uploadResult.success) {
                    imageInfo.uploaded = true;
                    imageInfo.fileInfo = uploadResult.file_info;
                    return uploadResult;
                } else {
                    throw new Error(uploadResult.message || '图片上传失败');
                }
            })
            .catch(error => {
                console.error('❌ 后台上传失败:', error);
                imageInfo.uploaded = false;
                throw error;
            })
            .finally(() => {
                imageInfo.uploading = false;
            });
        
        return imageInfo.uploadPromise;
    }
    
    // 显示图片处理进度
    function showImageProcessing() {
        if (imageProcessing) {
            imageProcessing.style.display = 'block';
            const progressFill = document.getElementById('processing-progress-fill');
            const progressText = document.getElementById('processing-progress-text');
            
            if (progressFill) progressFill.style.width = '0%';
            if (progressText) progressText.textContent = '0%';
        }
    }
    
    // 更新处理进度
    function updateProcessingProgress(progress, message) {
        const progressFill = document.getElementById('processing-progress-fill');
        const progressText = document.getElementById('processing-progress-text');
        const processingText = document.querySelector('.processing-text');
        
        if (progressFill) {
            progressFill.style.width = `${progress}%`;
        }
        
        if (progressText) {
            progressText.textContent = `${Math.round(progress)}%`;
        }
        
        if (processingText && message) {
            processingText.textContent = message;
        }
    }
    
    // 隐藏图片处理状态
    function hideImageProcessing() {
        if (imageProcessing) {
            imageProcessing.style.display = 'none';
        }
    }
    
    // 显示图片预览
    function showImagePreview(result) {
        if (!imagePreview) return;
        
        const previewImage = document.getElementById('preview-image');
        const imageMeta = document.getElementById('image-meta');
        
        if (previewImage) {
            previewImage.src = result.thumbnailDataUrl || result.processedDataUrl;
        }
        
        if (imageMeta) {
            const { metadata } = result;
            imageMeta.innerHTML = `
                <div class="meta-info">
                    <span class="meta-item">📏 ${metadata.processedDimensions.width}×${metadata.processedDimensions.height}</span>
                    <span class="meta-item">📦 ${(metadata.processedSize / 1024).toFixed(0)}KB</span>
                    <span class="meta-item">🗜️ ${(metadata.compressionRatio * 100).toFixed(0)}%</span>
                </div>
            `;
        }
        
        imagePreview.style.display = 'block';
        
        // 重新绑定删除按钮
        const newRemoveBtn = document.getElementById('remove-image');
        if (newRemoveBtn) {
            newRemoveBtn.addEventListener('click', clearSelectedImage);
        }
        
        // 启用发送按钮
        if (sendBtn) {
            sendBtn.disabled = false;
        }
    }
    
    // 显示统一错误提示
    function showErrorToast(message = '消息发送失败，请检查网络设置') {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-toast';
        errorDiv.textContent = message;
        errorDiv.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #ff4757;
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 14px;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(255, 71, 87, 0.3);
            animation: slideInDown 0.3s ease-out;
        `;
        
        // 添加动画样式
        if (!document.querySelector('#error-toast-styles')) {
            const style = document.createElement('style');
            style.id = 'error-toast-styles';
            style.textContent = `
                @keyframes slideInDown {
                    from { transform: translateX(-50%) translateY(-100%); opacity: 0; }
                    to { transform: translateX(-50%) translateY(0); opacity: 1; }
                }
            `;
            document.head.appendChild(style);
        }
        
        document.body.appendChild(errorDiv);
        
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.style.animation = 'slideInDown 0.3s ease-out reverse';
                setTimeout(() => {
                    if (errorDiv.parentNode) {
                        errorDiv.parentNode.removeChild(errorDiv);
                    }
                }, 300);
            }
        }, 4000);
    }

    // 成功提示
    function showSuccessToast(message = '已完成') {
        const toast = document.createElement('div');
        toast.className = 'success-toast';
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #2ecc71;
            color: #fff;
            padding: 10px 16px;
            border-radius: 8px;
            font-size: 14px;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(46, 204, 113, 0.3);
            animation: slideInDown 0.3s ease-out;
        `;
        document.body.appendChild(toast);
        setTimeout(() => {
            if (toast.parentNode) {
                toast.style.animation = 'slideInDown 0.3s ease-out reverse';
                setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
            }
        }, 2000);
    }

    // 显示图片错误
    function showImageError(message) {
        // 可以显示一个临时的错误提示
        const errorDiv = document.createElement('div');
        errorDiv.className = 'image-error-toast';
        errorDiv.textContent = `图片处理失败: ${message}`;
        errorDiv.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #ff4757;
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 14px;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(255, 71, 87, 0.3);
        `;
        
        document.body.appendChild(errorDiv);
        
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.parentNode.removeChild(errorDiv);
            }
        }, 4000);
    }
    
    // 上传图片到服务器
    async function uploadImageToServer(processedResult, originalName) {
        try {
            const response = await fetch('/api/upload-image', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    image_data: processedResult.processedDataUrl,
                    image_type: processedResult.metadata.format,
                    original_name: originalName,
                    metadata: processedResult.metadata
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const result = await response.json();
            if (!result.success) {
                throw new Error(result.message || '上传失败');
            }
            
            return result;
            
        } catch (error) {
            console.error('图片上传失败:', error);
            throw error;
        }
    }
    
    // 清除选中的图片
    function clearSelectedImage() {
        selectedImage = null;
        processingState = 'idle';
        
        if (imagePreview) {
            imagePreview.style.display = 'none';
        }
        
        if (imageUpload) {
            imageUpload.value = '';
        }
        
        if (cameraUpload) {
            cameraUpload.value = '';
        }
        
        // 更新发送按钮状态
        if (sendBtn && messageInput) {
            sendBtn.disabled = !messageInput.value.trim();
        }
    }
    
    function loadChatHistory() {
        // 直接显示历史记录侧栏和遮罩层
        if (historySidebar) {
            historySidebar.classList.add('active');
        }
        if (historyOverlay) {
            historyOverlay.classList.add('active');
        }
        
        fetch('/api/conversations')
            .then(response => {
                if (!response.ok) {
                    throw new Error('网络错误: ' + response.status);
                }
                return response.json();
            })
            .then(data => {
                const historyList = document.getElementById('history-list');
                if (historyList) {
                    historyList.innerHTML = '';
                    
                    if (data.success && data.conversations && data.conversations.length > 0) {
                        data.conversations.forEach(conv => {
                            const item = document.createElement('div');
                            item.className = 'history-item';
                            item.innerHTML = `
                                <div class="history-content">
                                    <div class="history-title">${conv.title || '未命名对话'}</div>
                                    <div class="history-time">${conv.updated_at ? TimeFormatter.getRelativeTime(conv.updated_at) : '时间未知'}</div>
                                </div>
                                <button class="delete-btn" data-conv-id="${conv.conversation_id}" title="删除对话">删除</button>
                            `;
                            
                            // 对话条目点击事件
                            const historyContent = item.querySelector('.history-content');
                            historyContent.addEventListener('click', () => {
                                window.location.href = `/chat?conversation_id=${conv.conversation_id}`;
                            });
                            
                            // 删除按钮点击事件
                            const deleteBtn = item.querySelector('.delete-btn');
                            deleteBtn.addEventListener('click', (e) => {
                                e.stopPropagation(); // 防止触发对话条目的点击事件
                                deleteConversation(conv.conversation_id, conv.title);
                            });
                            
                            historyList.appendChild(item);
                        });
                    } else {
                        historyList.innerHTML = '<div class="no-history">暂无对话历史</div>';
                    }
                }
            })
            .catch(error => {
                console.error('加载历史记录失败:', error);
                const historyList = document.getElementById('history-list');
                if (historyList) {
                    historyList.innerHTML = '<div class="error">加载历史记录失败: ' + error.message + '</div>';
                }
            });
    }
    
    function closeHistory() {
        if (historySidebar) {
            historySidebar.classList.remove('active');
        }
        if (historyOverlay) {
            historyOverlay.classList.remove('active');
        }
    }
    
    function startNewChat() {
        // 清空当前对话状态
        window.currentConvId = null;
        messagesContainer.innerHTML = '';
        
        // 清理URL参数，避免刷新时跳转
        if (window.location.search.includes('conversation_id')) {
            // 直接导航到干净的聊天页面，让后端重新初始化状态
            window.location.href = '/chat?auto_start_new=true';
            return;
        }
        
        // 首先检查是否有缓存的欢迎消息，避免不必要的API调用
        if (window.welcomeCacheManager) {
            const cachedWelcome = window.welcomeCacheManager.getCachedWelcome();
            if (cachedWelcome) {
                messagesContainer.innerHTML = '';
                const welcomeDiv = addMessage('', 'assistant');
                const wEl = welcomeDiv.querySelector('.message-content');
                const wText = cachedWelcome.content || cachedWelcome;
                if (MAGIC_EFFECT_ENABLED) {
                    // 缓存内容非流式，直接最终呈现，避免“瞬间后又重绘”的感觉
                    renderMarkdown(wEl, wText, true);
                } else {
                    renderMarkdown(wEl, wText, true);
                }
                return;
            }
        }
        
        // 显示全局加载遮罩
        if (loadingOverlay) {
            loadingOverlay.style.display = 'flex';
        }
        
        // 关闭历史对话侧栏 (如果打开)
        closeHistory();
        
    // 准备AI消息占位符用于流式显示（保留loading直至首块到达）
    const aiMessageDiv = addMessage('', 'assistant');
        const contentDiv = aiMessageDiv.querySelector('.message-content');
        
        // 调用后端API创建新对话并获取AI欢迎消息（流式）
        fetch('/api/chat/new', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                datetime: formatUserDateTime(),
                language: getUserLanguage(),
                timezone_offset: getTimezoneOffset()
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('网络错误');
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let accumulatedContent = '';
            let isFirstChunk = true;
            let typer = null;
            let firstChunkArrived = false;
            
            function readStream() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        // 流式传输完成
                        return;
                    }
                    
                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.substring(6));
                                
                                if (data.success && data.conversation_id) {
                                    // 设置新的对话ID
                                    window.currentConvId = data.conversation_id;
                                } else if (data.type === 'chunk') {
                                    // 当收到第一个内容块时隐藏loading遮罩
                                    if (isFirstChunk && loadingOverlay) {
                                        loadingOverlay.style.display = 'none';
                                        isFirstChunk = false;
                                    }
                                    if (MAGIC_EFFECT_ENABLED && !firstChunkArrived) {
                                        contentDiv.innerHTML = '';
                                        typer = new TypingRenderer(contentDiv);
                                        firstChunkArrived = true;
                                    }
                                    accumulatedContent += data.content;
                                    if (MAGIC_EFFECT_ENABLED && typer) {
                                        typer.pushChunk(data.content);
                                    } else {
                                        renderMarkdown(contentDiv, accumulatedContent);
                                        scrollToBottom();
                                    }
                                } else if (data.type === 'complete') {
                                    if (MAGIC_EFFECT_ENABLED && typer) {
                                        try { typer.markCompleted(); } catch (e) { console.warn('typer.markCompleted() 失败:', e); }
                                    } else {
                                        renderMarkdown(contentDiv, accumulatedContent, true);
                                        if (typeof waitForHeightStability === 'function' && messagesContainer) {
                                            waitForHeightStability(messagesContainer, { timeout: 800, idleFrames: 2 })
                                                .then(() => scrollToBottomSettled());
                                        } else {
                                            scrollToBottomSettled();
                                        }
                                    }
                                    
                                    // 保存到缓存，避免下次重复生成
                                    if (window.welcomeCacheManager && accumulatedContent) {
                                        window.welcomeCacheManager.setCachedWelcome(accumulatedContent);
                                    }
                                    // 刷新侧栏标题（若开启）
                                    try {
                                        const sidebarOpen = historySidebar && historySidebar.classList.contains('active');
                                        if (sidebarOpen) { loadChatHistory(); }
                                    } catch (e) {}
                                } else if (data.type === 'error') {
                                    // 隐藏loading遮罩并显示错误
                                    if (loadingOverlay) {
                                        loadingOverlay.style.display = 'none';
                                    }
                                    contentDiv.innerHTML = '<span class="error">抱歉，发生了错误：' + data.message + '</span>';
                                }
                            } catch (e) {
                                console.error('解析响应数据错误:', e);
                            }
                        }
                    }
                    
                    return readStream();
                }).catch(error => {
                    console.error('读取流错误:', error);
                    // 隐藏loading遮罩并显示错误
                    if (loadingOverlay) {
                        loadingOverlay.style.display = 'none';
                    }
                    contentDiv.innerHTML = '<span class="error">网络连接中断，请重试。</span>';
                });
            }
            
            readStream();
        })
        .catch(error => {
            console.error('创建新对话失败:', error);
            // 隐藏loading遮罩并显示兜底欢迎消息
            if (loadingOverlay) {
                loadingOverlay.style.display = 'none';
            }
            // 清空消息容器并显示静态欢迎消息
            messagesContainer.innerHTML = '';
            showWelcomeMessage();
        });
    }
    
    function showWelcomeMessage() {
        const welcomeHTML = `
            <div class="message assistant">
                <div class="message-bubble">
                    <div class="message-content">
                        <p>你好！我是Sovi，你的AI学习伙伴！✨</p>
                        <p>我在这里帮助你：</p>
                        <ul>
                            <li>解答学术问题</li>
                            <li>提供学习指导</li>  
                            <li>给你鼓励和支持</li>
                        </ul>
                        <p>今天有什么我可以帮助你的吗？</p>
                    </div>
                </div>
            </div>
        `;
        messagesContainer.innerHTML = welcomeHTML;
    }
    
    // 底部导航功能
    const navBtns = document.querySelectorAll('.nav-btn');
    navBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const page = this.getAttribute('data-page');
            if (page === 'profile') {
                window.location.href = '/profile';
            } else if (page === 'chat') {
                window.location.href = '/chat';
            }
        });
    });
    
    // 初始化时自动聚焦输入框
    if (messageInput) {
        messageInput.focus();
    }
    
    function initializeChat() {
        // 检查URL参数是否要求自动开始新对话
        const urlParams = new URLSearchParams(window.location.search);
        const autoStartNew = urlParams.get('auto_start_new');
        
        if (autoStartNew === 'true') {
            // 清理URL参数，避免刷新时重复触发
            window.history.replaceState({}, document.title, window.location.pathname);
            
            // 清除可能存在的旧对话状态
            window.currentConvId = null;
            messagesContainer.innerHTML = '';
            
            // 先显示加载状态，提升用户体验
            const loadingDiv = addMessage('正在为您开启新对话...', 'assistant');
            const contentDiv = loadingDiv.querySelector('.message-content');
            contentDiv.classList.add('loading');
            
            // 直接启动新对话，让后端处理欢迎消息逻辑
            setTimeout(() => {
                // 移除加载状态，然后启动新对话
                loadingDiv.remove();
                startNewChat();
            }, 500);
            
            return;
        }
        
        // 检查其他需要显示欢迎消息的场景（容器为空则触发）
        if (!window.currentConvId) {
            const hasAnyMessage = !!messagesContainer.querySelector('.message');
            if (!hasAnyMessage) {
                // 优先使用缓存
                if (window.welcomeCacheManager) {
                    const cachedWelcome = window.welcomeCacheManager.getCachedWelcome();
                    if (cachedWelcome) {
                        messagesContainer.innerHTML = '';
                        const welcomeDiv = addMessage('', 'assistant');
                        const wEl = welcomeDiv.querySelector('.message-content');
                        const wText = cachedWelcome.content || cachedWelcome;
                        // 直接渲染，保持与其他消息一致
                        renderMarkdown(wEl, wText, true);
                        return;
                    }
                }
                // 无缓存则动态生成
                startNewChat();
            }
        }
    }
    
    // 初始化时间格式化
    function initializeTimeFormatting() {
        if (typeof TimeFormatter === 'undefined') {
            console.warn('TimeFormatter未加载，跳过时间格式化');
            return;
        }
        
        // 格式化历史对话中的时间显示
        document.querySelectorAll('.history-time[data-utc-time]').forEach(function(timeElement) {
            const utcTime = timeElement.getAttribute('data-utc-time');
            if (utcTime) {
                const formattedTime = TimeFormatter.getRelativeTime(utcTime);
                timeElement.textContent = formattedTime;
                // 添加title属性显示完整时间
                timeElement.title = TimeFormatter.formatToLocal(utcTime);
            }
        });
        
        // 格式化消息中的时间显示
        document.querySelectorAll('.message-time[data-utc-time]').forEach(function(timeElement) {
            const utcTime = timeElement.getAttribute('data-utc-time');
            if (utcTime) {
                const formattedTime = TimeFormatter.formatChatTime(utcTime);
                timeElement.textContent = formattedTime;
                // 添加title属性显示完整时间
                timeElement.title = TimeFormatter.formatToLocal(utcTime);
            }
        });
    }
    
    // 不活跃检测功能
    function initializeInactivityDetection() {
        const INACTIVITY_THRESHOLD = 30 * 60 * 1000; // 30分钟不活跃阈值
        const LAST_ACTIVITY_KEY = 'sovi_last_activity';
        
        // 检查上次活跃时间
        function checkLastActivity() {
            const lastActivity = localStorage.getItem(LAST_ACTIVITY_KEY);
            if (lastActivity) {
                const timeSinceLastActivity = Date.now() - parseInt(lastActivity);
                
                if (timeSinceLastActivity > INACTIVITY_THRESHOLD) {
                    // 清除旧的对话状态
                    window.currentConvId = null;
                    localStorage.removeItem('current_conversation_id');
                    
                    // 标记需要新对话（但不立即执行，等用户交互时）
                    sessionStorage.setItem('need_new_conversation', 'true');
                }
            }
        }
        
        // 更新最后活跃时间
        function updateLastActivity() {
            localStorage.setItem(LAST_ACTIVITY_KEY, Date.now().toString());
        }
        
        // 检查是否需要新对话（在用户开始交互时）
        function checkAndStartNewConversationIfNeeded() {
            if (sessionStorage.getItem('need_new_conversation') === 'true') {
                sessionStorage.removeItem('need_new_conversation');
                
                // 清空当前消息并开始新对话
                messagesContainer.innerHTML = '';
                startNewChat();
            }
        }
        
        // 页面加载时检查上次活跃时间
        checkLastActivity();
        
        // 监听用户活跃事件
        const activityEvents = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'];
        activityEvents.forEach(event => {
            document.addEventListener(event, updateLastActivity, { passive: true });
        });
        
        // 监听用户开始输入或发送消息
        if (messageInput) {
            messageInput.addEventListener('focus', checkAndStartNewConversationIfNeeded);
            messageInput.addEventListener('input', () => {
                checkAndStartNewConversationIfNeeded();
                updateLastActivity();
            });
        }
        
        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                checkAndStartNewConversationIfNeeded();
                updateLastActivity();
            });
        }
        
        // 页面隐藏/显示时的处理
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                // 页面重新可见时检查是否需要新对话
                checkLastActivity();
            } else {
                // 页面隐藏时更新最后活跃时间
                updateLastActivity();
            }
        });
        
        // 页面卸载时保存最后活跃时间
        window.addEventListener('beforeunload', updateLastActivity);
    }
    
    // 图片模态框显示
    function showImageModal(imgElement) {
        // 创建模态框
        const modal = document.createElement('div');
        modal.className = 'image-modal';
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            cursor: pointer;
        `;
        
        const img = document.createElement('img');
        img.src = imgElement.src;
        img.style.cssText = `
            max-width: 90vw;
            max-height: 90vh;
            border-radius: 8px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        `;
        
        modal.appendChild(img);
        document.body.appendChild(modal);
        
        // 点击关闭
        modal.addEventListener('click', () => {
            modal.remove();
        });
        
        // ESC键关闭
        function handleKeydown(e) {
            if (e.key === 'Escape') {
                modal.remove();
                document.removeEventListener('keydown', handleKeydown);
            }
        }
        document.addEventListener('keydown', handleKeydown);
    }
    
    // 处理页面加载时已存在的历史消息的LaTeX渲染
    function processExistingMessages() {
        // 等待KaTeX库加载完成
        setTimeout(() => {
            // 找到所有已存在的消息内容区域
            const messageContents = messagesContainer.querySelectorAll('.message-content');
            
            messageContents.forEach((contentDiv, index) => {
                // 获取原始内容（从data属性中）
                const originalContent = contentDiv.getAttribute('data-original-content');
                
                if (originalContent && originalContent.trim()) {
                    // 修复：检查内容是否已被服务端格式化（包含<br>标签）
                    const currentHTML = contentDiv.innerHTML;
                    const hasServerFormatting = currentHTML.includes('<br>') || currentHTML.includes('<p>') || currentHTML.includes('<div>');
                    
                    if (hasServerFormatting) {
                        // 检查原始内容是否包含未处理的markdown语法
                        const hasUnprocessedMarkdown = originalContent.includes('`') || 
                                                     originalContent.includes('**') || 
                                                     originalContent.includes('*') ||
                                                     originalContent.includes('[') ||
                                                     originalContent.includes('$$') ||
                                                     originalContent.includes('$');
                        
                        if (hasUnprocessedMarkdown) {
                            // 有未处理的markdown，进行完整渲染
                            renderMarkdown(contentDiv, originalContent, true);
                        } else {
                            // 只进行LaTeX渲染，避免双重处理
                            if (typeof window.renderMathInElementSafe === 'function') {
                                window.renderMathInElementSafe(contentDiv);
                            }
                        }
                    } else {
                        // 原始markdown内容，进行完整渲染
                        renderMarkdown(contentDiv, originalContent, true);
                    }
                } else {
                    // 如果没有原始内容属性，只进行LaTeX渲染
                    if (typeof window.renderMathInElementSafe === 'function') {
                        window.renderMathInElementSafe(contentDiv);
                    }
                }
            });
            
        }, 1000); // 给KaTeX库足够时间加载
    }
    
    // 暴露全局函数
    window.showImageModal = showImageModal;
    
    // 图片加载错误处理
    window.handleImageError = function(imgElement) {
        console.warn('图片加载失败:', imgElement.src);
        
        // 尝试重新加载一次
        const originalSrc = imgElement.dataset.originalSrc || imgElement.src;
        if (imgElement.src === originalSrc) {
            // 第一次失败，显示错误提示
            imgElement.style.display = 'none';
            
            // 创建错误提示元素
            const errorDiv = document.createElement('div');
            errorDiv.className = 'image-error';
            errorDiv.innerHTML = `
                <div class="error-icon">🖼️</div>
                <div class="error-text">图片加载失败</div>
                <button class="retry-btn" onclick="retryImageLoad(this)">重试</button>
            `;
            errorDiv.dataset.originalSrc = originalSrc;
            
            // 替换图片元素
            imgElement.parentNode.insertBefore(errorDiv, imgElement);
        }
    };
    
    // 重试图片加载
    window.retryImageLoad = function(button) {
        const errorDiv = button.parentNode.parentNode;
        const originalSrc = errorDiv.dataset.originalSrc;
        
        if (originalSrc) {
            // 创建新的图片元素
            const newImg = document.createElement('img');
            newImg.src = originalSrc;
            newImg.alt = '用户上传的图片';
            newImg.onclick = function() { showImageModal(this); };
            newImg.onerror = function() { handleImageError(this); };
            newImg.loading = 'lazy';
            newImg.dataset.originalSrc = originalSrc;
            
            // 替换错误提示
            errorDiv.parentNode.insertBefore(newImg, errorDiv);
            errorDiv.remove();
        }
    };

    // 字符限制功能
    function initializeCharacterLimit() {
        const messageInput = document.getElementById('message-input');
        const charCount = document.getElementById('char-count');
        const maxLength = 800;
        
        function updateCharacterCount() {
            const currentLength = messageInput.value.length;
            charCount.textContent = `${currentLength}/${maxLength}`;
            
            // 移除所有状态类
            messageInput.classList.remove('warning', 'danger');
            charCount.classList.remove('warning', 'danger');
            
            if (currentLength >= maxLength) {
                // 达到上限 - 红色
                messageInput.classList.add('danger');
                charCount.classList.add('danger');
            } else if (currentLength >= 700) {
                // 接近上限 - 黄色警告
                if (currentLength >= 780) {
                    messageInput.classList.add('danger');
                    charCount.classList.add('danger');
                } else {
                    messageInput.classList.add('warning');
                    charCount.classList.add('warning');
                }
            }
        }
        
        function enforceLimit() {
            if (messageInput.value.length > maxLength) {
                messageInput.value = messageInput.value.substring(0, maxLength);
                updateCharacterCount();
            }
        }
        
        // 监听输入事件
        messageInput.addEventListener('input', function() {
            enforceLimit();
            updateCharacterCount();
            
            // 保持原有的高度调整功能
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            sendBtn.disabled = !this.value.trim() && !selectedImage;
        });
        
        // 监听粘贴事件
        messageInput.addEventListener('paste', function(e) {
            // 让粘贴先执行，然后在下一个事件循环中检查长度
            setTimeout(() => {
                enforceLimit();
                updateCharacterCount();
            }, 0);
        });
        
        // 初始化显示
        updateCharacterCount();
    }

});
