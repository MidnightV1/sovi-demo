/**
 * 时间处理工具函数
 * 提供UTC时间到本地时间的转换和格式化功能
 */

class TimeFormatter {
    /**
     * 将UTC时间字符串转换为本地时间并格式化
     * @param {string} utcTimeString - UTC时间字符串 (ISO格式)
     * @param {Object} options - 格式化选项
     * @returns {string} 格式化后的本地时间字符串
     */
    static formatToLocal(utcTimeString, options = {}) {
        if (!utcTimeString) {
            return '时间未知';
        }
        
        try {
            // 处理不同格式的时间字符串
            let utcDate;
            
            // 检查是否为GMT格式 (例如: "Sun, 17 Aug 2025 11:43:34 GMT")
            if (utcTimeString.includes('GMT') || utcTimeString.match(/\w{3}, \d{1,2} \w{3} \d{4}/)) {
                // 直接使用Date构造函数解析GMT格式
                utcDate = new Date(utcTimeString);
            } else {
                // 处理ISO格式的时间字符串
                let isoString = utcTimeString;
                if (utcTimeString.endsWith('Z')) {
                    // 已经是UTC格式
                    isoString = utcTimeString;
                } else if (!utcTimeString.includes('+') && !utcTimeString.includes('Z')) {
                    // 没有时区信息，添加Z表示UTC
                    isoString = utcTimeString + 'Z';
                }
                utcDate = new Date(isoString);
            }
            
            // 检查日期是否有效
            if (isNaN(utcDate.getTime())) {
                console.warn('无效的时间字符串:', utcTimeString);
                return '时间格式错误';
            }
            
            // 默认格式化选项
            const defaultOptions = {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            };
            
            const formatOptions = { ...defaultOptions, ...options };
            
            // 转换为本地时间并格式化
            return utcDate.toLocaleString('zh-CN', formatOptions);
        } catch (error) {
            console.error('时间格式化错误:', error, utcTimeString);
            return '时间解析失败';
        }
    }
    
    /**
     * 获取相对时间描述（如："2分钟前"、"昨天"等）
     * @param {string} utcTimeString - UTC时间字符串
     * @returns {string} 相对时间描述
     */
    static getRelativeTime(utcTimeString) {
        if (!utcTimeString) {
            return '时间未知';
        }
        
        try {
            let isoString = utcTimeString;
            if (utcTimeString.endsWith('Z')) {
                isoString = utcTimeString;
            } else if (!utcTimeString.includes('+') && !utcTimeString.includes('Z')) {
                isoString = utcTimeString + 'Z';
            }
            
            const utcDate = new Date(isoString);
            const now = new Date();
            const diffMs = now.getTime() - utcDate.getTime();
            const diffSeconds = Math.floor(diffMs / 1000);
            const diffMinutes = Math.floor(diffSeconds / 60);
            const diffHours = Math.floor(diffMinutes / 60);
            const diffDays = Math.floor(diffHours / 24);
            
            if (diffSeconds < 60) {
                return '刚刚';
            } else if (diffMinutes < 60) {
                return `${diffMinutes}分钟前`;
            } else if (diffHours < 24) {
                return `${diffHours}小时前`;
            } else if (diffDays === 1) {
                return '昨天';
            } else if (diffDays < 7) {
                return `${diffDays}天前`;
            } else {
                return TimeFormatter.formatToLocal(utcTimeString, {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit'
                });
            }
        } catch (error) {
            console.error('相对时间计算错误:', error, utcTimeString);
            return '时间解析失败';
        }
    }
    
    /**
     * 格式化聊天消息时间（简短格式）
     * @param {string} utcTimeString - UTC时间字符串
     * @returns {string} 简短的时间格式
     */
    static formatChatTime(utcTimeString) {
        if (!utcTimeString) {
            return '';
        }
        
        try {
            let isoString = utcTimeString;
            if (utcTimeString.endsWith('Z')) {
                isoString = utcTimeString;
            } else if (!utcTimeString.includes('+') && !utcTimeString.includes('Z')) {
                isoString = utcTimeString + 'Z';
            }
            
            const utcDate = new Date(isoString);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const messageDate = new Date(utcDate.getFullYear(), utcDate.getMonth(), utcDate.getDate());
            
            if (messageDate.getTime() === today.getTime()) {
                // 今天的消息，只显示时间
                return utcDate.toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false
                });
            } else {
                // 其他日期的消息，显示月-日 时:分
                return utcDate.toLocaleString('zh-CN', {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false
                });
            }
        } catch (error) {
            console.error('聊天时间格式化错误:', error, utcTimeString);
            return '';
        }
    }
    
    /**
     * 格式化对话历史时间
     * @param {string} utcTimeString - UTC时间字符串
     * @returns {string} 对话历史显示格式
     */
    static formatHistoryTime(utcTimeString) {
        const relativeTime = TimeFormatter.getRelativeTime(utcTimeString);
        const fullTime = TimeFormatter.formatToLocal(utcTimeString, {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        });
        
        return {
            relative: relativeTime,
            full: fullTime
        };
    }
}

// 导出为全局变量（兼容性）
window.TimeFormatter = TimeFormatter;
