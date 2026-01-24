# Sovi Demo 部署指南

本文档提供完整的本地开发和 GCP 云端部署方案。

---

## 目录

1. [本地开发部署](#本地开发部署)
2. [Docker 本地运行](#docker-本地运行)
3. [GCP Cloud Run 部署](#gcp-cloud-run-部署)
4. [环境变量说明](#环境变量说明)
5. [常见问题排查](#常见问题排查)

---

## 本地开发部署

### 前置要求

- Python 3.10+
- pip 包管理器
- Google Gemini API Key（[获取地址](https://aistudio.google.com/apikey)）

### 步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd SoviDemo

# 2. 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 Windows:
# venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 GEMINI_API_KEY

# 5. 启动应用
python app.py
```

### 访问应用

打开浏览器访问: http://127.0.0.1:5000

本地开发模式会自动使用 SQLite 数据库（无需额外配置）。

---

## Docker 本地运行

### 构建镜像

```bash
docker build -t sovi-demo .
```

### 运行容器

```bash
docker run -p 5000:5000 \
  -e LOCAL_DEV=true \
  -e GEMINI_API_KEY=your_api_key_here \
  -e SECRET_KEY=your_secret_key_here \
  sovi-demo
```

### 使用 Docker Compose（推荐）

创建 `docker-compose.yml`：

```yaml
version: '3.8'
services:
  sovi-demo:
    build: .
    ports:
      - "5000:5000"
    environment:
      - LOCAL_DEV=true
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - SECRET_KEY=${SECRET_KEY}
    volumes:
      - ./data:/app/data  # 持久化数据库
```

运行：

```bash
docker-compose up -d
```

---

## GCP Cloud Run 部署

### 前置要求

- GCP 账户和项目
- 安装 [gcloud CLI](https://cloud.google.com/sdk/docs/install)
- 启用必要的 API

### 1. 初始化 GCP 环境

```powershell
# 设置变量（PowerShell）
$PROJECT_ID = "your-project-id"
$REGION = "asia-east1"
$REPO = "sovi-repo"
$IMAGE = "sovi-demo"
$TAG = (Get-Date -Format "yyyyMMdd-HHmmss")
$IMAGE_URI = "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/${IMAGE}:$TAG"

# 设置项目
gcloud config set project $PROJECT_ID

# 启用必要的 API
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### 2. 创建 Artifact Registry 仓库

```powershell
gcloud artifacts repositories create $REPO `
    --repository-format=docker `
    --location=$REGION `
    --description="Sovi demo images"

# 配置 Docker 认证
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
```

### 3. 构建并推送镜像

```powershell
# 本地构建
docker build -t $IMAGE_URI .

# 推送到 Artifact Registry
docker push $IMAGE_URI
```

### 4. 配置 Secret Manager（推荐）

```powershell
# 创建 Gemini API Key secret
echo -n "your-gemini-api-key" | gcloud secrets create gemini-api-key --data-file=-

# 创建数据库密码 secret
echo -n "your-db-password" | gcloud secrets create sovi-db-password --data-file=-

# 授予 Cloud Run 服务账号访问权限
$SERVICE_ACCOUNT = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding gemini-api-key `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/secretmanager.secretAccessor"
```

### 5. 创建 Cloud SQL 实例（可选）

```powershell
# 创建 PostgreSQL 实例
gcloud sql instances create sovi-db `
    --database-version=POSTGRES_14 `
    --tier=db-f1-micro `
    --region=$REGION

# 创建数据库
gcloud sql databases create sovi_data --instance=sovi-db

# 创建用户
gcloud sql users create manager `
    --instance=sovi-db `
    --password="your-secure-password"
```

### 6. 部署到 Cloud Run

```powershell
gcloud run deploy sovi-demo `
    --image $IMAGE_URI `
    --region $REGION `
    --platform managed `
    --allow-unauthenticated `
    --port 8080 `
    --memory 1Gi `
    --cpu 1 `
    --max-instances 10 `
    --concurrency 80 `
    --set-env-vars "LOCAL_DEV=false,PROJECT_ID=$PROJECT_ID" `
    --set-secrets "GEMINI_API_KEY=gemini-api-key:latest,DB_PASSWORD=sovi-db-password:latest" `
    --add-cloudsql-instances "$PROJECT_ID:$REGION:sovi-db"
```

### 7. 验证部署

```powershell
# 获取服务 URL
gcloud run services describe sovi-demo --region $REGION --format="value(status.url)"

# 查看日志
gcloud logs read --service=sovi-demo --region=$REGION --limit=50
```

---

## 环境变量说明

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `LOCAL_DEV` | 否 | `true` | 本地开发模式，使用 SQLite |
| `GEMINI_API_KEY` | 是 | - | Google Gemini API 密钥 |
| `SECRET_KEY` | 生产必需 | - | Flask 会话密钥 |
| `DATABASE_URL` | 生产可选 | - | 完整数据库 URL |
| `DB_HOST` | 生产可选 | - | PostgreSQL 主机 |
| `DB_PORT` | 否 | `5432` | PostgreSQL 端口 |
| `DB_NAME` | 否 | `sovi_data` | 数据库名称 |
| `DB_USER` | 生产必需 | - | 数据库用户名 |
| `DB_PASSWORD` | 生产必需 | - | 数据库密码 |
| `PROJECT_ID` | GCP | - | GCP 项目 ID |
| `USE_CLOUD_SQL_CONNECTOR` | GCP | `false` | 使用 Cloud SQL 连接器 |
| `INSTANCE_CONNECTION_NAME` | GCP | - | Cloud SQL 实例连接名 |

---

## 常见问题排查

### Q: 本地运行时数据库连接失败

确认 `.env` 文件中设置了 `LOCAL_DEV=true`，SQLite 数据库会自动创建。

### Q: Gemini API 调用失败

```bash
# 检查 API Key 是否正确配置
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('API Key:', bool(os.getenv('GEMINI_API_KEY')))"
```

### Q: Docker 容器无法启动

```bash
# 查看容器日志
docker logs <container-id>

# 检查端口占用
netstat -an | grep 5000
```

### Q: Cloud Run 部署失败

```powershell
# 查看详细构建日志
gcloud builds list --limit=5

# 查看 Cloud Run 服务状态
gcloud run services describe sovi-demo --region $REGION
```

### Q: 数据库迁移问题

本项目使用自动表创建，首次运行会自动初始化数据库结构。如需手动迁移：

```bash
# 连接到数据库执行 SQL
python -c "from infrastructure.db.db import DatabaseManager; db = DatabaseManager(); db.init_database()"
```

---

## 性能优化建议

### Cloud Run 配置

- **内存**: 推荐 1Gi，处理图片时可能需要更多
- **CPU**: 1 核足够日常使用
- **并发**: 80-100，根据实际负载调整
- **最小实例**: 设置 1 以减少冷启动

### 成本优化

- 使用系统提示缓存（默认启用）可节省 80% 输入 token 成本
- 设置合理的 `max-instances` 防止费用失控
- 使用 Artifact Registry 而非 Container Registry（更便宜）

---

## 安全建议

1. **生产环境必须设置 `SECRET_KEY`**
2. **使用 Secret Manager 管理敏感信息**
3. **启用 Cloud Run 的身份验证（如需要）**
4. **定期轮换 API 密钥和数据库密码**
5. **配置 VPC 网络隔离数据库访问**
