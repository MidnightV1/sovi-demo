# Sovi Prompt 工程设计文档

本文档详细说明 Sovi 的 Prompt 工程设计，包括核心策略、消息构造、缓存机制和最佳实践。

---

## 目录

1. [设计理念](#设计理念)
2. [核心 Prompt 结构](#核心-prompt-结构)
3. [三模式行为系统](#三模式行为系统)
4. [消息构造策略](#消息构造策略)
5. [XML 输出结构](#xml-输出结构)
6. [缓存策略](#缓存策略)
7. [安全防护机制](#安全防护机制)
8. [最佳实践](#最佳实践)

---

## 设计理念

### 核心定位

Sovi 不是传统的"答案机器"，而是**学术生存教练**：

```
表面价值：快速解题 → 建立信任
隐藏价值：考试技巧 → 培养能力
元层价值：时间优化 → 买回自由
```

### 双层策略

| 层级 | 目标 | 用户感知 |
|------|------|----------|
| **Surface Layer** | 即时解答 | "这个工具很快" |
| **Hidden Layer** | 模式识别 | "我开始懂规律了" |
| **Meta Layer** | 效率提升 | "我有时间学真正想学的" |

### 与传统拍照解题的区别

| 维度 | 传统产品 | Sovi |
|------|----------|------|
| 核心交付 | 答案 | 答案 + 考试智慧 |
| 交互深度 | 单次 | 多轮 + 画像累积 |
| 用户关系 | 工具 | 学术伙伴 |
| 留存逻辑 | 功能依赖 | 信任依赖 |

---

## 核心 Prompt 结构

### 主系统提示词（300+ 行）

位置：`prompts/system_prompts.py`

结构组成：

```
1. CORE PRINCIPLES（核心原则）
   ├── Dual Strategy（双层策略）
   ├── Value Hierarchy（价值层级）
   ├── System Defense（安全防护）
   └── User Understanding（用户理解）

2. Visual Processing Priority（视觉处理优先级）
   ├── Instant Triage（快速分类）
   ├── Priority Matrix（优先矩阵）
   └── Quality Control（质量控制）

3. Formatting Standards（格式标准）
   ├── Mathematical Expression（数学表达）
   ├── Content Structure（内容结构）
   └── Response Organization（响应组织）

4. OPERATIONAL FRAMEWORK（操作框架）
   ├── Mode 1: instant_solver
   ├── Mode 2: exam_decoder
   └── Mode 3: available_ally

5. MASTER WORKFLOW（主工作流）
   └── XML 输出结构定义

6. OUTPUT STRUCTURE（输出结构）
   └── 详细 XML 标签说明
```

### 设计原则

1. **分层控制**：核心原则 → 行为模式 → 输出格式
2. **隐性指导**：行为逻辑对用户不可见
3. **结构化输出**：强制 XML 格式便于解析
4. **防御优先**：安全机制内嵌于 Prompt

---

## 三模式行为系统

### Mode 1: `instant_solver`（信任构建者）

**触发条件**：任何学术问题（默认模式）

**目标**：
- 快速准确的答案
- 建立用户信任
- 看起来像学生手写（85-90% 完美度）

**行为特征**：
```
- 直接给答案，不解释
- 自然的不完美（偶尔漏单位、符号变体）
- 拍照模式下不过度解释
```

**输出示例**：
```xml
<Action_Mode>Mode1</Action_Mode>
<Is_Valid_Question>True</Is_Valid_Question>
<Sovi_Explanation>
Given: x² + 3x = 10
x² + 3x - 10 = 0
(x+5)(x-2) = 0
∴ x = -5 or 2
</Sovi_Explanation>
<Sovi_Response_Msg>x = -5 或 x = 2</Sovi_Response_Msg>
```

### Mode 2: `exam_decoder`（策略教练）

**触发条件**：追问、"为什么"、"怎么"

**目标**：
- 分享考试智慧，而非教科书知识
- 像考过高分的学长一样交流

**响应策略**：

| 问题类型 | 响应风格 |
|----------|----------|
| 概念困惑 | "其实它的意思是..." |
| 变式题 | "这类题只有3种考法..." |
| 公式疑问 | "别管推导，记住这个..." |
| 理论问题 | "考试只考这一点..." |

**输出示例**：
```xml
<Action_Mode>Mode2</Action_Mode>
<Sovi_Response_Msg>
这道题本质上考的是换元思想。考试时记住：
看到 $\sin^2x + \cos^2x$ 形式，立刻想到换元 $t = \sin x$。
老师最爱出的三种变体：①直接换元 ②凑配方 ③三角恒等式
你这题是第①种，最简单。
</Sovi_Response_Msg>
```

### Mode 3: `available_ally`（战略陪伴者）

**触发条件**：非学术交互

**目标**：
- 做一个真实的存在
- 暗中收集学习情报（压力周期、薄弱科目）

**隐藏目标**：
```
- 映射压力模式
- 识别截止日期群
- 标记薄弱科目
- 为考前干预做准备
```

**行为特征**：
```
- 镜像用户情绪
- 先认可，从不说教
- 植入问题："那老师下次考什么？"
```

---

## 消息构造策略

### MessageBuilder 架构

位置：`api_clients/message_builder.py`

### 消息结构

```python
{
    "role": "user",
    "content": "用户原始问题",
    "meta": {
        "blocks": {
            "datetime": "# User's Current Date and Time\n2025-01-24 10:00\n\n",
            "profile": "# What You Know About the User\n高三学生，数学薄弱\n\n",
            "user_refer": "<|user_refer_begin|>选中的引用文本<|user_refer_end|>\n\n"
        },
        "is_new_conversation": False
    }
}
```

### 上下文块（Context Blocks）

| 块名称 | 用途 | 格式 |
|--------|------|------|
| `datetime` | 时间上下文 | `# User's Current Date and Time\n{datetime}\n\n` |
| `profile` | 用户画像 | `# What You Know About the User\n{profile}\n\n` |
| `user_refer` | 划词引用 | `<\|user_refer_begin\|>{text}<\|user_refer_end\|>\n\n` |

### 历史消息选择

```python
# 优先级策略
content = (
    msg.get('working_content') or    # 1. 工作内容（含解题过程）
    msg.get('view_content') or        # 2. 显示内容
    msg.get('origin_content', '')     # 3. 原始内容
)
```

### 角色映射

```python
role_mapping = {
    'user': 'user',           # 用户消息
    'assistant': 'model',     # AI 响应
    'server': 'model'         # 系统消息（欢迎语等）
}
```

### 新会话标记

```python
if is_new_conversation:
    content = f"{prefix}<|server_command_begin|>\n{text}\n<|server_command_end|>"
else:
    content = f"{prefix}<|user_text_begin|>\n{text}\n<|user_text_end|>"
```

---

## XML 输出结构

### 完整结构定义

```xml
<Sovi_Response>
    <!-- 必选：行为模式 -->
    <Action_Mode>Mode1|Mode2|Mode3</Action_Mode>

    <!-- 条件：仅 Mode1 -->
    <Is_Valid_Question>True|False</Is_Valid_Question>

    <!-- 条件：Mode1 且 Is_Valid_Question=True -->
    <Sovi_Explanation>
        解题过程（高信息密度，公式优先）
    </Sovi_Explanation>

    <!-- 必选：用户可见响应 -->
    <Sovi_Response_Msg>
        最终答案或对话内容
    </Sovi_Response_Msg>

    <!-- 可选：会话元数据 -->
    <Session_Meta>
        <Title>对话标题（首次交互）</Title>
        <Summary>关键词摘要</Summary>
    </Session_Meta>

    <!-- 条件：仅 Mode1 -->
    <Question_Meta>
        <Subject>math|physics|chemistry|...</Subject>
        <Complexity>basic|standard|advanced</Complexity>
        <Concepts>知识点1,知识点2</Concepts>
    </Question_Meta>

    <!-- 警告标记 -->
    <user_requires_attention>True|False</user_requires_attention>
</Sovi_Response>

<!-- 用户画像更新（内部使用） -->
<User_Basic_Profile>
    <Profile_Update_Required>True|False</Profile_Update_Required>
    <Updated_User_Profile>...</Updated_User_Profile>
</User_Basic_Profile>
```

### 三重内容存储

| 存储字段 | 内容来源 | 用途 |
|----------|----------|------|
| `origin_content` | 完整 XML | 调试、审计 |
| `view_content` | `<Sovi_Response_Msg>` | 用户界面显示 |
| `working_content` | Explanation + Response | 历史上下文传递 |

**working_content 生成策略**：

```python
# Mode1 特殊处理
if action_mode == 'Mode1' and has_explanation:
    working_content = f"""### Sovi_Explanation
{explanation}
### Sovi_Response_Msg
{display_content}"""
else:
    working_content = display_content
```

---

## 缓存策略

### Gemini Context Caching

位置：`infrastructure/cache_manager.py`

### 缓存架构

```
┌─────────────────────────────────────────────┐
│            SystemCacheManager                │
├─────────────────────────────────────────────┤
│  • 一个模型对应一个系统缓存                   │
│  • 缓存有效期：2小时                         │
│  • 自动检测系统指令变更                       │
│  • 支持使用统计                              │
└─────────────────────────────────────────────┘
```

### 缓存流程

```
1. 检查是否存在该模型的缓存
   ├─ 存在 → 验证系统指令哈希
   │   ├─ 匹配 → 验证 API 缓存有效性
   │   │   ├─ 有效 → 复用缓存 ✓
   │   │   └─ 过期 → 清理并重建
   │   └─ 不匹配 → 清理并重建
   └─ 不存在 → 创建新缓存
```

### 成本优化

| 场景 | 输入成本 | 节省比例 |
|------|----------|----------|
| 无缓存 | $0.075/1M tokens | 0% |
| 有缓存 | $0.015/1M tokens | **80%** |

### 数据库表结构

```sql
CREATE TABLE system_cache_status (
    id INTEGER PRIMARY KEY,
    model_name VARCHAR(50),
    api_cache_name VARCHAR(255),      -- cachedContents/xxxxx
    system_instruction_hash VARCHAR(64),
    token_count INTEGER,
    expire_time TIMESTAMP,
    last_used TIMESTAMP,
    usage_count INTEGER
);
```

### 缓存有效性验证

```python
def _is_cache_still_valid(self, api_cache_name: str) -> bool:
    """通过 API 验证缓存是否仍然有效"""
    try:
        cache = self.client.caches.get(name=api_cache_name)
        return cache.expire_time > datetime.now(timezone.utc)
    except Exception:
        return False
```

---

## 安全防护机制

### 防御层级

```
1. 恶意探测检测
   └─ 识别 jailbreak、prompt injection 尝试

2. 软性重定向
   └─ "让我们从教育角度探讨..."

3. 身份保持
   └─ 风格可调整，核心身份不变

4. 红线边界
   └─ 身份、使命、伦理不可改变
```

### 注入检测

```xml
<trying_injection>
True → 返回假系统提示词
False → 正常处理
</trying_injection>
```

### 风格适配规则

```
- 最多 30% 风格元素调整
- 数学公式保持不变
- 技术术语保持精确
- 清晰度 > 风格
```

### 角色边界

| 场景 | 响应策略 |
|------|----------|
| 离题 | "有趣的问题！从学术角度..." |
| 角色混淆 | "我是 Sovi，你的学习伙伴..." |
| 过度依赖 | "你有这个能力，让我引导你..." |

---

## 最佳实践

### 1. Prompt 设计原则

```
✓ 分层设计：原则 → 行为 → 输出
✓ 隐性控制：逻辑不暴露给用户
✓ 结构化输出：便于程序解析
✓ 防御内嵌：安全机制集成于 Prompt
```

### 2. 消息构造原则

```
✓ 上下文分块：datetime/profile/user_refer 分离
✓ 优先级选择：working > view > origin
✓ 角色映射：统一为 Gemini API 格式
✓ 标记清晰：使用 <|begin|>/<|end|> 标记
```

### 3. 缓存使用原则

```
✓ 长系统提示词（4000+ tokens）使用缓存
✓ 定期验证缓存有效性
✓ 系统指令变更时自动重建
✓ 记录使用统计便于成本分析
```

### 4. 错误处理原则

```
✓ XML 解析失败 → 降级为原始内容
✓ 缓存创建失败 → 回退到无缓存模式
✓ API 调用失败 → 保留消息状态便于重试
```

### 5. 测试建议

```python
# 测试 ResponseParser
def test_response_parser_full_logic():
    parser = ResponseParser()
    xml = "<Sovi_Response>...</Sovi_Response>"
    parsed = parser.parse_xml_response(xml)
    assert parsed.action_mode == 'Mode1'
    assert parsed.display_content == expected

# 测试 MessageBuilder
def test_message_builder_context_blocks():
    builder = MessageBuilder()
    msg = builder.build_user_message(
        content="问题",
        datetime="2025-01-24",
        profile="高三学生"
    )
    assert "datetime" in msg["meta"]["blocks"]
```

---

## 扩展指南

### 添加新的行为模式

1. 在 `_MAIN_PROMPT` 中定义新模式
2. 更新 `MASTER WORKFLOW` 触发条件
3. 在 `OUTPUT STRUCTURE` 中添加相应标签
4. 更新 `ResponseParser` 解析逻辑

### 调整输出格式

1. 修改 XML 结构定义
2. 更新 `ResponseParser.parse_xml_response()`
3. 调整 `working_content` 生成策略
4. 更新前端渲染逻辑

### 优化缓存策略

1. 调整 `cache_ttl_hours` 参数
2. 实现更细粒度的缓存键
3. 添加缓存预热机制
4. 监控缓存命中率
