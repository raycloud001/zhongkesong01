# Career Assessment Shared Contracts

## Runtime
- API prefix: `/api/v1`.
- Public service listens on `0.0.0.0:7860`.
- All IDs are opaque strings; all timestamps are ISO-8601 UTC.
- Error body: `{ "error": { "code": string, "message": string, "requestId": string, "details": object } }`.

## Ownership and versions
- Every user resource carries `ownerId`; unauthorized access returns 404.
- A submitted assessment fixes `questionVersion`, `ruleVersion`, `jobTemplateVersion`, `knowledgeIndexVersion`, `promptVersion`, `modelName`, and `profileSnapshotId`.
- A published version is immutable. A current-pointer change affects new tasks only.

## Report contract
- **规范变更状态：** 本节已按《题目与AI报告生成规则》更新，但当前Pydantic/TypeScript、数据库列和前端仍待迁移；旧生成类型不得作为新实现依据。
- Report `status`: `generating|partial|ready|failed`; `reviewStatus`: `pending|confirmed|disputed`. A report with only core is `partial`; no usable part is `failed`.
- 数值雷达和适配百分比可选；没有已发布数值规则时为`null`，不得用0代替未知。
- `jobMatches`为0—3个；用户明确目标另列`explicitTargets`且最多3个，不得凑满。
- `longInterpretation.sections` is exactly four named sections: `core_judgment`, `job_impact`, `uncertainty`, `validation`.
- Every generated claim has `claimType` (`fact|inference|recommendation|to_validate`) and either `evidenceIds` or `knowledgeEvidenceIds` as appropriate.
- `tracking.status` is `preview|scheduled|completed`; MVP always uses `preview`.

## Jobs and idempotency
- Generation job status: `queued|running|ready|failed`.
- A job has `inputHash`, `sourceVersions`, `profileSnapshotId`, `attemptCount`, `leaseUntil`, `availableAt`, `errorCode`, and optional `reportId`.
- Submit/retry/feedback/chat decisions accept an idempotency key; duplicate keys return the first result.
- 单次AI生成/校验失败只重试一次，仍失败用规则模板；队列租约故障的`attemptCount`最多3，两个计数不可混用。知识库不可用时明确降级，有个人证据仍可生成最小报告。

## Profile and restricted chat
- Chat is report-understanding only and receives current report, confirmed profile facts, and current question.
- Candidate facts are `candidate|confirmed|rejected`; only confirmed facts enter a new `ProfileSnapshot`.
- Confirming, rejecting, retracting, or correcting a fact is idempotent and preserves prior snapshots.

## 完整领域类型（取代上方简述中的 Report.status）

以下TypeScript为目标规范表达，尚待代码迁移：除`?`字段外均必填；null表示未知，空数组表示已计算且没有条目。领域对象不可直接用模型输出覆盖。

```typescript
type ID = string;
type Score = number | null;
type Kind = 'fact'|'inference'|'recommendation'|'to_validate';
type Phase = 'pending'|'running'|'ready'|'failed';
type Ref = { source: 'answer'|'knowledge'|'report'|'profile'|'job_source'|'method';
  id: ID; version: ID; location: string|null };
type Claim = { id: ID; text: string; claimType: Kind; references: Ref[] };
type Evidence = { id: ID; questionId: ID|null; answerId: ID|null; quote: string;
  taskIds: ID[]; sourceStatus: 'verified_result'|'confirmed_self_report'|'behavior'|'preference'|'missing'|'conflict';
  verificationSource: string|null; gaps: string[]; conflictGroupId: ID|null };
type Dimension = { id: ID; name: string; score: Score; description: string; evidenceIds: ID[] };
type Versions = { questionVersion: ID; ruleVersion: ID; jobTemplateVersion: ID;
  knowledgeIndexVersion: ID; promptVersion: ID; modelName: string;
  embeddingModelVersion: string; profileSnapshotId: ID|null };
type Action = { id: ID; title: string; reason: Claim; firstStep: string;
  methodReferences: Ref[]; status: 'pending'|'completed' };
type RequirementComparison = { requirementId: ID; taskId: ID; capabilityId: ID;
  requirementType: 'hard_gate'|'core'|'bonus'; requiredLevel: 'L0'|'L1'|'L2'|'L3'|'unknown';
  observedLevel: 'L0'|'L1'|'L2'|'L3'|'unknown';
  judgmentStatus: 'supported'|'self_report_pending'|'transfer_pending'|'gap'|'unknown'|'conflict';
  evidenceIds: ID[]; requirementSource: Ref };
type HardGate = { requirementId: ID; status: 'met'|'missing'|'unknown'|'conflict';
  evidenceIds: ID[]; source: Ref };
type TransferDimension = { key: 'core_task'|'industry_qualification'|'hard_skill'|'service_chain'|'responsibility_environment';
  status: 'reusable'|'validate_in_context'|'training_needed'|'unknown'|'conflict';
  evidenceIds: ID[]; requirementIds: ID[]; references: Ref[] };
type Transfer = { level: 'low'|'medium'|'high'|'unknown'; provisional: boolean;
  dimensions: TransferDimension[]; reason: Claim };
type JobMatch = { id: ID; name: string; jobSourceId: ID|null; jobVersion: ID|null;
  sourceStatus: 'verified'|'template_provisional'|'unknown'; tasks: {id:ID; name:string}[];
  eligibility: 'current'|'explore'|'clarify'|'exclude';
  strategyLabel: 'steady'|'stretch'|'safe'|null;
  strategyStatus: 'ready'|'pending_method';
  taskCoverage: {behavior: number|null; verified: number|null};
  evidenceStatus: 'supported'|'self_report_pending'|'transfer_pending'|'gap'|'unknown'|'conflict';
  requirementComparisons: RequirementComparison[]; hardGates: HardGate[]; transfer: Transfer;
  reason: Claim; evidenceIds: ID[]; gaps: string[]; risks: Claim[];
  validationTask: Action; industryContext: {point: Claim; line: Claim; plane: Claim; system: Claim;
    asOf: string|null; references: Ref[]} };
type Core = { type: {id: ID; name: string; summary: Claim}|null;
  keySummaries: {state: Claim; advantage: Claim; risk: Claim};
  radar: {dimensions: Dimension[]; scale: [0,100]}|null; evidence: Evidence[];
  strengths: {dimensionId: ID; score: Score; evidenceIds: ID[]; application: string}[];
  weaknesses: Claim[]; risk: Claim|null; judgments: Claim[] };
type Decisions = { jobMatches: JobMatch[]; explicitTargets: JobMatch[]; preferredDirection: Claim|null;
  alternativeDirection: Claim|null; actions: Action[];
  actionPlan: {day: 30|60|90; actionIds: ID[]; deliverable: string}[];
  preparationSuggestions: Claim[]; counterEvidenceConditions: Claim[] };
type Interpretation = { sections: {key: 'core_judgment'|'job_impact'|'uncertainty'|'validation'; claims: Claim[]}[];
  aiUsageNotice: string; reviewItems: string[] };
type Part<T> = { status: Phase; data: T|null; errorCode: string|null };
type Report = { id: ID; assessmentId: ID; version: number; demo: boolean;
  status: 'generating'|'partial'|'ready'|'failed'; reviewStatus: 'pending'|'confirmed'|'disputed';
  sourceVersions: Versions; inputHash: string; createdAt: string;
  core: Part<Core>; decisions: Part<Decisions>; interpretation: Part<Interpretation>;
  tracking: {status: 'preview'; nodes: {day: 7|30|90; label: string}[]} };
type Job = {id: ID; status: 'queued'|'running'|'ready'|'failed';
  stage: 'validate'|'score'|'retrieve'|'generate'|'complete'; reportId: ID|null;
  completedParts: ('core'|'decisions'|'interpretation')[];
  failedParts: string[]; retryable: boolean; attemptCount: number; errorCode: string|null};
type Fact = {factId: ID; content: string; sourceMessageId: ID;
  status: 'candidate'|'confirmed'|'rejected'|'retracted'; createdAt: string;
  targetProfileField: 'goal'|'preference'|'experience'|'feedback'};
type ChatReply = {messageId: ID; conclusion: Claim;
  facts: Claim[]; inferences: Claim[]; recommendations: Claim[]; toValidate: Claim[];
  factCandidates: Fact[]; createdAt: string};
type Snapshot = {id: ID; previousId: ID|null; createdAt: string;
  reportIds: ID[]; confirmedFacts: Fact[]; changeReason: string};
```

证据台账由core.judgments及Ref关联core.evidence生成；不重复维护一份易失同步的证据表。知识Ref必须引用固定索引版本中的有效chunk；方法引用使用`source='method'`并以`id=method_id`、`version`和`location`定位已审阅方法条目；岗位要求引用使用`source='job_source'`定位`job_source_id/job_version`及原文位置。answer Ref必须属于当前作答；profile Ref必须属于sourceVersions.profileSnapshotId。用户自述不自动标记verified。报告先展示core待复核内容，用户看到内容后才能确认；partial仅能记录disputed，完整ready才允许confirmed。

迁移难度固定比较五维：核心任务、行业知识/资格、硬技能、服务群体链路、职责/环境。判定优先序为：关键冲突、目标要求未知或核心任务证据未知→`unknown`；信息足够且硬门槛缺失或核心任务需新增训练→`high`；不存在前述情况但需要场景验证→`medium`；全部核心任务可复用且硬门槛满足→`low`。缺少具体JD时可用模板形成`provisional=true`的暂定逐项比较，但`level`必须为`unknown`，不得输出确定难度。

## 分区持久化与快照事务

1. 提交在数据库事务内锁定会话，读取当前有效ProfileSnapshot ID（初次为null）、答案及所有发布指针，保存不可变输入快照并enqueue_job。inputHash包括规范化输入和所有版本ID；幂等键以owner+session为范围，不同键也不能重复提交已锁定会话。
2. Worker先创建Report ID并保存core，GET jobs立即提供reportId及completedParts=['core']。其余字段以Part.pending返回，不补造内容。随后检索、生成decisions和interpretation，各分区单独校验并提交。
3. 全部ready才将job置ready；有core且其他分区失败时Report.status=partial、job.status=failed。尚无任何有效分区时Report.status=failed。前端每2秒轮询job，展示可用分区与单区重试入口。
4. 任务存储包含leaseOwner和leaseToken递增值，写回条件必须匹配当前token。自动重试总尝试次数最多3；手动重试新建attempt记录，复用相同输入快照，保留ready分区；相同Idempotency-Key不增加attempt。
5. 提交后用户确认新事实生成新档案，不改变本任务profileSnapshotId。初始档案在core发布时创建；完整报告仍按同一reportId可读取。后续人工更正不覆盖旧报告。
6. 档案更新后可用原冻结答案、新ProfileSnapshot和固定版本创建新的可复现任务，无需重答；旧报告与旧快照保持不变。

## 路由与请求响应（全部列入所属任务）

统一分页 `{items: T[], nextCursor: string|null}`，limit默认20最大100。所有用户端返回仅限当前owner。数组或详情必须遵循以上类型。

| 任务 | 方法与路径 | 请求 → 响应 |
|---|---|---|
|3|POST /identity/anonymous|空 → 201 {ownerId,csrfToken}及cookie；已有有效owner则200复用|
|3|GET /identity|空 → {ownerId,role,csrfToken}|
|3|POST /logout|CSRF → 204，撤销cookie凭证|
|3|POST /admin/login|{username,password} → {csrfToken}及管理员cookie|
|5/5b|POST /sessions|{questionVersion?:ID,mode?:evidence_only或demo} → 201 {id,status,revision,questionVersion,questions,answers,progress,jobId,demo}；仅可选已发布版本，指定mode须匹配；正式入口固定evidence_only，不自动切换发布指针|
|5/5b|GET /sessions/current|mode?:evidence_only或demo → {session: object|null}，按owner与mode恢复草稿/生成任务；正式入口不恢复demo会话|
|5|GET /sessions/{id}|空 → {id,status,revision,questionVersion,answers,progress}|
|5b|PUT /sessions/{id}/answers/{questionId}|{value:string|string[]|number|object,revision:number} → {revision,answeredCount}；object用于复合题|
|5|POST /sessions/{id}/submit|Idempotency-Key → 202 {jobId}|
|10|GET /jobs/{id}|空 → Job|
|10|POST /jobs/{id}/retry|Idempotency-Key → 202 {jobId};仅失败状态|
|10|GET /reports/{id}|空 → Report（包括部分结果）|
|10|GET /reports/{id}/parts/{part}|core/decisions/interpretation → Part|
|10|POST /reports/{id}/review|{status:confirmed或disputed,comment?:string} → {reviewStatus}|
|10|POST /reports/{id}/feedback|{rating:accurate或partial或inaccurate,text?:string,clientEventId:ID} → 201 {feedbackId}|
|10|GET /reports/{id}/feedback|cursor? → 分页反馈|
|11|POST /reports/{id}/chat|{message:string,clientMessageId:ID} → ChatReply；重复键返回原回复|
|11|GET /reports/{id}/chat/messages|cursor? → 分页用户消息及ChatReply|
|11|POST /facts/{id}/decision|{status:confirmed或rejected,expectedSnapshotId:ID或null,clientDecisionId:ID} → {snapshotId:ID或null}|
|11|POST /facts/{id}/revision|{content:string或null,expectedSnapshotId:ID,reason:string,clientDecisionId:ID} → {snapshotId};null撤回|
|11|GET /profile|空 → {snapshot:Snapshot或null,reports:Report[]}|
|11|GET /profile/snapshots|cursor? → 分页Snapshot|
|11|GET /profile/snapshots/{id}|空 → Snapshot|
|11|PUT /actions/{id}|{status:pending或completed,revision:number} → {revision,status}；记录事件不覆盖报告内容|
|7|GET/POST /admin/{resource}|rules/questions/configs/job-templates；列表或{content,changeReason}→草稿|
|7|GET /admin/{resource}/{id}|空 → {id,content,status,revision,version}|
|7|PUT /admin/{resource}/{id}|{content,revision} → 新revision；已发布409|
|7|POST /admin/{resource}/{id}/publish|{expectedRevision,changeReason} → {activeVersionId}|
|7|POST /admin/{resource}/{id}/rollback|{changeReason} → {activeVersionId}；只切换已发布历史版本|
|7|GET /admin/{resource}/versions|cursor? → 历史版本分页；路由注册优先于/{id}|
|8|GET/POST /admin/knowledge|列表或{title,body,source,date,tags}→草稿|
|8|GET/PUT /admin/knowledge/{id}|读取详情/以{body,revision,changeReason}编辑草稿|
|8|GET /admin/knowledge/versions|cursor? → 已发布语料集合历史；注册优先于/{id}|
|8|POST /admin/knowledge/{id}/index|空 → 202 {indexJobId}|
|8|GET /admin/index-jobs/{id}|空 → {status,progress,errorCode,indexVersionId}|
|8|POST /admin/knowledge/{id}/publish|{expectedRevision,changeReason} → {activeVersionId}；索引未ready则409|
|8|POST /admin/knowledge/{id}/deactivate|{changeReason} → 202 {indexJobId}；构建排除此文档的新集合，成功后原子发布|
|8|POST /admin/knowledge/{id}/rollback|{targetIndexVersionId,changeReason} → {activeVersionId}；恢复整版集合|

题库固定唯一Q01—Q40，Q39可选；Q25/Q30/Q31/Q36/Q37/Q38为复合输入并由版本化schema校验。Q30的1—4不得直接映射L0—L3，Q07/Q40差异不自动扣分。服务端按`required`和子字段校验，不能信任客户端questions。

任务覆盖按唯一核心task去重，分母为0返回`null`。证据区分核验结果、确认自述、行为、倾向、迁移待验证、缺口、未知和冲突；同一事实的重复来源不增加覆盖。

MVP保持首页、答题页、报告页、最小档案和手工经历入口。文件/简历上传、语音转写与完整Company长期追踪属于新增范围待办，本文不声明其已实现。

错误码：401 AUTH_REQUIRED、403 CSRF_INVALID/ADMIN_REQUIRED、404 NOT_FOUND、409 REVISION_CONFLICT/ALREADY_SUBMITTED/NOT_READY、422 INPUT_INVALID/REFERENCE_INVALID、429 RATE_LIMITED、503 PROVIDER_UNAVAILABLE。error.details不得包含密钥或其他用户内容。索引与生成各自持久化job，不共用含义不同的状态字段。

## 部分结果请求示例

```json
{"id":"job-1","status":"running","stage":"generate","reportId":"report-1","completedParts":["core"],"failedParts":[],"retryable":false,"attemptCount":1,"errorCode":null}
```

`GET /reports/report-1/parts/decisions` 在等待时返回：

```json
{"status":"pending","data":null,"errorCode":null}
```

确认事实请求：

```json
{"status":"confirmed","expectedSnapshotId":"profile-1","clientDecisionId":"confirm-1"}
```

成功响应为 `{"snapshotId":"profile-2"}`；进行中的job-1仍固定profile-1。

## Task5b 草稿与提交校验

复合答案草稿允许尚未填完的子字段；每次保存仍校验已给字段的类型、合法选项、上界、条件和禁止字段。提交时检查所有必答题的完整性及所有已给选答值，包含条件必填与激活状态下的合计长度。Q39音频待实现，接口拒绝音频字段；Q37无经历不适用经历字数限制。正式evidence_only提交必须固定已发布证据规则；尚未实现的job/prompt/index可固定明确unavailable状态，不使用demo名称，也不声称模型或知识库已运行。
