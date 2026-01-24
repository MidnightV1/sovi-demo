# Sovi Demo 架构设计文档

本文档详细说明 Sovi Demo 的系统架构、模块设计和核心技术决策。

---

## 目录

1. [系统架构概览](#系统架构概览)
2. [分层架构设计](#分层架构设计)
3. [核心模块详解](#核心模块详解)
4. [数据流设计](#数据流设计)
5. [数据库设计](#数据库设计)
6. [设计模式应用](#设计模式应用)

---

## 系统架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端界面层                                │
│              HTML/CSS + Vanilla JavaScript                       │
│         (SSE客户端、图片处理、实时渲染、跟随追问)                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTP / SSE
┌─────────────────────────┴───────────────────────────────────────┐
│                     Flask 应用层 (app.py)                        │
│              路由、会话管理、文件上传、流式响应                   │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
┌─────────┴─────────┐ ┌───┴───────┐ ┌─────┴─────────────────┐
│   业务逻辑层       │ │ 核心服务   │ │    基础设施层          │
│ business_logic/   │ │  core/    │ │   infrastructure/      │
│ • ChatOrchestrator│ │ • Service │ │ • DatabaseManager      │
│ • ResponseParser  │ │   Container│ │ • CacheManager         │
│ • WelcomeService  │ │ • 依赖注入 │ │ • StorageManager       │
└─────────┬─────────┘ └───────────┘ └───────────────────────┘
          │
┌─────────┴─────────────────────────────────────────────────────┐
│                    API 客户端层 (api_clients/)                 │
│     GeminiClient • MessageBuilder • GoogleTransport           │
└─────────┬─────────────────────────────────────────────────────┘
          │ HTTPS
┌─────────┴─────────────────────────────────────────────────────┐
│                   Google Gemini API                            │
└───────────────────────────────────────────────────────────────┘
```

---

## 分层架构设计

### 1. 应用层 (`app.py`)

**职责**：
- HTTP 路由处理
- 请求验证和响应格式化
- 会话管理
- SSE 流式响应推送

**关键端点**：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/chat/send` | POST | 发送消息（流式） |
| `/api/chat/new` | POST | 创建新对话 |
| `/api/ask-follow-up` | POST | 划词追问 |
| `/api/conversations` | GET | 获取对话列表 |
| `/api/upload-image` | POST | 上传图片 |

### 2. 业务逻辑层 (`business_logic/`)

**模块说明**：

| 模块 | 文件 | 职责 |
|------|------|------|
| **ChatOrchestrator** | `chat_orchestrator.py` | 对话编排核心，管理完整的消息生命周期 |
| **ResponseParser** | `response_parser.py` | 解析 Gemini 返回的 XML 结构化响应 |
| **WelcomeService** | `welcome_service.py` | 生成欢迎消息 |
| **MessageStatusService** | `message_status_service.py` | 消息状态管理（pending/success/failed） |
| **SessionMetaService** | `session_meta_service.py` | 对话元数据管理（标题、摘要） |
| **ProfileService** | `profile_service.py` | 用户画像提取和管理 |
| **TransactionManager** | `transaction_manager.py` | 短事务管理 |

### 3. API 客户端层 (`api_clients/`)

**模块说明**：

| 模块 | 文件 | 职责 |
|------|------|------|
| **GeminiClient** | `gemini_client.py` | Gemini API 高层封装 |
| **MessageBuilder** | `message_builder.py` | 消息格式构造 |
| **GoogleTransport** | `google_transport.py` | 底层 HTTP 传输 |
| **ResponseTypes** | `response_types.py` | 响应数据类型定义 |
| **Exceptions** | `exceptions.py` | API 异常定义 |

### 4. 核心服务层 (`core/`)

**ServiceContainer** (`service_container.py`)：

```python
# 依赖注入容器示例
container = ServiceContainer()
container.register_singleton('parser', ResponseParser())
container.register_factory('orchestrator', lambda: ChatOrchestrator(...))

# 获取服务
parser = container.get('parser')
```

### 5. 基础设施层 (`infrastructure/`)

| 模块 | 文件 | 职责 |
|------|------|------|
| **DatabaseManager** | `db/db.py` | SQLite 数据库管理 |
| **PostgresManager** | `db/db_postgre.py` | PostgreSQL 数据库管理 |
| **CacheManager** | `cache_manager.py` | Gemini API 缓存管理 |
| **StorageManager** | `storage_manager.py` | 图片存储（本地/GCS） |

### 6. 系统提示层 (`prompts/`)

**SystemPrompts** (`system_prompts.py`)：

- 核心系统提示词管理
- 三模式行为定义（Mode1/Mode2/Mode3）
- 输出格式约束（XML 结构）

---

## 核心模块详解

### ChatOrchestrator（对话编排器）

对话编排器是系统核心，负责协调整个消息处理流程：

```
用户消息 → 入库(pending) → 构造请求 → API调用 → 流式响应 → 解析XML → 短事务提交 → 标记完成
```

**关键特性**：

1. **状态机管理**：消息状态从 `pending` → `success`/`failed`
2. **流式转发**：实时提取 `<Sovi_Response_Msg>` 内容推送给前端
3. **短事务**：避免长事务锁，流完成后集中提交
4. **容错机制**：失败时保留消息状态，支持重试

### ResponseParser（响应解析器）

解析 Gemini 返回的 XML 格式响应：

```xml
<Sovi_Response>
    <Action_Mode>Mode1</Action_Mode>
    <Is_Valid_Question>true</Is_Valid_Question>
    <Sovi_Explanation>解题过程...</Sovi_Explanation>
    <Sovi_Response_Msg>用户看到的答案</Sovi_Response_Msg>
    <Session_Meta>
        <Title>对话标题</Title>
        <Summary>对话摘要</Summary>
    </Session_Meta>
    <Question_Meta>
        <Subject>数学</Subject>
        <Complexity>中等</Complexity>
        <Concepts>导数,极限</Concepts>
    </Question_Meta>
</Sovi_Response>
```

**三重内容存储策略**：

| 字段 | 用途 | 内容 |
|------|------|------|
| `origin_content` | 审计/调试 | 完整 XML 响应 |
| `view_content` | 用户界面 | 清理后的显示内容 |
| `working_content` | 历史上下文 | 包含解题过程的内容 |

### MessageBuilder（消息构造器）

构造发送给 Gemini API 的消息格式：

```python
# 消息结构
{
    "role": "user",
    "content": "用户问题",
    "meta": {
        "blocks": {
            "datetime": "# User's Current Date and Time\n2025-01-24 10:00\n\n",
            "profile": "# What You Know About the User\n高三学生，数学薄弱\n\n",
            "user_refer": "<|user_refer_begin|>选中的文本<|user_refer_end|>\n\n"
        },
        "is_new_conversation": False
    }
}
```

---

## 数据流设计

### 消息发送完整流程

```
1. 用户输入
   ├─ 前端验证
   └─ 图片压缩（如有）

2. POST /api/chat/send
   ├─ 验证用户登录
   ├─ 检查/创建对话
   └─ 入库用户消息 (status=pending)

3. ChatOrchestrator.orchestrate()
   ├─ 加载用户画像
   ├─ 获取对话历史（排除当前消息）
   └─ 构造 Gemini 请求

4. GeminiClient.chat_with_streaming()
   ├─ 系统提示（可能使用缓存）
   ├─ 历史消息（使用 working_content）
   └─ 当前消息 + 图片

5. 流式处理
   ├─ 接收 chunks
   ├─ 提取 <Sovi_Response_Msg> 内容
   └─ SSE 推送给前端

6. 流完成
   ├─ 解析完整 XML
   ├─ 提取元数据
   └─ 短事务提交（AI消息、元数据、标题）

7. 标记用户消息 status=success
```

### SSE 事件格式

```javascript
// 内容块
data: {"type": "chunk", "content": "..."}

// 完成信号
data: {"type": "complete", "conversation_id": 123}

// 错误
data: {"type": "error", "message": "..."}

// 心跳（防止超时）
: heartbeat
```

---

## 数据库设计

### 核心表结构

#### conversations（对话表）

```sql
CREATE TABLE conversations (
    conversation_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title VARCHAR(500) DEFAULT '新对话',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

#### messages（消息表）

```sql
CREATE TABLE messages (
    message_id INTEGER PRIMARY KEY,
    conversation_id INTEGER,
    user_id INTEGER,
    role VARCHAR(20),           -- 'user' | 'assistant' | 'server'
    round_num INTEGER,          -- 轮次（-1=欢迎消息）

    -- 三重内容存储
    origin_content TEXT,        -- 原始内容
    view_content TEXT,          -- 显示内容
    working_content TEXT,       -- 工作内容

    -- 元数据
    action_mode VARCHAR(10),    -- Mode1/Mode2/Mode3
    is_valid_question BOOLEAN,
    image_url TEXT,
    send_status VARCHAR(20),    -- pending/success/failed

    created_at TIMESTAMP
);
```

#### api_requests（API 请求日志）

```sql
CREATE TABLE api_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER,
    conversation_id INTEGER,

    request_data TEXT,          -- JSON: 请求内容
    response_meta TEXT,         -- JSON: 响应元数据

    total_cost_usd DECIMAL(10,6),
    total_cost_cny DECIMAL(10,6),
    request_duration_ms INTEGER,

    model_name VARCHAR(50),
    created_at TIMESTAMP
);
```

#### system_cache_status（系统缓存状态）

```sql
CREATE TABLE system_cache_status (
    id INTEGER PRIMARY KEY,
    model_name VARCHAR(50),
    api_cache_name VARCHAR(255),
    expires_at TIMESTAMP,
    usage_count INTEGER,
    content_hash VARCHAR(64)
);
```

---

## 设计模式应用

### 1. 依赖注入（Dependency Injection）

`ServiceContainer` 实现松耦合的服务管理：

```python
# 注册
container.register_singleton('db', DatabaseManager())
container.register_factory('client', lambda: GeminiClient(transport))

# 使用
db = container.get('db')
```

**优点**：
- 便于单元测试（可注入 Mock）
- 服务生命周期统一管理
- 降低模块耦合度

### 2. 工厂模式（Factory Pattern）

延迟初始化和动态创建服务：

```python
container.register_factory('orchestrator',
    lambda: ChatOrchestrator(
        gemini_client=container.get('client'),
        parser=container.get('parser')
    )
)
```

### 3. 单例模式（Singleton Pattern）

全局唯一实例管理：

```python
# DatabaseManager、AuthManager 等使用单例
container.register_singleton('db', DatabaseManager())
```

### 4. 策略模式（Strategy Pattern）

响应解析器支持不同的解析策略：

```python
# Mode1 特殊策略：working_content 包含解释
if action_mode == 'Mode1' and has_explanation:
    working_content = f"### Sovi_Explanation\n{explanation}\n### Sovi_Response_Msg\n{display}"
```

### 5. 观察者模式（Observer Pattern）

SSE 流式事件推送：

```python
def generate_stream():
    for chunk in api_response:
        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
```

---

## 扩展性设计

### 添加新的 AI 模型

1. 实现新的 Transport 类
2. 注册到 ServiceContainer
3. 更新配置支持模型切换

### 添加新的存储后端

1. 实现 `StorageManager` 接口
2. 添加配置项
3. 注册到 ServiceContainer

### 添加新的业务逻辑

1. 在 `business_logic/` 创建新服务
2. 注册到 ServiceContainer
3. 在 ChatOrchestrator 中调用
