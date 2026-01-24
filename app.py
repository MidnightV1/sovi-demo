"""
Flask 版本的 Sovi Demo
完全控制布局，解决 Streamlit 的布局限制问题
"""

# --- BEGIN GEVENT PATCH ---
# 仅在生产环境（即非Flask开发服务器运行时）应用补丁
# 这可以防止在本地 `python app.py` 调试时出现不必要的副作用
import os
# 通过检查 Gunicorn 相关的环境变量来判断是否在生产环境
if "GUNICORN_PID" in os.environ or os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn"):
    from gevent import monkey
    monkey.patch_all()
    print("[OK] Gevent monkey patch applied for streaming support")
# --- END GEVENT PATCH ---

# ----------------- 添加诊断代码 -----------------
print(f"[START] Server is running with: {os.environ.get('SERVER_SOFTWARE', 'Unknown / Not a WSGI server')}")
# -----------------------------------------------------------

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from flask_cors import CORS
import json
import logging
import random
import uuid
import base64
from datetime import datetime
from dotenv import load_dotenv

# 导入现有的后端逻辑
from auth import AuthManager
from config import Config
from core.service_container import ServiceContainer
try:
    # 避免强依赖，若不可用则使用本地备用欢迎语
    from api_clients.response_types import DEFAULT_WELCOME_MESSAGES
except Exception:
    DEFAULT_WELCOME_MESSAGES = [
        "你好！我是Sovi，你的AI学习伙伴！有什么可以帮助你的吗？",
        "欢迎使用Sovi！我在这里为你提供学习支持和问题解答。",
        "你好！很高兴与你交流，我是你的AI助手Sovi，随时为你服务！",
        "欢迎来到Sovi！我是你的学习伙伴，让我们开始一段有意义的对话吧！",
        "嗨！我是Sovi，你的智能学习助手。今天想学习什么呢？",
    ]
from infrastructure.storage_manager import get_storage_manager
from tools.utils import TimeUtils

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 日志与调试工具
LOG_VERBOSE = os.getenv('LOG_VERBOSE') in ('1', 'true', 'True') or os.getenv('DEBUG_SSE') in ('1', 'true', 'True')

def redact_snippet(text: str, head: int = 24, tail: int = 24) -> str:
    try:
        if not isinstance(text, str):
            return f"<{type(text).__name__}>"
        n = len(text)
        if n <= head + tail + 3:
            return text
        return f"{text[:head]}...{text[-tail:]} (len={n})"
    except Exception:
        return "<unprintable>"

# 创建Flask应用
app = Flask(__name__)
_secret_key = os.getenv('SECRET_KEY')
if not _secret_key:
    if os.getenv('LOCAL_DEV', 'true').lower() == 'true':
        _secret_key = 'dev-only-secret-key-do-not-use-in-production'
    else:
        raise ValueError("SECRET_KEY environment variable is required in production mode")
app.secret_key = _secret_key
CORS(app)

# 添加模板过滤器
@app.template_filter('format_message')
def format_message_content(content):
    """格式化消息内容，处理换行符和特殊字符"""
    if not content:
        return ""
    
    # 处理转义的换行符
    formatted = content.replace('\\n', '\n')
    
    # 转换为HTML格式，保留换行
    formatted = formatted.replace('\n', '<br>')
    
    return formatted

# 初始化服务
auth_manager = AuthManager()
# 当使用容器时，避免重复创建db/gemini。容器可回用现有实现。
_container = ServiceContainer.build_default()
db_manager = _container.get('db')
gemini_client = _container.get('gemini_client')  # 使用新架构（通过适配器）
response_parser = _container.get('response_parser')  # 使用业务层的XML解析器
_orchestrator = _container.get('chat_orchestrator')
_welcome_service = _container.get('welcome_service')

# Mock 模式配置
MOCK_MODE = False  # 使用fake Gemini客户端进行测试

class FlaskChatService:
    """Flask版本的聊天服务"""
    
    def __init__(self):
        self.db = db_manager if not MOCK_MODE else None
        
    def get_user_conversations(self, user_id: int, limit: int = 20):
        """获取用户对话历史"""
        if MOCK_MODE:
            # Mock数据
            mock_conversations = session.get('mock_conversations', [])
            return mock_conversations[:limit]
        else:
            return self.db.get_user_conversations(user_id, limit=limit)
    
    def create_conversation(self, user_id: int, title: str = "新对话"):
        """创建新对话"""
        if MOCK_MODE:
            conversations = session.get('mock_conversations', [])
            # 重新计算最大ID，防止排序或删除导致的错乱
            max_id = 0
            for c in conversations:
                if c.get('conversation_id', 0) > max_id:
                    max_id = c['conversation_id']
            conv_id = max_id + 1
            now_iso = TimeUtils.format_iso_utc(TimeUtils.utc_now())
            new_conv = {
                'conversation_id': conv_id,
                'title': title,
                'created_at': now_iso,
                'updated_at': now_iso
            }
            conversations.insert(0, new_conv)
            session['mock_conversations'] = conversations
            # 初始化消息
            messages = session.get('mock_messages', {})
            messages[str(conv_id)] = []
            session['mock_messages'] = messages
            return conv_id
        else:
            return self.db.create_conversation(user_id, title)
    
    def get_messages(self, conversation_id: int):
        """获取对话消息（支持新表结构）"""
        if MOCK_MODE:
            messages = session.get('mock_messages', {})
            return messages.get(str(conversation_id), [])
        else:
            # 使用新的查询方法，支持元数据关联查询
            raw_messages = self.db.get_conversation_messages_with_metadata(conversation_id)
            unified = []
            for m in raw_messages:
                # 构建统一格式的消息数据
                content = m.get('view_content') or m.get('origin_content') or ''
                created_at = m.get('created_at')
                if hasattr(created_at, 'isoformat'):
                    created_at = created_at.isoformat()
                
                message_data = {
                    'message_id': m.get('message_id'),
                    'role': m.get('role'),
                    'content': content,
                    'created_at': created_at,
                    'image_url': m.get('image_url'),  # 直接使用数据库中的完整URL
                    'action_mode': m.get('action_mode'),
                    'is_valid_question': m.get('is_valid_question'),
                    'content_summary': m.get('content_summary')
                }
                
                # 如果有元数据，添加到消息中
                if m.get('metadata'):
                    message_data['metadata'] = m['metadata']
                
                unified.append(message_data)
            return unified
    
    def add_message(self, conversation_id: int, role: str, content: str, round_num: int = 0, 
                    parsed_data: dict = None, image_data=None, user_id: int = None, send_status: str = 'success'):
        """添加消息（支持新的表拆分架构和独立欢迎消息）"""
        message = {
            'role': role,
            'content': content,
            'round_num': round_num,
            'created_at': TimeUtils.format_iso_utc(TimeUtils.utc_now()),
            'image_data': image_data,
            'user_id': user_id
        }
        
        if MOCK_MODE:
            # Mock模式：将扩展数据也存储到session中
            if parsed_data:
                message.update({
                    'working_content': parsed_data.get('working_content'),
                    'content_summary': parsed_data.get('content_summary'),
                    'action_mode': parsed_data.get('action_mode'),
                    'question_meta': parsed_data.get('question_meta'),
                    'is_valid_question': parsed_data.get('is_valid_question')
                })
            
            messages = session.get('mock_messages', {})
            conv_messages = messages.get(str(conversation_id), [])
            conv_messages.append(message)
            messages[str(conversation_id)] = conv_messages
            session['mock_messages'] = messages
            # 同步更新会话更新时间（如果有conversation_id）
            if conversation_id:
                conversations = session.get('mock_conversations', [])
                for conv in conversations:
                    if conv['conversation_id'] == conversation_id:
                        conv['updated_at'] = TimeUtils.format_iso_utc(TimeUtils.utc_now())
                        break
                session['mock_conversations'] = conversations
        else:
            # 真实数据库模式：使用新的拆分架构
            # API日志记录已移至gemini_client中，此处不再重复记录
            if parsed_data:
                # AI响应消息：包含完整的解析数据
                message_id = self.db.save_message(
                    conversation_id=conversation_id,
                    user_id=user_id,  # 新增必填参数
                    role=role,
                    round_num=round_num,
                    origin_content=parsed_data.get('raw_response', content),  # 原始AI响应
                    view_content=content,  # 显示给用户的内容
                    working_content=parsed_data.get('working_content'),
                    content_summary=parsed_data.get('content_summary'),
                    action_mode=parsed_data.get('action_mode'),
                    # 优先使用XML片段；若无则使用dict，DB层已兼容两种输入
                    question_meta=parsed_data.get('question_meta_xml') or parsed_data.get('question_meta'),  # 将被拆分到metadata表
                    is_valid_question=parsed_data.get('is_valid_question'),
                    image_url=image_data,
                    api_request_id=None,  # API记录已移至gemini_client中
                    send_status=send_status
                )
            else:
                # 简单消息（如用户消息）
                message_id = self.db.save_message(
                    conversation_id=conversation_id,
                    user_id=user_id,  # 新增必填参数
                    role=role,
                    origin_content=content,
                    round_num=round_num,
                    view_content=content,
                    working_content=content,  # 用户消息的working_content与view_content相同
                    image_url=image_data,  # 添加图片路径参数
                    send_status=send_status
                )

            message['message_id'] = message_id
        
        return message
    
    def generate_mock_response(self, user_message: str):
        """生成Mock响应"""
        responses = [
            f"这是对「{user_message[:30]}」的模拟回复...",
            "我理解了您的问题，让我为您详细解答。",
            "根据您提供的信息，我建议以下几种解决方案...",
            "这是一个很好的问题！让我从几个角度来分析。"
        ]
        import random
        return random.choice(responses)
    
    def update_conversation_title(self, conversation_id: int, title: str):
        """更新对话标题"""
        if MOCK_MODE:
            conversations = session.get('mock_conversations', [])
            for conv in conversations:
                if conv['conversation_id'] == conversation_id:
                    conv['title'] = title
                    conv['updated_at'] = TimeUtils.format_iso_utc(TimeUtils.utc_now())
                    break
            session['mock_conversations'] = conversations
        else:
            self.db.update_conversation_title(conversation_id, title)

chat_service = FlaskChatService()

@app.route('/')
def index():
    """首页 - 检查登录状态"""
    # 检查用户是否已登录
    token = request.args.get('token') or session.get('auth_token')
    
    if token:
        user = auth_manager._restore_session_from_token(token)
        if user:
            session['auth_token'] = token
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            return redirect(url_for('chat'))
    
    return render_template('login.html')


@app.route('/chat')
def chat():
    """聊天主页"""
    # 检查登录状态
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    username = session['username']
    
    # 检查是否是新对话请求，如果是则清理session状态
    auto_start_new = request.args.get('auto_start_new')
    if auto_start_new == 'true':
        session.pop('current_conversation_id', None)
        logger.info(f"清理session状态，用户ID: {user_id}")
        # 不重定向，让前端处理auto_start_new参数
    
    # 检查是否有指定的conversation_id参数
    conversation_id_param = request.args.get('conversation_id')
    current_conv_id = None
    
    if conversation_id_param:
        # 根据ID查找对话
        conversations = chat_service.get_user_conversations(user_id)
        for conv in conversations:
            try:
                # 统一转换为整数进行比较
                if int(conv.get('conversation_id')) == int(conversation_id_param):
                    current_conv_id = conv.get('conversation_id')
                    break
            except (ValueError, TypeError):
                # 如果转换失败，跳过这个对话
                continue
        
        if current_conv_id:
            # 切换到指定对话，确保session中存储整数类型
            session['current_conversation_id'] = int(current_conv_id)
        else:
            # ID无效，重定向到默认聊天页面
            return redirect(url_for('chat'))
    
    # 获取或使用现有对话
    current_conv_id = session.get('current_conversation_id')
    messages = []
    
    # 只有在有有效conversation_id时才加载消息
    if current_conv_id:
        messages = chat_service.get_messages(current_conv_id)
    
    # 获取对话历史列表
    conversations = chat_service.get_user_conversations(user_id)
    
    return render_template('chat.html', 
                        username=username,
                        user_id=user_id,
                        current_conv_id=current_conv_id,
                        conversations=conversations,
                        messages=messages)

@app.route('/profile')
def profile():
    """个人中心页面"""
    # 检查登录状态
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    username = session['username']
    
    # 获取用户统计信息
    if MOCK_MODE:
        # Mock模式下的统计
        mock_conversations = session.get('mock_conversations', [])
        conversation_count = len(mock_conversations)
        
        # 只计算用户发送的消息数（role='user'）
        mock_messages = session.get('mock_messages', {})
        message_count = 0
        for messages in mock_messages.values():
            message_count += sum(1 for msg in messages if msg.get('role') == 'user')
    else:
        # 真实数据库统计
        conversation_count = db_manager.get_user_conversation_count(user_id)
        message_count = db_manager.get_user_message_count(user_id)
    
    return render_template('profile.html',
                        username=username,
                        conversation_count=conversation_count,
                        message_count=message_count)

@app.route('/api/login', methods=['POST'])
def api_login():
    """统一的登录/注册API - 自动判断是登录还是注册"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'})
        
        # 使用合并的登录或注册方法
        user, message = auth_manager.login_or_register_flask(username, password)
        
        if user:
            # 创建会话token
            token = auth_manager._generate_session_token(user['user_id'])
            session['auth_token'] = token
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            
            # 清除旧的对话状态，确保每次登录都开始新对话
            session.pop('current_conversation_id', None)
            
            return jsonify({
                'success': True,
                'message': message,
                'redirect_url': url_for('chat'),
                'token': token,
                'start_new_conversation': True  # 标记需要开始新对话
            })
        else:
            return jsonify({'success': False, 'message': message})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})

@app.route('/api/chat/send', methods=['POST'])
def api_send_message():
    """发送消息API - 支持流式响应"""
    # 时间戳1: 收到客户端请求
    timestamp_request_received = datetime.now()
    
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    try:
        correlation_id = str(uuid.uuid4())
        data = request.get_json() or {}
        message = data.get('message', '').strip()
        is_new_conversation = data.get('is_new_conversation', False)
        conv_id = data.get('conversation_id') or session.get('current_conversation_id')
        user_id = session['user_id']

        image_file_info = data.get('image_file_info')
        image_data_url = data.get('image_data_url')
        client_datetime = data.get('datetime', '').strip()
        client_language = data.get('language', '').strip()
        client_timezone_offset = data.get('timezone_offset')

        logger.info(f"[PERF][{correlation_id}] Request received: {timestamp_request_received.isoformat()}")
        logger.info(f"[send][{correlation_id}] 请求开始 user={user_id} conv_id={conv_id} is_new={is_new_conversation}")
        logger.info(f"[send][{correlation_id}] 客户端: time={client_datetime}, lang={client_language}")
        if image_file_info:
            logger.info(f"[send][{correlation_id}] 包含图片: name={image_file_info.get('filename','unknown')} path={image_file_info.get('file_path')}")

        if not message and not image_file_info:
            return jsonify({'success': False, 'message': '消息内容或图片不能为空'})

        # 新对话创建/激活欢迎
        if is_new_conversation or not conv_id:
            logger.info(f"[send][{correlation_id}] 创建新对话: is_new={is_new_conversation} prev_conv={conv_id}")
            try:
                conv_id = chat_service.create_conversation(user_id, "新对话")
                logger.info(f"[send][{correlation_id}] 对话创建成功: conv_id={conv_id}")
                session['current_conversation_id'] = int(conv_id)
                if not MOCK_MODE:
                    welcome_msg = db_manager.get_user_welcome_message(user_id, window_minutes=30)
                    if welcome_msg:
                        if db_manager.update_welcome_message_to_active(welcome_msg['message_id'], conv_id):
                            logger.info(f"[send][{correlation_id}] 欢迎消息已激活: message_id={welcome_msg['message_id']}, conv_id={conv_id}")
                        else:
                            logger.warning(f"[send][{correlation_id}] 欢迎消息激活失败")
            except Exception as e:
                logger.error(f"创建新对话失败: {str(e)}")
                return jsonify({'success': False, 'message': f'创建对话失败: {str(e)}'})
        else:
            # 验证对话ID存在
            logger.info(f"[send][{correlation_id}] 验证对话ID是否存在: conversation_id={conv_id}")
            try:
                existing_conversations = chat_service.get_user_conversations(user_id)
                conv_exists = False
                for conv in existing_conversations:
                    db_conv_id = conv.get('conversation_id')
                    try:
                        if int(db_conv_id) == int(conv_id):
                            conv_exists = True
                            break
                    except (ValueError, TypeError):
                        if str(db_conv_id) == str(conv_id):
                            conv_exists = True
                            break
                if not conv_exists:
                    logger.warning(f"[send][{correlation_id}] 对话ID不存在，创建新对话: conversation_id={conv_id}")
                    session.pop('current_conversation_id', None)
                    conv_id = chat_service.create_conversation(user_id, "新对话")
                    logger.info(f"[send][{correlation_id}] 新对话创建成功: conv_id={conv_id}")
                    session['current_conversation_id'] = int(conv_id)
                else:
                    logger.info(f"[send][{correlation_id}] 对话ID验证通过: conversation_id={conv_id}")
            except Exception as e:
                logger.error(f"验证对话ID时出错: {str(e)}")
                return jsonify({'success': False, 'message': '对话不存在，请使用新对话功能重新开始', 'error_code': 'CONVERSATION_NOT_FOUND'})

        # 轮次
        if not MOCK_MODE:
            round_num = db_manager.get_next_round_num(conv_id)
        else:
            messages = session.get('mock_messages', {}).get(str(conv_id), [])
            user_messages = [m for m in messages if m['role'] == 'user']
            round_num = len(user_messages) + 1

        # 入库用户消息（V2 下由编排器创建 pending，避免重复落库）
        # 使用完整的access_url而不是相对路径file_path
        image_url = image_file_info.get('access_url') if image_file_info else None
        if image_url:
            logger.info(f"[send][{correlation_id}] 准备保存图片URL到数据库: {image_url}")
        user_message_id = None
        if not Config.USE_CHAT_V2:
            user_msg = chat_service.add_message(
                conversation_id=conv_id,
                role='user',
                content=message,
                round_num=round_num,
                user_id=user_id,
                image_data=image_url,  # 保存完整URL而不是相对路径
                send_status='pending'
            )
            user_message_id = user_msg.get('message_id')
        
        # 时间戳2: 用户消息入库完成
        timestamp_user_message_saved = datetime.now()
        logger.info(f"[PERF][{correlation_id}] User message saved: {timestamp_user_message_saved.isoformat()}")
        logger.info(f"[send][{correlation_id}] 用户消息入库: msg_id={user_message_id} round={round_num} image={bool(image_url)} content_len={len(message) if message else 0}")

        def generate():
            try:
                # 时间戳3: 开始API调用
                timestamp_api_start = datetime.now()
                logger.info(f"[PERF][{correlation_id}] API call started: {timestamp_api_start.isoformat()}")
                
                if Config.USE_CHAT_V2:
                    v2_round = db_manager.get_next_round_num(conv_id) if not MOCK_MODE else (len(session.get('mock_messages', {}).get(str(conv_id), [])) + 1)
                    v2_image_path = image_file_info.get('access_url') if image_file_info else None  # 修复：使用完整URL而不是相对路径
                    logger.info(f"[send][{correlation_id}] V2编排开始: round={v2_round} has_image={bool(v2_image_path)} msg_len={len(message) if message else 0}")
                    
                    first_response_logged = False
                    for evt in _orchestrator.stream_chat(
                        user_id=user_id,
                        conversation_id=conv_id,
                        user_text=message,
                        round_num=v2_round,
                        image_path=v2_image_path,
                        client_datetime=client_datetime,
                        client_language=client_language,
                        client_timezone_offset=data.get('timezone_offset'),
                    ):
                        # 时间戳4: 第一个响应返回
                        if not first_response_logged:
                            timestamp_first_response = datetime.now()
                            logger.info(f"[PERF][{correlation_id}] First response: {timestamp_first_response.isoformat()}")
                            first_response_logged = True
                        if LOG_VERBOSE and isinstance(evt, str) and evt.startswith('data: '):
                            try:
                                payload = json.loads(evt[6:])
                                if payload.get('type') == 'chunk':
                                    snippet = redact_snippet(payload.get('content', ''))
                                    logger.debug(f"[send][{correlation_id}] chunk(len={len(payload.get('content',''))}): {snippet}")
                            except Exception:
                                pass
                        yield evt
                    logger.info(f"[send][{correlation_id}] V2编排结束")
                    # 时间戳5: API响应完成  
                    timestamp_api_complete = datetime.now()
                    logger.info(f"[PERF][{correlation_id}] API response completed: {timestamp_api_complete.isoformat()}")
                    return

                # 遗留流式
                user_profile = db_manager.get_active_user_profile(user_id) if not MOCK_MODE else None
                full_response = ""
                streaming_started = False
                streaming_finished = False
                sent_length = 0
                start_tag = "<Sovi_Response_Msg>"
                end_tag = "</Sovi_Response_Msg>"
                msg_started = False
                msg_finished = False
                leading_trimmed = False
                start_index = -1
                extracted_buffer = ""

                image_bytes = None
                if image_file_info and image_file_info.get('file_path'):
                    try:
                        storage_manager = get_storage_manager()
                        # 使用原始的file_path从存储中获取图片数据
                        file_path = image_file_info.get('file_path')
                        image_bytes = storage_manager.get_image_data(file_path)
                        if image_bytes:
                            logger.info(f"[send][{correlation_id}] 图片数据加载成功: {len(image_bytes)} bytes")
                        else:
                            logger.warning(f"[send][{correlation_id}] 未找到图片文件: {file_path}")
                    except Exception as e:
                        logger.error(f"[send][{correlation_id}] 图片数据加载失败: {str(e)}")

                import time
                last_heartbeat = time.time()
                heartbeat_interval = 30

                for chunk in gemini_client.chat_with_streaming(
                    user_input=message,
                    user_id=user_id,
                    user_profile=user_profile,
                    conversation_id=conv_id,
                    message_id=user_message_id,
                    client_datetime=client_datetime,
                    client_language=client_language,
                    client_timezone_offset=data.get('timezone_offset'),
                    image_data=image_bytes
                ):
                    current_time = time.time()
                    if current_time - last_heartbeat > heartbeat_interval:
                        yield ": heartbeat\n\n"
                        last_heartbeat = current_time

                    chunk_text = ""
                    if hasattr(chunk, 'text') and chunk.text:
                        chunk_text = chunk.text
                        full_response += chunk_text
                        if LOG_VERBOSE:
                            logger.debug(f"[send][{correlation_id}] recv_chunk(len={len(chunk_text)}): {redact_snippet(chunk_text)}")
                    else:
                        continue

                    if not streaming_finished:
                        if not streaming_started and start_tag in full_response:
                            streaming_started = True
                            sent_length = 0
                            logger.info(f"[send][{correlation_id}] 检测到开始标签 {start_tag}")

                        if streaming_started:
                            start_pos = full_response.find(start_tag) + len(start_tag)
                            current_content = full_response[start_pos:]
                            if end_tag in current_content:
                                streaming_finished = True
                                end_pos = current_content.find(end_tag)
                                current_content = current_content[:end_pos]
                                logger.info(f"[send][{correlation_id}] 检测到结束标签 {end_tag}")
                            current_content = current_content.strip()
                            if len(current_content) > sent_length:
                                new_content = current_content[sent_length:]
                                if new_content:
                                    if LOG_VERBOSE:
                                        logger.debug(f"[send][{correlation_id}] send_chunk(len={len(new_content)}): {redact_snippet(new_content)}")
                                    yield f"data: {json.dumps({'type': 'chunk', 'content': new_content})}\n\n"
                                    sent_length = len(current_content)

                if not streaming_started:
                    logger.warning(f"警告：完整响应未找到开始标签 {start_tag}")
                    logger.warning(f"响应前100字符: {full_response[:100]}")
                elif not streaming_finished:
                    logger.warning(f"警告：响应找到开始标签但未找到结束标签 {end_tag}")

                parsed_response = response_parser.parse_xml_response(full_response)
                display_content = parsed_response.get('display_content', full_response)
                if display_content.startswith('\n'):
                    display_content = display_content.lstrip('\n')
                if display_content.endswith('\n'):
                    display_content = display_content.rstrip('\n')

                assistant_msg = chat_service.add_message(
                    conversation_id=conv_id,
                    role='assistant',
                    content=display_content,
                    round_num=round_num,
                    parsed_data=parsed_response,
                    user_id=user_id
                )

                session_meta = parsed_response.get('session_meta', {})
                if session_meta.get('title'):
                    current_title = None
                    if not MOCK_MODE:
                        current_title = db_manager.get_conversation_title(conv_id)
                    else:
                        for c in session.get('mock_conversations', []):
                            if c['conversation_id'] == conv_id:
                                current_title = c.get('title')
                                break
                    if not current_title or current_title.startswith('新对话') or current_title in ('无标题对话', '新对话'):
                        chat_service.update_conversation_title(conv_id, session_meta['title'])

                profile_update = parsed_response.get('profile_update')
                if profile_update and profile_update.get('profile_update_required'):
                    updated_profile = profile_update.get('updated_user_profile')
                    if updated_profile and not MOCK_MODE:
                        db_manager.save_user_profile(user_id, updated_profile)

                yield f"data: {json.dumps({'type': 'complete', 'conversation_id': conv_id, 'parsed_response': parsed_response.to_dict()})}\n\n"
                logger.info(f"[send][{correlation_id}] SSE complete 已发送 conv_id={conv_id}")

                if not MOCK_MODE:
                    db_manager.update_message_status(user_message_id, 'success')
                    logger.info(f"[send][{correlation_id}] 用户消息状态更新为 success: msg_id={user_message_id}")

            except Exception as e:
                logger.exception(f"[send][{correlation_id}] 处理异常: {e}")
                error_message = "响应超时，请检查网络连接" if isinstance(e, TimeoutError) else "消息发送失败，请检查网络设置"
                yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"
                if not MOCK_MODE:
                    db_manager.update_message_status(user_message_id, 'failed')
                    logger.info(f"[send][{correlation_id}] 用户消息状态更新为 failed: msg_id={user_message_id}")

        return Response(generate(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'发送失败: {str(e)}'})

@app.route('/api/ask-follow-up', methods=['POST'])
def api_ask_follow_up():
    """划词追问API（SSE）。请求体至少包含 quote, question, conversation_id。
    可选: full_context, datetime, language, timezone_offset。
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})

    try:
        data = request.get_json() or {}
        quote = (data.get('quote') or '').strip()
        question = (data.get('question') or '').strip()
        conversation_id = data.get('conversation_id') or session.get('current_conversation_id')
        client_datetime = (data.get('datetime') or '').strip()
        client_language = (data.get('language') or '').strip()
        client_timezone_offset = data.get('timezone_offset')
        user_id = session['user_id']

        # 基础校验
        if not conversation_id:
            return jsonify({'success': False, 'message': '缺少会话ID'}), 400
        if not question:
            return jsonify({'success': False, 'message': '问题不能为空'}), 400
        if quote and len(quote) > 1500:
            return jsonify({'success': False, 'message': '引用内容过长'}), 400

        # 验证对话ID归属与存在（与发送接口一致）
        try:
            existing_conversations = chat_service.get_user_conversations(user_id)
            conv_exists = False
            for conv in existing_conversations:
                db_conv_id = conv.get('conversation_id')
                try:
                    if int(db_conv_id) == int(conversation_id):
                        conv_exists = True
                        break
                except (ValueError, TypeError):
                    if str(db_conv_id) == str(conversation_id):
                        conv_exists = True
                        break
            if not conv_exists:
                return jsonify({'success': False, 'message': '对话不存在'}), 404
        except Exception:
            return jsonify({'success': False, 'message': '会话校验失败'}), 400

        # 轮次计算（与V2一致由DB计算）
        if not MOCK_MODE:
            round_num = db_manager.get_next_round_num(conversation_id)
        else:
            messages = session.get('mock_messages', {}).get(str(conversation_id), [])
            user_messages = [m for m in messages if m['role'] == 'user']
            round_num = len(user_messages) + 1

        def generate():
            try:
                first_response_logged = False
                for evt in _orchestrator.stream_chat(
                    user_id=user_id,
                    conversation_id=int(conversation_id),
                    user_text=question,
                    user_refer_text=quote or None,
                    round_num=round_num,
                    image_path=None,
                    client_datetime=client_datetime,
                    client_language=client_language,
                    client_timezone_offset=client_timezone_offset,
                ):
                    if not first_response_logged:
                        first_response_logged = True
                    yield evt
            except Exception as e:
                import logging as _logging
                _logging.getLogger(__name__).exception(f"follow-up 处理异常: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': '追问失败，请稍后重试'})}\n\n"

        return Response(generate(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'追问失败: {str(e)}'})

@app.route('/api/chat/send_sync', methods=['POST']) 
def api_send_message_sync():
    """发送消息API - 同步版本（用于兼容）"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        conv_id = data.get('conversation_id') or session.get('current_conversation_id')
        
        # 新增：获取客户端时间和语言信息
        client_datetime = data.get('datetime', '').strip()
        client_language = data.get('language', '').strip()
        client_timezone_offset = data.get('timezone_offset')
        
        if not message:
            return jsonify({'success': False, 'message': '消息内容不能为空'})
        
        # 添加用户消息
        user_msg = chat_service.add_message(
            conversation_id=conv_id, 
            role='user', 
            content=message, 
            user_id=session['user_id']
        )
        user_message_id = user_msg.get('message_id')  # 获取消息ID用于API记录
        
        # 生成回复 (Mock模式)
        if MOCK_MODE:
            reply = chat_service.generate_mock_response(message)
        else:
            # 获取AI回复
            user_id = session['user_id'] 
            user_profile = None  # TODO: 从数据库加载用户画像
            
            # 收集流式响应 - 让gemini_client自己处理历史对话
            full_response = ""
            for chunk in gemini_client.chat_with_streaming(
                user_input=message,
                user_id=user_id,
                user_profile=user_profile, 
                conversation_id=conv_id,
                message_id=user_message_id,
                client_datetime=client_datetime,  # 新增：传递客户端时间
                client_language=client_language,   # 新增：传递客户端语言
                client_timezone_offset=client_timezone_offset
            ):
                # 确保从chunk对象正确提取文本
                chunk_text = ""
                if hasattr(chunk, 'text') and chunk.text:
                    chunk_text = chunk.text
                elif isinstance(chunk, str):
                    chunk_text = chunk
                full_response += chunk_text
            
            # 解析响应
            parsed_response = response_parser.parse_xml_response(full_response)
            reply = parsed_response.get('display_content', full_response)
            # 处理标题（与流式逻辑一致）
            session_meta = parsed_response.get('session_meta', {})
            if session_meta.get('title'):
                current_title = None
                if not MOCK_MODE:
                    current_title = db_manager.get_conversation_title(conv_id)
                else:
                    for c in session.get('mock_conversations', []):
                        if c['conversation_id'] == conv_id:
                            current_title = c.get('title')
                            break
                if not current_title or current_title.startswith('新对话') or current_title in ('无标题对话', '新对话'):
                    chat_service.update_conversation_title(conv_id, session_meta['title'])
        
        # 添加助手回复
        assistant_msg = chat_service.add_message(
            conversation_id=conv_id, 
            role='assistant', 
            content=reply, 
            user_id=session['user_id']
        )

        return jsonify({
            'success': True,
            'user_message': user_msg,
            'assistant_message': assistant_msg
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'发送失败: {str(e)}'})

@app.route('/api/chat/new', methods=['POST'])
def api_new_chat():
    """新建对话API - 仅生成独立欢迎消息（round_num=-1），不创建conversation记录"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    try:
        # 获取请求数据
        data = request.get_json() or {}
        client_datetime = data.get('datetime', '').strip()
        client_language = data.get('language', 'EN').strip()  # 从请求中获取语言，默认英文
        client_timezone_offset = data.get('timezone_offset', 0)  # 时区偏移量（分钟）
        
        user_id = session['user_id']
        chat_service = FlaskChatService()
        
        # 检查是否已有30分钟内的欢迎消息
        if not MOCK_MODE:
            existing_welcome = db_manager.get_user_welcome_message(user_id, window_minutes=30)
            if existing_welcome:
                logger.info(f"复用30分钟内的欢迎消息: message_id={existing_welcome['message_id']}, created_at={existing_welcome['created_at']}")
                # 直接返回缓存的欢迎消息
                welcome_content = existing_welcome.get('view_content') or existing_welcome.get('origin_content')
                return Response(
                    f"data: {json.dumps({'success': True, 'cached': True})}\n\n" +
                    f"data: {json.dumps({'type': 'chunk', 'content': welcome_content})}\n\n" +
                    f"data: {json.dumps({'type': 'complete'})}\n\n",
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
                )
            else:
                logger.info(f"未找到30分钟窗口内的未激活欢迎消息（round_num=-1），将生成新的欢迎消息")

        # 如果开启新欢迎流开关，走WelcomeService路径（保持默认遗留路径不变）
        if Config.USE_WELCOME_V2:
            # 清理失败欢迎消息并清空当前会话ID
            try:
                if not MOCK_MODE:
                    db_manager.cleanup_failed_welcome_messages(user_id)
            except Exception as e:
                logger.warning(f"清理失败欢迎消息时出错: {str(e)}")

            session.pop('current_conversation_id', None)

            # 由WelcomeService负责流式生成与入库（round_num=-1）
            return Response(
                _welcome_service.stream_welcome(user_id, client_datetime, client_language, client_timezone_offset),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
            )
        
        # 清除可能存在的失败欢迎消息记录
        try:
            if not MOCK_MODE:
                # 删除包含错误信息的欢迎消息
                db_manager.cleanup_failed_welcome_messages(user_id)
        except Exception as e:
            logger.warning(f"清理失败欢迎消息时出错: {str(e)}")
        
        # 清除旧的对话状态，确保重新开始
        session.pop('current_conversation_id', None)
        
        # 生成AI欢迎消息
        user_profile = None
        last_message_time = None
        if not MOCK_MODE:
            user_profile = db_manager.get_active_user_profile(user_id)
            last_message_time = db_manager.get_user_last_message_time(user_id)
        
        def generate_welcome_stream():
            # 首先发送对话准备成功的信息
            yield f"data: {json.dumps({'success': True, 'new_welcome': True})}\n\n"
            
            try:
                # 使用统一的chat_with_streaming生成欢迎消息
                full_response = ""
                # 优先使用客户端传入时间；否则根据时区偏移生成本地当前时间
                if client_datetime:
                    current_time = client_datetime
                else:
                    try:
                        from datetime import timezone, timedelta
                        current_time = (datetime.now(timezone.utc) + timedelta(minutes=int(client_timezone_offset))).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                # 格式化用户上次消息时间信息
                last_message_info = ""
                if last_message_time:
                    # 将UTC时间转换为用户本地时间
                    from datetime import timedelta
                    # client_timezone_offset 是分钟，正值表示东时区，负值表示西时区
                    local_last_time = last_message_time + timedelta(minutes=client_timezone_offset)
                    # 格式化为 YYYY-MM-DD HH:MM 格式
                    last_time_str = local_last_time.strftime("%Y-%m-%d %H:%M")
                    last_message_info = f"### User's last message time (local time)\n{last_time_str}"
                else:
                    last_message_info = "No Time Gap! It's a new user, first time meet you, Welcome and introduce yourself!"
                
                # 用于流式XML解析
                buffer = ""
                inside_sovi_response_msg = False
                sovi_msg_content = ""
                
                # 新对话发起命令体（集中化管理，命令体进入 <|server_command_begin|>）
                from prompts.system_prompts import SystemPrompts
                # 统一 last_message_info 文本格式
                if last_message_time:
                    last_message_info = f"Last seen: {last_time_str}"
                else:
                    last_message_info = "No Time Gap! It's a new user, first time meet you, Welcome and introduce yourself!"

                welcome_prompt = SystemPrompts.get_welcome_generation_command(
                    client_language=client_language,
                    last_message_info=last_message_info,
                    user_profile=user_profile,
                )
                for chunk in gemini_client.chat_with_streaming(
                    user_input=welcome_prompt,
                    user_id=user_id,
                    user_profile=user_profile,
                    conversation_id=None,  # 独立欢迎消息，无conversation_id
                    message_id=None,
                    client_datetime=current_time,
                    client_language=client_language,
                    is_new_conversation=True,  # 明确标识这是新对话
                    session_context='welcome_generation'  # 标识这是欢迎消息生成
                ):
                    # 获取chunk内容
                    chunk_text = ""
                    if hasattr(chunk, 'text') and chunk.text:
                        chunk_text = chunk.text
                    elif chunk and str(chunk):
                        chunk_text = str(chunk)
                    
                    if chunk_text:
                        full_response += chunk_text
                        buffer += chunk_text
                        
                        # 实时解析XML，只发送Sovi_Response_Msg内容
                        while True:
                            if not inside_sovi_response_msg:
                                # 寻找Sovi_Response_Msg开始标签
                                start_tag = "<Sovi_Response_Msg>"
                                start_idx = buffer.find(start_tag)
                                if start_idx != -1:
                                    inside_sovi_response_msg = True
                                    buffer = buffer[start_idx + len(start_tag):]
                                    continue
                                else:
                                    break
                            else:
                                # 在Sovi_Response_Msg内部，寻找结束标签
                                end_tag = "</Sovi_Response_Msg>"
                                end_idx = buffer.find(end_tag)
                                if end_idx != -1:
                                    # 找到结束标签，发送剩余内容
                                    remaining_content = buffer[:end_idx]
                                    if remaining_content:
                                        sovi_msg_content += remaining_content
                                        yield f"data: {json.dumps({'type': 'chunk', 'content': remaining_content})}\n\n"
                                    inside_sovi_response_msg = False
                                    buffer = buffer[end_idx + len(end_tag):]
                                    break
                                else:
                                    # 还没找到结束标签，发送当前buffer内容
                                    if buffer:
                                        sovi_msg_content += buffer
                                        yield f"data: {json.dumps({'type': 'chunk', 'content': buffer})}\n\n"
                                        buffer = ""
                                    break
                
                # 解析完整响应
                welcome_parsed = response_parser.parse_xml_response(full_response)
                welcome_content = welcome_parsed.get('display_content', sovi_msg_content)
                
                # 如果解析失败或内容为空，使用默认内容
                if not welcome_content or not welcome_content.strip():
                    welcome_content = random.choice(DEFAULT_WELCOME_MESSAGES)
                    welcome_parsed = {'display_content': welcome_content}
                    # 如果之前没有发送任何内容，发送默认内容作为流
                    if not sovi_msg_content:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': welcome_content})}\n\n"
                    
            except Exception as e:
                logger.error(f"生成AI欢迎消息失败: {str(e)}")
                # 失败时使用默认欢迎语
                welcome_content = random.choice(DEFAULT_WELCOME_MESSAGES)
                welcome_parsed = {'display_content': welcome_content}
                full_response = welcome_content
                # 发送错误信息和默认内容
                yield f"data: {json.dumps({'type': 'error', 'message': '生成欢迎消息失败，使用默认消息'})}\n\n"
                yield f"data: {json.dumps({'type': 'chunk', 'content': welcome_content})}\n\n"
                
                # 重要：失败的欢迎消息不存储到数据库，避免后续复用错误状态
                logger.warning(f"AI生成失败，不存储欢迎消息到数据库，用户: {user_id}")
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return
            
            # 只有成功生成时才存储到数据库
            try:
                # 确保有内容可存储，按优先级选择内容
                final_content = welcome_content or sovi_msg_content or full_response
                if not final_content or not final_content.strip():
                    final_content = random.choice(DEFAULT_WELCOME_MESSAGES)
                    welcome_parsed = {'display_content': final_content}
                
                # 保存为独立欢迎消息（round_num=-1，conversation_id=None）
                welcome_msg = chat_service.add_message(
                    conversation_id=None,  # 独立消息，无conversation_id
                    role='server', 
                    content=final_content, 
                    round_num=-1,  # 标记为未激活的欢迎消息
                    parsed_data=welcome_parsed or {},
                    user_id=user_id  # 关联到用户
                )
                logger.info(f"独立欢迎消息已存储: message_id={welcome_msg.get('message_id')}, user_id={user_id}, content_len={len(final_content)}")
            except Exception as save_error:
                logger.error(f"保存独立欢迎消息失败: {str(save_error)}")
                # 存储失败不影响用户体验，继续完成流程
            
            # 发送完成信号
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        # 返回SSE流
        return Response(
            generate_welcome_stream(),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
        )

    except Exception as e:
        logger.error(f"创建新对话失败: {str(e)}")
        return jsonify({'success': False, 'message': f'创建新对话失败: {str(e)}'})

@app.route('/api/conversations')
def api_get_conversations():
    """获取对话列表API"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    try:
        user_id = session['user_id']
        conversations = chat_service.get_user_conversations(user_id)
        
        return jsonify({
            'success': True,
            'conversations': conversations
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取对话失败: {str(e)}'})

@app.route('/api/chat/<int:conv_id>/messages')
def api_get_messages(conv_id):
    """获取对话消息API"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    try:
        messages = chat_service.get_messages(conv_id)
        session['current_conversation_id'] = int(conv_id)  # 确保存储为整数
        
        return jsonify({
            'success': True,
            'messages': messages,
            'conversation_id': conv_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取消息失败: {str(e)}'})

@app.route('/api/chat/<int:conv_id>', methods=['DELETE'])
def delete_conversation(conv_id):
    """删除对话"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': '请先登录'})
        
        chat_service = FlaskChatService()
        
        if MOCK_MODE:
            # Mock模式：从session中删除对话
            mock_conversations = session.get('mock_conversations', [])
            session['mock_conversations'] = [conv for conv in mock_conversations if conv['conversation_id'] != conv_id]
            
            # 同时删除相关消息
            session_messages = session.get('messages', {})
            if str(conv_id) in session_messages:
                del session_messages[str(conv_id)]
                session['messages'] = session_messages
                
        else:
            # 真实数据库模式
            success = db_manager.delete_conversation(conv_id, user_id)
            if not success:
                return jsonify({'success': False, 'message': '删除失败或对话不存在'})
        
        # 如果删除的是当前session中的对话，清空相关session数据
        current_session_conv_id = session.get('current_conversation_id')
        if current_session_conv_id and int(current_session_conv_id) == int(conv_id):
            session.pop('current_conversation_id', None)
            print(f"已清空session中的current_conversation_id: {current_session_conv_id}")
        
        return jsonify({
            'success': True,
            'message': '对话已删除'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

@app.route('/logout')
def logout():
    """登出"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/test-latex')
def test_latex():
    """测试LaTeX渲染的简单页面"""
    return '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>LaTeX 诊断测试</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; }
        .test-case { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
        .status { margin: 10px 0; padding: 10px; background: #f0f0f0; font-family: monospace; }
    </style>
</head>
<body>
    <h1>LaTeX 渲染诊断测试</h1>
    
    <div class="status" id="status">检查中...</div>
    
    <div class="test-case">
        <h3>测试1: 内联公式</h3>
        <p>这是一个简单的公式：$E = mc^2$</p>
    </div>
    
    <div class="test-case">
        <h3>测试2: 块级公式</h3>
        $$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$
    </div>
    
    <div class="test-case">
        <h3>测试3: 您发送的例子</h3>
        <p>这里面有小x和小y两个未知数：$2x + 3y = 7$</p>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const statusEl = document.getElementById('status');
            let status = [];
            
            // 检查KaTeX库
            if (typeof katex !== 'undefined') {
                status.push('[OK] KaTeX核心库已加载');
            } else {
                status.push('[FAIL] KaTeX核心库未加载');
            }

            // 检查渲染函数
            if (typeof renderMathInElement !== 'undefined') {
                status.push('[OK] renderMathInElement函数已加载');

                try {
                    renderMathInElement(document.body, {
                        delimiters: [
                            {left: '$$', right: '$$', display: true},
                            {left: '$', right: '$', display: false}
                        ],
                        throwOnError: false
                    });
                    status.push('[OK] LaTeX渲染执行完成');
                } catch (e) {
                    status.push('[FAIL] LaTeX渲染出错: ' + e.message);
                }
            } else {
                status.push('[FAIL] renderMathInElement函数未加载');
            }

            statusEl.innerHTML = status.join('<br>');

            // 额外检查：5秒后再次检查渲染结果
            setTimeout(function() {
                const mathElements = document.querySelectorAll('.katex');
                status.push(`[INFO] 找到 ${mathElements.length} 个已渲染的数学元素`);
                statusEl.innerHTML = status.join('<br>');
            }, 5000);
        });
    </script>
</body>
</html>
    '''

@app.route('/api/retry-message/<int:message_id>', methods=['POST'])
def api_retry_message(message_id):
    """重试发送失败的消息"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录'})
    
    try:
        user_id = session['user_id']
        db_manager = Config.get_database_manager()
        
        # 获取原始消息
        message = db_manager.get_message_by_id(message_id)
        if not message:
            return jsonify({'success': False, 'message': '消息不存在'})
        
        # 验证消息所有权
        if message['user_id'] != user_id:
            return jsonify({'success': False, 'message': '无权限操作此消息'})
        
        # 检查消息状态
        if message['send_status'] != 'failed':
            return jsonify({'success': False, 'message': '消息状态不正确'})
        
        # 检查图片上传状态
        if message['image_url']:
            # 图片已上传成功，直接重试模型调用
            return _retry_with_existing_image(message, db_manager)
        else:
            # 图片上传失败或无图片，需要前端重新上传
            return jsonify({
                'success': False, 
                'message': '需要重新上传图片',
                'error_code': 'IMAGE_UPLOAD_REQUIRED',
                'original_message': {
                    'message_id': message['message_id'],
                    'content': message['origin_content'],
                    'conversation_id': message['conversation_id']
                }
            })
            
    except Exception as e:
        logger.error(f"重试消息失败: {str(e)}")
        return jsonify({'success': False, 'message': f'重试失败: {str(e)}'})

def _retry_with_existing_image(message, db_manager):
    """使用现有图片重试模型调用"""
    try:
        # 更新消息状态为 pending
        db_manager.update_message_status(message['message_id'], 'pending')
        
        # 准备图片数据
        image_bytes = None
        if message['image_url']:
            try:
                storage_manager = get_storage_manager()
                image_bytes = storage_manager.get_image_data(message['image_url'])
            except Exception as e:
                logger.error(f"获取图片数据失败: {str(e)}")
                # 图片获取失败，标记消息为失败状态
                db_manager.update_message_status(message['message_id'], 'failed')
                return jsonify({'success': False, 'message': '图片数据获取失败，请重新上传图片'})
        
        # 获取用户画像
        user_profile = db_manager.get_active_user_profile(message['user_id'])
        
        # 重新调用模型
        try:
            # 这里使用容器获取客户端实例，保持一致性
            retry_gemini_client = _container.get('gemini_client')
            
            # 简化的同步调用（获取完整响应）
            full_response = ""
            for chunk in retry_gemini_client.chat_with_streaming(
                user_input=message['origin_content'],
                user_id=message['user_id'],
                user_profile=user_profile,
                conversation_id=message['conversation_id'],
                message_id=message['message_id'],
                image_data=image_bytes
            ):
                if hasattr(chunk, 'text') and chunk.text:
                    full_response += chunk.text
            
            # 解析响应
            parsed_response = response_parser.parse_xml_response(full_response)
            
            # 保存AI响应消息
            chat_service = FlaskChatService()
            ai_round_num = message['round_num']  # AI响应使用相同轮次
            
            ai_msg = chat_service.add_message(
                conversation_id=message['conversation_id'],
                role='assistant',
                content=parsed_response.get('display_content', ''),
                round_num=ai_round_num,
                parsed_data=parsed_response,
                user_id=message['user_id']
            )
            
            # 更新用户消息状态为成功
            db_manager.update_message_status(message['message_id'], 'success')
            
            return jsonify({
                'success': True,
                'message': '重试成功',
                'ai_response': {
                    'message_id': ai_msg.get('message_id'),
                    'content': parsed_response.get('display_content', ''),
                    'conversation_id': message['conversation_id']
                }
            })
            
        except Exception as e:
            logger.error(f"模型调用失败: {str(e)}")
            # 更新消息状态为失败
            db_manager.update_message_status(message['message_id'], 'failed')
            return jsonify({'success': False, 'message': f'模型调用失败: {str(e)}'})
            
    except Exception as e:
        logger.error(f"重试处理失败: {str(e)}")
        return jsonify({'success': False, 'message': f'重试处理失败: {str(e)}'})

@app.route('/api/upload-image', methods=['POST'])
def upload_image():
    """处理图片上传"""
    try:
        # 检查用户身份
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': '用户未登录'})
        
        data = request.get_json()
        if not data or 'image_data' not in data:
            return jsonify({'success': False, 'message': '未收到图片数据'})
        
        image_data = data['image_data']
        image_type = data.get('image_type', 'webp')
        original_name = data.get('original_name', 'image')
        
        # 解析base64数据
        if ',' in image_data:
            header, base64_data = image_data.split(',', 1)
        else:
            base64_data = image_data
            header = f"data:image/{image_type};base64"
        
        # 解码图片数据
        try:
            image_bytes = base64.b64decode(base64_data)
        except Exception as e:
            return jsonify({'success': False, 'message': f'图片数据解码失败: {str(e)}'})
        
        # 使用存储管理器上传图片
        storage_manager = get_storage_manager()
        file_extension = image_type if image_type in ['webp', 'jpeg', 'jpg', 'png'] else 'webp'
        
        result = storage_manager.upload_image(image_bytes, str(user_id), file_extension)
        if not result:
            return jsonify({'success': False, 'message': '图片存储失败'})
        
        storage_path, access_url = result
        
        # 记录到数据库的文件信息
        file_info = {
            'file_id': storage_path.split('/')[-1].split('.')[0],  # 从路径提取UUID
            'filename': storage_path.split('/')[-1],  # 文件名
            'file_path': storage_path,  # 存储路径
            'access_url': access_url,  # 访问URL
            'original_name': original_name,
            'image_type': image_type,
            'file_size': len(image_bytes),
            'user_id': user_id,
            'created_at': datetime.now().isoformat()
        }
        
        logger.info(f"图片上传成功: {storage_path}, 大小: {len(image_bytes)} bytes, 用户: {user_id}")
        
        return jsonify({
            'success': True, 
            'message': '图片上传成功',
            'file_info': file_info
        })
        
    except Exception as e:
        logger.error(f"图片上传处理出错: {str(e)}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'})

@app.route('/temp_image_storage/<path:file_path>')
def get_temp_image(file_path):
    """提供临时图片访问 - 支持日期分层路径"""
    try:
        # 安全检查：防止路径遍历攻击
        if '..' in file_path or file_path.startswith('/') or '\\' in file_path:
            return "Invalid file path", 400
        
        # 使用存储管理器获取图片
        storage_manager = get_storage_manager()
        
        # 构造完整的存储路径
        storage_path = file_path  # 例如：2025/08/16/uuid.jpg
        
        # 获取图片数据
        image_data = storage_manager.get_image_data(storage_path)
        if not image_data:
            return "File not found", 404
        
        # 根据文件扩展名确定MIME类型
        file_extension = file_path.split('.')[-1].lower()
        mime_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'webp': 'image/webp',
            'gif': 'image/gif'
        }
        content_type = mime_types.get(file_extension, 'image/jpeg')
        
        # 返回图片数据
        from flask import Response
        return Response(image_data, mimetype=content_type)
        
    except Exception as e:
        logger.error(f"访问临时图片失败: {str(e)}")
        return "Server error", 500

@app.route('/health')
def health_check():
    """健康检查端点"""
    return {'status': 'healthy', 'timestamp': datetime.now().isoformat()}, 200

@app.route('/test-stream')
def test_stream():
    """极简流式传输测试接口"""
    import time
    import json
    
    def generate_simple_stream():
        print("-----> Starting simple stream test <-----")
        for i in range(1, 6):
            # 模拟AI思考，每次发送一个数据块
            message = f"这是第 {i} 个数据块..."
            print(f"Yielding: {message}")
            yield f"data: {json.dumps({'content': message})}\n\n"
            time.sleep(1) # 暂停1秒
        
        final_message = "流式传输结束！"
        print(f"Yielding: {final_message}")
        yield f"data: {json.dumps({'content': final_message, 'complete': True})}\n\n"
        print("-----> Simple stream test finished <-----")

    # 必须设置 'text/event-stream' mimetype
    return Response(generate_simple_stream(), mimetype='text/event-stream')

@app.route('/init-db', methods=['POST'])
def init_database():
    """初始化数据库的特殊端点（仅用于部署时）"""
    try:
        # 强制设置为生产环境
        os.environ['LOCAL_DEV'] = 'false'
        
        # 初始化数据库管理器（会自动创建表）
        db_manager = Config.get_database_manager()
        
        return jsonify({
            'status': 'success',
            'message': '数据库初始化成功',
            'tables': ['users', 'user_sessions', 'conversations', 'messages', 'api_requests', 'system_cache_status', 'question_metadata', 'user_profiles']
        }), 200
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'数据库初始化失败: {str(e)}'
        }), 500

if __name__ == '__main__':
    # 本地开发使用5000端口，生产环境通过gunicorn使用8080端口
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
