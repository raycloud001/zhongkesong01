# 求职天赋测评技术实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在魔搭创空间交付可运行的三页面测评 MVP，支持专家规则与知识库管理，并生成可解释、可追溯的人才画像报告。

**Architecture:** React + FastAPI模块化单体；确定性规则计算证据、覆盖、资格、缺口、未知和冲突，AI只解释锁定判断。数值规则缺失时生成证据最小报告。

**Tech Stack:** React, TypeScript, Vite, Tailwind CSS, Zustand, React Hook Form, Zod, Recharts, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite, Chroma, Docker, 魔搭 AIGC/API Inference。

**Spec:** `技术架构设计.md`

**Business Inputs:** `题目与AI报告生成规则.md`（外部材料，规则副本已整理至 `backend/seed/sources/`）；唯一Q01—Q40已提供，数值锚点、分类器和策略阈值仍未完成。

## Global Constraints

- 部署到魔搭创空间，服务监听 `0.0.0.0:7860`，路演状态为 Running。
- API Key、Token、密码必须使用创空间 Secrets/环境变量，不得进入代码、README、截图或录屏。
- 固定40题；题目、规则、知识库和报告均需版本化，历史报告不可被新版本覆盖。
- 规则负责证据、去重、覆盖、资格和缺口；AI只负责候选提取、解释和行动建议。不得补造分数、分类器或策略阈值。
- 未知值使用 `null`，前端显示“待验证/证据不足”，不得补造分数。
- 报告输出必须区分事实、推断、建议、待验证，并保存引用证据。

---

## 执行约定与依赖

按 Task 1–13 顺序执行。每个任务的执行包必须包含该任务全文、Global Constraints、指定的契约章节；禁止只提取检查框。公共契约：`docs/superpowers/specs/2026-09-12-career-contracts.md`，所有接口前缀为 `/api/v1`。任务中的文件路径均相对仓库根目录。

Task 1仅建立可测试基础和无数据库平台探针；Task 2建立数据库、任务存储与契约；Task 3实现真实身份；Task 4导入专家内容；Task 5提交到已存在的持久任务队列；Task 9才实现消费任务的AI工作循环。Task 5测试使用数据库中的queued任务，不依赖未来AI实现。所有模型调用测试用注入的假提供器，生产实现不得用测试夹具代替真实结果。

唯一正式Q01—Q40已作为`evidence_only`资产提供。数值锚点缺失只禁止数值分数、雷达、类型分类和自动策略档位，不阻断可追溯的非合成证据最小报告；合成夹具仍须清楚标记为demo。外部账户/存储未验证不等于技术不可实现，也不能声称正式上线验收完成。开发执行时先检查 Git 状态；若尚无 Git 仓库先初始化并建立开发分支，再按用户已选择的子代理流程实施与审查。本次文档修订不创建仓库、不部署。

### Task 1: 项目骨架与运行基线

**Files:** 创建 `frontend/`、`backend/`、`Dockerfile`、`.env.example`、`README.md`、对应测试目录。

- [ ] 初始化前端 Vite TypeScript 工程和后端 FastAPI 工程。
- [ ] 配置前端构建、后端健康检查 `/health`、CORS、结构化请求日志、`requestId` 和统一错误响应。
- [ ] 定义 OpenAPI 路由前缀 `/api/v1`、错误码和会话凭证策略；公开报告不得依赖前端路由保护。
- [ ] 配置 Docker 在 7860 端口启动服务，加入最小依赖和环境变量读取。
- [ ] 编写前后端启动与健康检查测试。
- [ ] 提交：`chore: scaffold assessment application`

创建 `backend/app/ai/provider.py`、`backend/tests/test_provider_capabilities.py`。先定义 `embed(texts: list[str]) -> list[list[float]]` 和 `generate_report(payload: dict) -> dict`，后续任务消费同一适配器。实测中文文本生成、Embedding维数、额度/限流以及创空间重启/重新部署持久化。无持久卷则在正式数据写入前选择外部 PostgreSQL，索引从版本化原文重建。

本任务的身份部分仅定义接口，真实会话及权限实现全部由Task 3负责。平台探针不依赖业务库，可在临时目录写入标识并验证重启结果。

**Interfaces:** 产出 create_app() -> FastAPI（仅health和静态页）；TextProvider.generate_report(payload: dict) -> dict、EmbeddingProvider.embed(texts: list[str]) -> list[list[float]]。不实现持久身份。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

**关键测试文件：** `backend/tests/test_health.py`

```python
from fastapi.testclient import TestClient
from app.main import create_app

def test_health():
    assert TestClient(create_app()).get("/health").json() == {"status": "ok"}
```

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 2: 数据模型、迁移与版本快照

**Files:** `backend/app/models/`、`backend/app/db/`、`backend/tests/test_models.py`。

- [ ] 建立 User、AssessmentSession、AssessmentAnswer、QuestionVersion、RuleVersion、KnowledgeDocument、KnowledgeChunk、KnowledgeIndexVersion、ReportVersion、EvidenceItem、JobMatch、ActionItem、FeedbackEvent、AdminUser、AuditLog 模型。
- [ ] 为 ReportVersion 保存 `questionVersion`、`ruleVersion`、`knowledgeIndexVersion`、`modelName`、`promptVersion`、`inputHash`、`reviewStatus`。
- [ ] 增加 ReportGenerationJob、PromptTemplateVersion、JobTemplateVersion、ProfileReview、ReportChatSession、ReportChatMessage、ConversationFact、ProfileSnapshot。
- [ ] 建立当前生效指针唯一约束、答案会话题目唯一约束、报告归属约束、事务和状态迁移约束。
- [ ] 完成 Alembic 初始迁移和 SQLite 测试数据库 fixture。
- [ ] 测试历史报告引用版本且不能被发布操作覆盖。
- [ ] 提交：`feat: add versioned assessment data model`

创建 `backend/app/contracts/report.py`、`backend/app/contracts/errors.py`、`backend/app/models/generation.py`、`backend/app/models/profile.py`。导出 OpenAPI 后生成 `frontend/src/api/schema.ts`，业务组件不能手写另一套同名类型。

Report保留版本、状态、证据、行动与解释分区；`radar`和百分比可为null。`jobMatches`为0—3个，`explicitTargets`另列最多3个。目标类型迁移见Task 4c，已完成Task 2的历史实现不代表新契约已经落地。

目标JobMatch保存资格、策略状态、任务覆盖、证据状态、缺口、风险、验证任务和行业上下文；资格与冲稳保策略不得共用字段。岗位模板固定版本，趋势判断带来源日期。

生成任务字段：`id, ownerId, assessmentId, inputHash, sourceVersions, status, attemptCount, leaseUntil, availableAt, errorCode, reportId`。状态 queued→running→ready/failed；超时租约可重排队，使用租约所有权校验拒绝过期工作者写入；重试最多3次，认证/结构错误不无限重试。持久化报告和任务ready在同一事务，重复完成由唯一约束阻止。本人复核状态独立为 pending/confirmed/disputed。

题目版本在创建会话时固定；规则、岗位、知识库、Prompt、模型在提交事务内固定。任务只读快照。草稿答案携带 revision，旧revision返回409，不覆盖新答案；已提交会话不可改写。

**Interfaces:** 产出 SQLAlchemy Base、get_db()、enqueue_job(db, owner_id: str, snapshot: dict) -> str；契约文件中的对象在此转为Pydantic模型并导出OpenAPI/TypeScript。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

**关键测试文件：** `backend/tests/test_contracts.py`

```python
from app.contracts.report import Score
from pydantic import TypeAdapter, ValidationError
import pytest

def test_unknown_and_bounds():
    adapter = TypeAdapter(Score)
    assert adapter.validate_python(None) is None
    with pytest.raises(ValidationError):
        adapter.validate_python(101)
```

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 3: 身份、授权与会话生命周期

**Files:** `backend/app/auth/service.py`、`backend/app/auth/routes.py`、`backend/tests/test_auth.py`。

数据库依赖Task 2。管理员首次账号由私有环境配置初始化，密码哈希存储；Cookie采用HttpOnly、生产Secure、SameSite=Lax。匿名owner独立于测评session，创建第二次测评不能替换owner。写操作验证CSRF；登录限流；会话默认有效30天，注销使凭证失效且前端清除本机缓存。管理员用户会话分开；报告、任务、答案、档案、对话均验证owner。

- [ ] 建立匿名owner获取/恢复、管理员登录、登出、当前身份接口。
- [ ] 覆盖A用户读取B资源404、未登录管理401、CSRF失败403、注销后会话失效。

**Interfaces:** 消费get_db；产出 require_owner(request) -> str、require_admin(request) -> str；业务路由通过依赖注入使用。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 4: 业务输入、范围冻结与种子数据

**Files:** `backend/seed/`、`docs/`、`backend/tests/test_seed.py`。

- [ ] 提供唯一Q01—Q40 JSON与复合题结构；记录数值锚点、分类器和阈值仍缺失。
- [ ] 提供岗位模板（职责、硬门槛、能力、场景、行业趋势、约束）和脱敏演示答案。
- [ ] 明确首期仅支持“理解报告”受限问答；确认后生成 ProfileSnapshot，支持报告详情查看与下次生成读取；开放式陪伴后移。
- [ ] 校验题目ID唯一、总数40、复合字段和证据映射；无已发布数值方法时禁用数值输出，不把正式`evidence_only`题表降格为演示数据。
- [ ] 提交：`docs: freeze assessment business inputs`

**Interfaces:** 消费数据库与契约；产出 validate_seed(payload: dict) -> list[str]、import_seed(db, payload: dict, mode: str) -> str。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

**关键测试文件：** `backend/tests/test_seed.py`

```python
from app.seed.service import validate_seed

def test_incomplete_seed():
    assert "QUESTION_COUNT" in validate_seed({"questions": []})
```

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 5: 40题测评、草稿保存与提交

**Files:** `backend/app/assessment/`、`frontend/src/features/assessment/`、`backend/tests/test_assessment.py`、`frontend/src/features/assessment/*.test.tsx`。

- [ ] 实现题目版本读取、会话创建、答案保存、进度查询和提交锁定 API。
- [ ] 提供单选、多选、Q39可选及Q25/Q30/Q31/Q36/Q37/Q38复合输入；刷新后恢复答案。
- [ ] 按required与复合字段校验提交，使用幂等键防止重复提交。
- [ ] 埋点 `assessment_start`、`question_view`、`question_answer`、`question_back`、`assessment_save`、`assessment_exit`、`assessment_submit`。
- [ ] 测试断网重试不清空答案、未完成不能提交、提交后答案不可覆盖。
- [ ] 提交：`feat: implement assessment flow`

**Interfaces:** 消费require_owner/get_db/enqueue_job；产出 submit_assessment(db, owner_id: str, session_id: str, key: str) -> str。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 4b: 正式题表资产（已审查范围）

- [x] 生成唯一Q01—Q40本地资产，保留来源哈希/行号、Q39可跳过和复合题子字段；不发布数据库指针，不补造数值方法。

### Task 4c: 目标契约与正式规则发布迁移

- [ ] 将逐项任务/能力/要求比较、硬门槛、五维迁移、岗位来源和方法引用迁移到Pydantic、TypeScript、数据库与种子发布契约。
- [ ] 迁移现有JobMatch ORM的旧必填列（match_status、evidence_sufficiency、current_basis等），使其与新JSON契约一致；如采用版本化payload兼容，必须保留旧记录可读并用迁移测试证明。
- [ ] 发布正式`evidence_only`题目版本及已定义的确定性证据方法配置；本任务只验证/导入配置，Task 6才执行计算。无数值方法时保持雷达/类型/策略为空，不阻断证据报告。
- [ ] Task 5b、Task 6和Task 9依赖本任务；Task 4b完成不代表本迁移完成。

### Task 5b: 复合答题与手工证据采集

**依赖：** Task 4c。

- [x] 渲染、保存、恢复和校验复合输入及可选Q39；手工经历为MVP证据入口。Task 5b经两轮修复及独立复审通过，正式入口仅使用evidence_only，提交到持久队列；报告生成未包含。
- [ ] 文件/简历上传和语音转写为新增待办，不宣称本阶段实现。

### Task 6: 证据规则、资格与岗位比较

**依赖：** Task 4c。

**Files:** `backend/app/scoring/`、`backend/app/matching/`、`backend/tests/test_scoring.py`、`backend/tests/test_matching.py`。

- [ ] 按fact_key/claim_hash去重并保留冲突组；区分核验、自述、行为、倾向、缺失、冲突和迁移待验证。
- [ ] 任务覆盖按唯一核心task计数，分母0返回null；当前推荐0—3个，明确目标另列最多3个。
- [ ] 输出`current|explore|clarify|exclude`资格；策略另存，方法未核实时`strategyLabel=null`,`strategyStatus=pending_method`。
- [ ] 逐项输出task/capability/requirement/evidence对应、硬门槛状态及岗位来源；方法建议引用固定method_id、版本和位置。
- [ ] 比较核心任务、行业知识/资格、硬技能、服务群体链路、职责/环境五维迁移；按unknown→high→medium→low优先序判定。缺JD只能暂定比较且难度为unknown。
- [ ] 所有未知分数使用 `null`；每条结论绑定 evidenceIds。
- [ ] 测试Q07/Q40、Q30、去重、冲突、分母0、0个推荐及固定输入可复现。
- [ ] 提交：`feat: add deterministic scoring and job matching`

**Interfaces:** 消费已确认配置；产出 score_answers(answers: list[dict], rule: dict) -> dict、match_jobs(core: dict, templates: list[dict]) -> list[dict]。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

**关键测试文件：** `backend/tests/test_scoring.py`

```python
from app.scoring.service import score_answers

def test_unknown_is_not_zero():
    rule = {"dimensions": [{"id": "communication", "items": []}]}
    result = score_answers([], rule)
    assert result["radar"] is None
```

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 7: 管理员规则与题目版本后台

**Files:** `backend/app/admin/`、`frontend/src/pages/admin/RulesPage.tsx`、`frontend/src/pages/admin/QuestionsPage.tsx`、相关测试。

- [ ] 实现管理员会话、规则/题目草稿编辑、发布、回滚 API。
- [ ] 发布时校验题目40题唯一、ID完整、复合字段和证据引用；仅当版本声明数值评分时校验权重/锚点。禁止执行任意脚本。
- [ ] 保存操作人、时间、变更原因到 AuditLog。
- [ ] 测试发布原子性、回滚和历史报告不变。
- [ ] 提交：`feat: add admin rule and question versioning`

规则管理任务新增 `frontend/src/pages/admin/ReportConfigPage.tsx`、`backend/app/admin/config.py`：编辑专家解释原则和Prompt草稿，选择兼容规则/模型/索引，预览后发布。知识管理任务新增 `frontend/src/pages/admin/KnowledgePage.tsx`、`backend/app/knowledge/publish.py`：正文编辑、来源/日期维护、草稿审核、重建索引、发布和回滚。实时指发布成功后无需重新部署即对新任务生效；已有任务和报告不变。

知识版本 draft→indexing→ready→published，失败保持旧版生效。只在新索引验证成功后切换指针。六类方法论的基础行为约束固定进入生成配置，不能依赖Top-K恰巧召回；案例与行业材料再按需检索。无相关来源时返回不足信息，不生成趋势断言。

**Interfaces:** 消费require_admin和版本表；产出 publish_version(db, resource: str, version_id: str, expected_revision: int) -> str。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 8: 模型能力验证与知识库导入、索引与检索

**Files:** `backend/app/ai/`、`backend/app/knowledge/`、`backend/tests/test_provider_capabilities.py`、`backend/tests/test_knowledge.py`、管理端知识库页面。

- [ ] 消费 Task 1 离线验证过接口边界的文本/Embedding适配器并保存账户级能力矩阵；真实调用未验证时不得宣称真实AI生成，但可明确标记`generationMode=rule_template`生成正式证据最小报告。
- [ ] 支持 Markdown/TXT 上传、标题/分类/来源编辑、启用停用和版本化。
- [ ] 保存文档 checksum、解析状态/失败原因、敏感内容人工审核状态；营销文案、图片和未读取外链默认不进入可引用语料。
- [ ] 按标题和段落切分，生成 Chroma 持久化索引；记录 documentId、chunkId、来源和更新时间。
- [ ] 实现六类方法论标签过滤 + 向量 Top-K 检索，默认召回6个片段。
- [ ] 索引构建失败时保留旧索引；重建时不混用不同 Embedding 模型。
- [ ] 测试来源追踪、索引切换、旧版本回滚和无关片段过滤。
- [ ] 提交：`feat: add versioned knowledge base retrieval`

规则管理任务新增 `frontend/src/pages/admin/ReportConfigPage.tsx`、`backend/app/admin/config.py`：编辑专家解释原则和Prompt草稿，选择兼容规则/模型/索引，预览后发布。知识管理任务新增 `frontend/src/pages/admin/KnowledgePage.tsx`、`backend/app/knowledge/publish.py`：正文编辑、来源/日期维护、草稿审核、重建索引、发布和回滚。实时指发布成功后无需重新部署即对新任务生效；已有任务和报告不变。

知识版本 draft→indexing→ready→published，失败保持旧版生效。只在新索引验证成功后切换指针。六类方法论的基础行为约束固定进入生成配置，不能依赖Top-K恰巧召回；案例与行业材料再按需检索。无相关来源时返回不足信息，不生成趋势断言。

**Interfaces:** 消费EmbeddingProvider；产出 retrieve(index_version_id: str, query: str, tags: list[str], limit: int=6) -> list[dict]。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 9: 规则与报告契约、魔搭 AI 适配器与结构化报告生成

**依赖：** Task 4c。

**Files:** `backend/app/ai/`、`backend/app/reports/`、`backend/tests/test_report_generation.py`。

- [ ] 消费Task 4c迁移后的Report Schema：证据、资格、覆盖、0—3推荐、明确目标、差距、行动、追踪、AI说明和复核；数值字段仅在数值规则已发布时出现。
- [ ] 消费Task 1提供的独立文本生成和Embedding接口，端点、模型和 Key 由环境变量配置。
- [ ] 组合冻结输入、规则判断、证据、岗位约束、可用知识片段、Prompt版本和JSON Schema。
- [ ] 使用 Pydantic 校验输出，检查 evidenceIds、knowledgeEvidenceIds、`null` 未知值和事实/推断/建议/待验证字段；拒绝无依据的分数、Offer/绩效承诺和把知识库内容当作用户证据。
- [ ] 用户答案和检索文本按不可信资料处理，已发布白名单规则作为业务约束；Prompt 注入不能改变系统规则、权限或版本选择。
- [ ] AI生成/校验失败只重试一次，仍失败用规则模板；队列租约最多3 attempt，分开记录。知识库不可用时明确降级。
- [ ] 测试模型不可用时保留结构化证据判断，不能伪造分数或报告；固定脱敏样例验证引用完整性。
- [ ] 提交：`feat: integrate ModelScope report generation`

**Interfaces:** 消费score_answers/match_jobs/retrieve/TextProvider及持久job；产出 run_once(db, provider, retriever) -> bool；实现分区生成，不重复实现provider。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 10: 报告读取、复核、反馈和任务重试API

**Files:** `backend/app/reports/routes.py`、`backend/app/feedback/routes.py`、`backend/tests/test_report_api.py`。

依赖Task 2/3/9。GET报告按契约返回就绪分区，包括失败时保留下来的core；复核和准确性反馈分别保存。复核确认不能更改结论，失败反馈可用clientEventId幂等重发。手动重试仅重试失败分区，沿用sourceVersions、profileSnapshotId和答案快照，不重新读取当前档案。

- [ ] 实现报告获取、分区读取、复核、反馈列表/提交与job重试。
- [ ] 保护归属；重复反馈返回原记录；已就绪任务重试409；版本变化不污染重试。

**Interfaces:** 消费require_owner与持久报告/job；产出契约列出的reports/feedback/retry端点。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 11: 受限报告问答、候选事实确认与最小档案

**Files:** `backend/app/chat/service.py`、`backend/app/chat/routes.py`、`backend/app/profile/service.py`、`backend/app/profile/routes.py`、`backend/tests/test_profile.py`、`backend/tests/test_chat.py`。

依赖Task 2/3/9/10。读取报告、岗位上下文、当前已确认事实和未完成行动，只做报告理解与下一步建议，不提供开放工具调用。AI按契约输出事实/推断/建议/待验证四类内容，每条有来源。新输入抽取为candidate，确认前不入档。报告core就绪时生成初始ProfileSnapshot，包含完整报告引用；新确认事实创建新快照。用户更正/撤回事实形成新快照并保留历史，拒绝候选不改变档案。多次确认clientDecisionId幂等。更正并发使用expectedSnapshotId冲突返回409。报告生成读取的是提交时固定的档案，不读取后续快照。

- [ ] 实现对话历史、发消息、事实确认/拒绝、更正/撤回、档案当前与历史接口。
- [ ] 输出完整版报告与确认事实的聚合视图；禁止把未确认推断写成档案事实。

**Interfaces:** 消费require_owner、TextProvider、持久报告与档案；产出 build_profile_context(db, snapshot_id: str | None) -> dict。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 12: 三页面结果展示、反馈与分享

**Files:** `frontend/src/pages/`、`frontend/src/features/report/`、`frontend/src/features/feedback/`、E2E 测试。

- [ ] 完成首页、答题页、结果页及响应式黑紫设计令牌；答题闭环由Task 5交付，本任务只集成UI。
- [ ] 展示证据、0—3个当前方向、最多3个明确目标、缺口、行动和反馈；仅有数值规则时展示雷达/百分比。
- [ ] 调用Task 10提供的报告读取、本人复核、反馈提交/查询、生成重试 API；T+7/T+30/T+90 仅为 preview，30/60/90 为行动计划。
- [ ] 长解释按四段结构化展示；生成中分区加载；待验证状态可见。
- [ ] 分享卡读取有依据的白名单字段；无数值规则时不含雷达或适配百分比。
- [ ] 测试1440/1024/320宽度无横向溢出，完整链路可走通。
- [ ] 提交：`feat: build assessment and report experience`

前端只负责渲染 Task 11 提供的报告问答、候选事实确认和最小档案数据；不在此任务实现档案写入或对话业务逻辑。

实现结果页全部埋点：result_page_view、radar_dimension_select、evidence_open、job_tier_switch、job_match_expand、validation_task_click、tracking_reminder_click、accuracy_feedback_submit、long_interpretation_expand、share_card_generate、share_card_confirm、report_export；生成成功/失败分别记录assessment_generate_success/failure。埋点只携带ID和状态，不记录自由文本答案。

完整报告导出采用打印样式和浏览器保存PDF；分享为独立白名单PNG，不生成公开完整报告链接。示例固定显示“演示数据”，不进入真实会话；分享失败、反馈失败保留输入。支持键盘焦点、减少动态、未知雷达轴不画成0分、证据等级文字提示。T+7/T+30/T+90为preview；30/60/90为行动内容，均不承诺自动通知。

**Interfaces:** 消费 Task 2 从共享契约生成的 `frontend/src/api/schema.ts` 与 Task 3/5/10/11 API；产出首页/答题/报告集成界面，无新增业务API。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。

### Task 13: 魔搭部署、验收与过程证据

**Files:** `Dockerfile`、`README.md`、部署配置、`docs/`。

- [ ] 在创空间配置 Secrets，验证 Build/Run 日志和 `Running` 状态。
- [ ] 验证 SQLite/Chroma 重启和重新部署持久化；不满足时切换外部 PostgreSQL/对象存储。
- [ ] 用两份脱敏数据完成对照演示，记录规则、知识库、验证和迭代航迹。
- [ ] 检查未登录访问、核心链路、重启持久化、密钥扫描、分享敏感字段过滤。
- [ ] 运行后端 pytest、前端 Vitest、Playwright E2E 并记录结果。
- [ ] 提交：`docs: add deployment and demo verification evidence`

**Interfaces:** 消费可构建服务、Docker、验收命令；产出部署地址及真实测试记录，未验证不得标记Running。

**契约输入：** `docs/superpowers/specs/2026-09-12-career-contracts.md`；执行者必须一并读取。

- [ ] 将本任务关键测试与契约验收案例写入指定测试文件。
- [ ] 先运行任务测试，确认因缺少本任务能力失败，排除环境错误。
- [ ] 按本任务接口实现最小行为，重复运行同一测试，要求全部通过。
- [ ] 审查规格符合性与质量后提交本任务文件；未获通过不进入下一任务。
