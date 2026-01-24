# 贡献指南

感谢你对 Sovi 项目的关注！我们欢迎各种形式的贡献。

## 如何贡献

### 报告问题

如果你发现了 bug 或有功能建议，请通过 [GitHub Issues](https://github.com/MidnightV1/sovi-demo/issues) 提交。

提交 Issue 时请包含：
- 问题的详细描述
- 复现步骤（如果是 bug）
- 预期行为与实际行为
- 运行环境（Python 版本、操作系统等）

### 提交代码

1. **Fork 仓库**
   ```bash
   git clone https://github.com/MidnightV1/sovi-demo.git
   cd sovi-demo
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```

3. **安装开发环境**
   ```bash
   pip install -r requirements.txt
   cp .env.example .env
   # 编辑 .env 填入你的 GEMINI_API_KEY
   ```

4. **进行修改并测试**
   ```bash
   # 运行测试
   pytest tests/ -v

   # 启动本地服务验证
   python app.py
   ```

5. **提交代码**
   ```bash
   git add .
   git commit -m "feat: 添加新功能描述"
   # 或
   git commit -m "fix: 修复问题描述"
   ```

6. **推送并创建 Pull Request**
   ```bash
   git push origin feature/your-feature-name
   ```

## 代码规范

### 提交信息格式

使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 文档更新
- `style:` 代码格式（不影响功能）
- `refactor:` 重构
- `test:` 测试相关
- `chore:` 构建/工具相关

### Python 代码风格

- 遵循 PEP 8 规范
- 使用 4 空格缩进
- 函数和类添加 docstring
- 类型注解（推荐）

### 目录结构

```
sovi-demo/
├── api_clients/      # API 客户端层
├── business_logic/   # 业务逻辑层
├── infrastructure/   # 基础设施层
├── core/             # 核心服务
├── prompts/          # 系统提示词
├── static/           # 前端静态资源
├── templates/        # HTML 模板
├── tests/            # 测试文件
└── docs/             # 文档
```

## 开发重点

### 欢迎的贡献类型

- Bug 修复
- 文档改进
- 测试用例补充
- 性能优化
- 新功能（请先开 Issue 讨论）

### 核心文件说明

| 文件 | 说明 | 修改注意 |
|:---|:---|:---|
| `prompts/system_prompts.py` | 系统提示词 | 核心资产，修改需谨慎测试 |
| `business_logic/chat_orchestrator.py` | 对话编排 | 流式响应核心逻辑 |
| `business_logic/response_parser.py` | 响应解析 | XML 解析逻辑 |
| `api_clients/gemini_client.py` | API 客户端 | Gemini API 交互 |

## 联系方式

- Email: john.william.sun@gmail.com
- GitHub Issues: [提交问题](https://github.com/MidnightV1/sovi-demo/issues)

## 许可证

贡献的代码将采用与项目相同的 [Apache License 2.0](LICENSE) 许可证。
