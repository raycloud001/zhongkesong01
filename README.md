# 求职天赋测评

仓库目前包含 FastAPI/React 运行基线、数据库迁移、匿名与管理员身份、正式 Q01–Q40 复合题测评、答案保存、事件记录和队列提交基础设施。完整报告生成、管理员知识库流程和正式发布仍未完成。魔搭文本与向量适配器已有配置入口；本项目尚未用真实外部模型或生产索引验证端到端报告。

## 安装与验证

需要 Python 3.11+ 和 Node.js 20+。以下命令都从仓库根目录执行：

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm ci --prefix frontend
.venv/bin/python -m pytest -c backend/pytest.ini backend/tests -q
npm run --prefix frontend build
```

先复制配置模板，再运行任何带 `--env-file` 的命令：

```sh
cp .env.example .env
```

把模板中的 `/absolute/path/to/zhongkesong` 替换为本机仓库的**一个绝对根目录**。本文统一使用这个绝对数据库地址：

```text
DATABASE_URL=sqlite:////absolute/path/to/zhongkesong/data/career_assessment.db
```

不要混用相对 SQLite 地址，也不要从不同工作目录分别运行迁移和服务。`uvicorn --env-file` 只为 Uvicorn 进程读取文件；Alembic 和管理员初始化不会自动读取 `.env`。因此先将 `.env` 导入当前 shell，再显式把同一个数据库地址传给迁移：

```sh
set -a
. ./.env
set +a
mkdir -p data
.venv/bin/python -m alembic -c backend/alembic.ini \
  -x database_url="$DATABASE_URL" upgrade head
```

`GET /health` 只表示服务进程存活，不能证明数据库已经初始化。必须先成功执行迁移，再创建身份、保存测评或初始化管理员。

迁移完成后，显式导入并激活仓库内的正式 evidence-only 题库；此命令不会自动运行，也不会自动启用演示题库：

```sh
.venv/bin/python scripts/import_official_evidence.py --database-url "$DATABASE_URL" --activate
```

如需管理员账号，在 `.env` 中填写私有的 `ADMIN_BOOTSTRAP_USERNAME` 和 `ADMIN_BOOTSTRAP_PASSWORD`，完成迁移后运行：

```sh
PYTHONPATH=backend .venv/bin/python -m app.auth.service bootstrap-admin
```

不要把真实密码提交到仓库。

## 推荐本地运行：构建后同源服务

此方式由 FastAPI 同时提供网页和 API，地址统一为 `http://localhost:7860`。本地 HTTP 使用：

```text
FRONTEND_ORIGIN=http://localhost:7860
APP_ENV=development
```

完成上面的迁移和可选管理员初始化后：

```sh
npm run --prefix frontend build
.venv/bin/python -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 7860
```

浏览器使用 `http://localhost:7860`。来源比较是精确的；`localhost` 与 `127.0.0.1` 属于不同来源，不要混用。

## 可选前端开发：Vite 5173

Vite 已将 `/api` 代理到 `http://127.0.0.1:8000`，并保留浏览器发出的 Origin，供后端执行真实的来源校验。开发配置应为：

```text
FRONTEND_ORIGIN=http://localhost:5173
APP_ENV=development
```

完成迁移后，在两个终端从仓库根目录运行：

```sh
set -a; . ./.env; set +a
.venv/bin/python -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8000 --reload
```

```sh
npm run --prefix frontend dev
```

访问 `http://localhost:5173`。`FRONTEND_ORIGIN` 只控制 CORS 和身份写操作的来源校验；实际转发由 Vite 代理完成。

## 魔搭接口配置

在本地 `.env` 或魔搭创空间 Secrets 中设置：

- `MODELSCOPE_BASE_URL`：兼容接口的基础地址，例如以 `/v1` 结尾的地址。
- `MODELSCOPE_API_KEY`：访问令牌，只能通过私有环境变量或 Secrets 注入。
- `MODELSCOPE_MODEL_NAME`：文本生成模型 ID。
- `MODELSCOPE_EMBEDDING_MODEL`：向量模型 ID。
- `MODELSCOPE_EMBEDDING_DIMENSION`：可选的预期向量维数，填写后会严格校验。

文本与远程向量能力可独立配置。缺少必需配置时，适配器会明确报告不可用。当前调用超时为 30 秒且不会自动重试；上游响应内容、用户输入和令牌不会进入公开异常信息。

## Docker 与魔搭创空间

本地 Docker 使用持久卷保存 SQLite 数据。`.env` 中为容器设置：

```text
DATABASE_URL=sqlite:////data/career_assessment.db
FRONTEND_ORIGIN=http://localhost:7860
APP_ENV=development
```

构建镜像，先用一次性容器显式迁移同一个卷，再启动服务：

```sh
mkdir -p data
docker build -t career-assessment .
docker run --rm --env-file .env -v "$(pwd)/data:/data" \
  career-assessment python -m alembic -c backend/alembic.ini \
  -x database_url=sqlite:////data/career_assessment.db upgrade head
docker run --rm -p 7860:7860 --env-file .env \
  -v "$(pwd)/data:/data" career-assessment
```

如需容器内初始化管理员，应在迁移之后，用同一个 `--env-file` 和数据卷运行 `python -m app.auth.service bootstrap-admin`。

公网部署必须使用实际 HTTPS 站点来源，例如：

```text
FRONTEND_ORIGIN=https://your-space-host.example
APP_ENV=production
```

`APP_ENV=production` 会启用 Secure 会话 Cookie，因此只能配合 HTTPS。魔搭创空间应将数据库放在持久卷或外部数据库中，并在启动应用前对同一个 `DATABASE_URL` 显式执行迁移。当前镜像不会自动迁移。通过 Secrets 注入密码和令牌，不要将真实值写入代码、镜像构建参数、截图或日志。
