# 部署说明（本地 Docker 构建 → Cloud Run）

本项目不依赖 Cloud Build。推荐在本地构建镜像并推送到 Artifact Registry，然后部署到 Cloud Run。

注意：项目根目录下的 `Dockerfile` 为唯一构建入口（deploy 目录不再包含 Dockerfile）。

## 前置条件
- 已安装并登录 gcloud CLI 与 Docker（Windows 使用 PowerShell）
- 已在 GCP 中创建项目并具备相应权限
- 已启用以下 API：Cloud Run、Artifact Registry

## 一次性配置
1) 设置项目与区域（PowerShell 环境变量）
- 项目 ID、区域、仓库名、镜像名可自定义

2) 配置 Artifact Registry 登录
- 使用 gcloud 配置 Docker 登录目标区域的 Artifact Registry 注册表

3) 创建（或复用）Docker 仓库
- 若仓库不存在则创建

## 构建与推送
1) 本地构建镜像（根目录执行）
- 使用 Dockerfile 构建镜像并打上唯一 TAG（如时间戳）

2) 推送镜像到 Artifact Registry
- 推送成功后将获得完整的 IMAGE URI（IMAGE_URI）

## 部署到 Cloud Run（推荐参数）
- 服务名：sovi-demo（可自定义）
- 端口：8080（与容器暴露端口一致）
- 公开访问：--allow-unauthenticated（如需内网或鉴权可去掉）
- 环境变量：按需设置，如 LOCAL_DEV=false、GEMINI_API_KEY=...、数据库配置等

小贴士：
- 若使用 Cloud SQL，请根据需求设置 `USE_CLOUD_SQL_CONNECTOR`、`INSTANCE_CONNECTION_NAME`、`DB_*` 等变量
- 镜像命名规范：`<REGION>-docker.pkg.dev/<PROJECT_ID>/<REPO>/<IMAGE>:<TAG>`
- 若使用 GCS 存储图片，请设置 `USE_GCS_STORAGE=true` 与 `GCS_BUCKET_NAME`

## 回滚/灰度
- Cloud Run 支持基于修订版本快速回滚
- 可为两版修订分配流量比例做灰度

## 凭据与密钥
- 请勿将任何敏感文件提交到仓库
- `deploy/creds/` 目录已忽略，仅用于本地开发放置临时凭据

## 参考
- 详细命令与示例请参考主仓库 `README.md` 的“Cloud Run 部署（本地构建）”章节
