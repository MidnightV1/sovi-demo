// 个人中心页面 JavaScript
document.addEventListener('DOMContentLoaded', function() {
    
    // 底部导航
    const navButtons = document.querySelectorAll('.nav-btn');
    navButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const page = this.dataset.page;
            
            if (page === 'chat') {
                // 跳转到聊天页面，并开始新对话
                window.location.href = '/chat?auto_start_new=true';
                return;
            }
            
            if (page === 'profile') {
                // 当前已在个人中心页面，无需跳转
                return;
            }
            
            // 更新导航状态
            navButtons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
        });
    });
    
    // 退出登录
    document.getElementById('logout-btn').addEventListener('click', function() {
        if (confirm('确定要退出登录吗？')) {
            window.location.href = '/logout';
        }
    });
    
});
