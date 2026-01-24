// 登录页面 JavaScript - 简化版（合并登录注册）
document.addEventListener('DOMContentLoaded', function() {
    
    // 消息提示功能
    const messageDiv = document.getElementById('message');
    
    function showMessage(text, type = 'success') {
        messageDiv.textContent = text;
        messageDiv.className = `message ${type}`;
        messageDiv.style.display = 'block';
        
        // 5秒后自动隐藏
        setTimeout(() => {
            messageDiv.style.display = 'none';
        }, 5000);
    }
    
    // 统一表单处理（自动登录或注册）
    const authForm = document.getElementById('auth-form');
    authForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const formData = new FormData(authForm);
        const data = {
            username: formData.get('username'),
            password: formData.get('password')
        };
        
        // 基本验证
        if (!data.username || data.username.length < 3) {
            showMessage('用户名至少需要3个字符', 'error');
            return;
        }
        
        if (!data.password || data.password.length < 6) {
            showMessage('密码至少需要6个字符', 'error');
            return;
        }
        
        // 禁用提交按钮
        const submitBtn = authForm.querySelector('button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = '正在验证...';
        
        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (result.success) {
                showMessage(result.message, 'success');
                
                // 如果登录成功且需要开始新对话，直接跳转让前端统一处理
                if (result.start_new_conversation) {
                    submitBtn.textContent = '准备对话中...';
                    
                    // 短暂延迟后跳转，让用户看到成功消息
                    setTimeout(() => {
                        window.location.href = result.redirect_url + '?auto_start_new=true';
                    }, 800);
                } else {
                    // 普通跳转（备用方案）
                    setTimeout(() => {
                        window.location.href = result.redirect_url;
                    }, 1500);
                }
            } else {
                showMessage(result.message, 'error');
            }
            
        } catch (error) {
            console.error('请求错误:', error);
            showMessage('网络错误，请检查连接后重试', 'error');
        } finally {
            // 恢复提交按钮
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    });
    
    // Enter 键快捷提交
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.matches('input')) {
            authForm.dispatchEvent(new Event('submit'));
        }
    });
    
    // 页面加载后自动聚焦到用户名输入框
    document.getElementById('auth-username').focus();
    
});
