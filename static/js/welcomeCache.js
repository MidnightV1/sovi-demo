/**
 * 时间窗口欢迎消息缓存管理
 * 用于控制新对话创建的成本，每30分钟窗口内复用欢迎消息
 */

class WelcomeCacheManager {
    constructor() {
        this.CACHE_KEY_PREFIX = 'sovi_welcome_cache';
        this.WINDOW_DURATION = 30 * 60 * 1000; // 30分钟
    }

    /**
     * 获取当前用户的缓存Key
     * @returns {string} 用户特定的缓存key
     */
    getUserCacheKey() {
        const userId = window.userId;
        if (!userId) {
            return `${this.CACHE_KEY_PREFIX}_default`;
        }
        return `${this.CACHE_KEY_PREFIX}_user_${userId}`;
    }

    /**
     * 获取当前时间窗口ID（整点和整半小时对齐）
     * @returns {number} 时间窗口ID
     */
    getTimeWindow() {
        const now = new Date();
        const year = now.getFullYear();
        const month = now.getMonth();
        const date = now.getDate();
        const hour = now.getHours();
        const minute = now.getMinutes();
        
        // 计算当前是否在上半小时（0-29分钟）还是下半小时（30-59分钟）
        const alignedMinute = minute < 30 ? 0 : 30;
        
        // 创建对齐后的时间点
        const alignedTime = new Date(year, month, date, hour, alignedMinute, 0, 0);
        
        return alignedTime.getTime();
    }

    /**
     * 检查是否需要重新生成欢迎消息
     * @returns {boolean} true表示需要重新生成
     */
    shouldRegenerateWelcome() {
        const cached = this.getCachedWelcome();
        if (!cached) {
            return true;
        }
        
        const currentWindow = this.getTimeWindow();
        return cached.windowId !== currentWindow;
    }

    /**
     * 获取缓存的欢迎消息
     * @returns {Object|null} 缓存的消息对象或null
     */
    getCachedWelcome() {
        try {
            const cached = localStorage.getItem(this.getUserCacheKey());
            if (!cached) return null;
            
            const data = JSON.parse(cached);
            const currentWindow = this.getTimeWindow();
            
            // 检查是否还在同一时间窗口
            if (data.windowId === currentWindow) {
                return data;
            }
            
            // 过期，清除缓存
            this.clearCache();
            return null;
        } catch (error) {
            console.error('读取欢迎消息缓存失败:', error);
            this.clearCache();
            return null;
        }
    }

    /**
     * 缓存欢迎消息
     * @param {string} content 欢迎消息内容
     * @param {Object} metadata 元数据信息
     */
    setCachedWelcome(content, metadata = {}) {
        try {
            const data = {
                content: content,
                metadata: metadata,
                windowId: this.getTimeWindow(),
                timestamp: Date.now(),
                userId: window.userId, // 存储用户ID用于调试
                userAgent: navigator.userAgent.substring(0, 100) // 简短的用户代理信息
            };
            localStorage.setItem(this.getUserCacheKey(), JSON.stringify(data));
        } catch (error) {
            console.error('缓存欢迎消息失败:', error);
        }
    }

    /**
     * 清除缓存
     */
    clearCache() {
        localStorage.removeItem(this.getUserCacheKey());
    }

    /**
     * 获取缓存状态信息（用于调试）
     * @returns {Object} 缓存状态信息
     */
    getCacheStatus() {
        const cached = localStorage.getItem(this.getUserCacheKey());
        if (!cached) {
            return {
                hasCached: false,
                currentWindow: this.getTimeWindow(),
                nextWindowTime: this.getTimeWindow() + this.WINDOW_DURATION
            };
        }

        try {
            const data = JSON.parse(cached);
            const currentWindow = this.getTimeWindow();
            const isValid = data.windowId === currentWindow;
            
            return {
                hasCached: true,
                isValid: isValid,
                cachedWindow: data.windowId,
                currentWindow: currentWindow,
                cachedTime: new Date(data.timestamp).toLocaleString(),
                nextWindowTime: currentWindow + this.WINDOW_DURATION,
                timeUntilNextWindow: (currentWindow + this.WINDOW_DURATION) - Date.now()
            };
        } catch (error) {
            return {
                hasCached: true,
                isValid: false,
                error: error.message
            };
        }
    }

    /**
     * 格式化时间窗口为可读格式
     * @param {number} windowId 时间窗口ID
     * @returns {string} 格式化的时间字符串
     */
    formatWindow(windowId) {
        const date = new Date(windowId);
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${hours}:${minutes}`;
    }
}

// 全局实例
window.welcomeCacheManager = new WelcomeCacheManager();
