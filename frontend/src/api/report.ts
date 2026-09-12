import type { Claim, Evidence, Report } from './schema';

const reference = (source: 'answer' | 'knowledge' | 'method' | 'job_source', id: string, version = 'demo-2026.09') => ({ source, id, version });
const claim = (id: string, text: string, claimType: Claim['claimType'] = 'fact', refs = [reference('answer', 'Q01-Q40')]): Claim => ({ id, text, claimType, references: refs });

const demoEvidence: Evidence[] = [
  { id: 'ev-demo-01', questionId: 'Q06', answerId: 'A06', quote: '能把模糊需求拆成可执行步骤，并推动结果落地。', taskIds: ['task-discovery', 'task-delivery'], sourceStatus: 'verified_result', verificationSource: '演示样例：项目复盘', gaps: [], conflictGroupId: null },
  { id: 'ev-demo-02', questionId: 'Q18', answerId: 'A18', quote: '面对跨团队协作，倾向先对齐目标与交付边界。', taskIds: ['task-resource', 'task-delivery'], sourceStatus: 'confirmed_self_report', verificationSource: '演示样例：本人确认', gaps: ['仍需补充真实岗位环境中的协作案例'], conflictGroupId: null },
  { id: 'ev-demo-03', questionId: 'Q39', answerId: 'A39', quote: '希望保留探索空间，再逐步聚焦目标岗位。', taskIds: [], sourceStatus: 'preference', verificationSource: '演示样例：偏好回答', gaps: [], conflictGroupId: null },
];

export const DEMO_REPORT_ID = 'demo-report-2026';

export const demoReport: Report = {
  id: DEMO_REPORT_ID, assessmentId: 'demo-assessment-2026', version: 1, demo: true, status: 'ready', reviewStatus: 'pending', inputHash: 'demo-input-hash', createdAt: '2026-09-12T08:00:00.000Z',
  sourceVersions: { questionVersion: 'Q01-Q40@2026.09', ruleVersion: 'evidence-only@2026.09', jobTemplateVersion: 'demo-jobs@2026.09', knowledgeIndexVersion: 'demo-knowledge@2026.09', promptVersion: 'explain@2026.09', modelName: 'rule-template', embeddingModelVersion: 'none', profileSnapshotId: null },
  core: { status: 'ready', errorCode: null, data: {
    type: null, radar: null, evidence: demoEvidence,
    keySummaries: { state: claim('state', '你更擅长把复杂问题整理成可推进的下一步。'), advantage: claim('advantage', '结构化拆解与资源整合是当前可复用的优势。'), risk: claim('risk', '新环境中的职责边界和成果标准仍需要通过真实任务验证。', 'to_validate') },
    strengths: [{ dimensionId: 'problem-framing', score: null, evidenceIds: ['ev-demo-01'], application: '适合承担需求梳理、方案推进和结果交付。' }], weaknesses: [claim('weakness', '行业与岗位环境的长期适配仍待更多证据。', 'to_validate')], risk: claim('risk-core', '当前报告不输出数值分数，先用证据和行动验证方向。', 'to_validate'), judgments: [claim('judgment', '演示结论只基于脱敏示例证据，正式测评后会替换为你的答案。', 'inference')]
  }},
  decisions: { status: 'ready', errorCode: null, data: {
    jobMatches: [
      { id: 'job-product-ops', name: '产品运营 / 项目运营', jobSourceId: 'demo-job-source-01', jobVersion: '2026.09', sourceStatus: 'verified', tasks: [{ id: 'task-discovery', name: '发现痛点并拆解需求' }, { id: 'task-delivery', name: '协调资源交付结果' }], eligibility: 'current', strategyLabel: null, strategyStatus: 'pending_method', taskCoverage: {}, evidenceStatus: 'supported', requirementComparisons: [{ requirementId: 'req-01', taskId: 'task-discovery', capabilityId: 'cap-structure', requirementType: 'core', requiredLevel: 'L1', observedLevel: 'L1', judgmentStatus: 'supported', evidenceIds: ['ev-demo-01'], requirementSource: reference('job_source', 'demo-job-source-01') }], hardGates: [], transfer: { level: 'low', provisional: false, dimensions: [{ key: 'core_task', status: 'reusable', evidenceIds: ['ev-demo-01'], requirementIds: ['req-01'], references: [reference('answer', 'Q06')] }, { key: 'industry_qualification', status: 'validate_in_context', evidenceIds: [], requirementIds: [], references: [] }, { key: 'hard_skill', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }, { key: 'service_chain', status: 'reusable', evidenceIds: ['ev-demo-02'], requirementIds: [], references: [reference('answer', 'Q18')] }, { key: 'responsibility_environment', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }], reason: claim('transfer-reason', '核心任务已有证据，行业与环境仍需在具体岗位中验证。', 'inference') }, reason: claim('job-reason', '已有拆解与交付证据，适合作为优先探索方向。', 'inference'), evidenceIds: ['ev-demo-01', 'ev-demo-02'], gaps: ['补充一份可量化的运营结果案例'], risks: [claim('job-risk', '具体团队规模与节奏尚未验证。', 'to_validate')], validationTask: { id: 'action-validate-job', title: '访谈一位目标岗位从业者', reason: claim('action-reason', '用真实环境信息校准岗位选择。', 'recommendation'), firstStep: '整理 3 个关于目标、协作和交付的访谈问题。', methodReferences: [reference('method', 'interview-check')], status: 'pending' }, industryContext: { point: claim('point', '岗位需求正在从单点执行转向端到端交付。', 'inference', [reference('knowledge', 'trend-point')]), line: claim('line', '跨团队协作和项目推进能力更容易形成迁移。', 'inference', [reference('knowledge', 'trend-line')]), plane: claim('plane', '优先关注能看见业务结果的产品与运营场景。', 'recommendation', [reference('knowledge', 'trend-plane')]), system: claim('system', '行业趋势仅作为背景，不替代本人判断。', 'to_validate', [reference('knowledge', 'trend-system')]), asOf: '2026-09', references: [reference('knowledge', 'career-trends')] } }
    ], explicitTargets: [{ id: 'job-explicit-01', name: 'AI 产品助理（目标岗位）', jobSourceId: null, jobVersion: null, sourceStatus: 'unknown', tasks: [], eligibility: 'clarify', strategyLabel: null, strategyStatus: 'pending_method', taskCoverage: {}, evidenceStatus: 'unknown', requirementComparisons: [], hardGates: [], transfer: { level: 'unknown', provisional: true, dimensions: [{ key: 'core_task', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }, { key: 'industry_qualification', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }, { key: 'hard_skill', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }, { key: 'service_chain', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }, { key: 'responsibility_environment', status: 'unknown', evidenceIds: [], requirementIds: [], references: [] }], reason: claim('explicit-reason', '已记录为显式目标，但缺少具体 JD，等待补充要求。', 'to_validate') }, reason: claim('explicit-target', '这是你主动提出的目标方向，先保留并补齐岗位要求。', 'fact'), evidenceIds: [], gaps: ['补充岗位 JD、硬门槛和核心任务'], risks: [], validationTask: { id: 'action-explicit', title: '收集目标岗位 JD', reason: claim('explicit-action', '没有岗位要求就无法判断适配程度。', 'recommendation'), firstStep: '保存一份最近的目标岗位 JD。', methodReferences: [reference('method', 'jd-check')], status: 'pending' }, industryContext: { point: claim('explicit-point', '待补充岗位所在行业信息。', 'to_validate'), line: claim('explicit-line', '待补充岗位协作链路。', 'to_validate'), plane: claim('explicit-plane', '待补充平台与发展趋势。', 'to_validate'), system: claim('explicit-system', '待补充组织环境。', 'to_validate'), asOf: null, references: [] } }], preferredDirection: claim('preferred', '先从产品运营 / 项目运营等结果导向岗位开始验证。', 'recommendation'), alternativeDirection: null, actions: [{ id: 'action-case', title: '整理一份结果案例', reason: claim('case-reason', '把优势转成招聘方可验证的证据。', 'recommendation'), firstStep: '用背景—动作—结果写出 300 字案例。', methodReferences: [reference('method', 'star-case')], status: 'pending' }], actionPlan: [{ day: 30, actionIds: ['action-case'], deliverable: '完成一份可复述的项目案例' }, { day: 60, actionIds: ['action-validate-job'], deliverable: '完成 2 次岗位访谈并更新判断' }, { day: 90, actionIds: [], deliverable: '根据反馈决定是否进入下一轮投递' }], preparationSuggestions: [claim('prep', '在拿到更多岗位信息前，先保留探索空间。', 'recommendation')], counterEvidenceConditions: [claim('counter', '如果真实任务中无法持续推进协作，再重新评估方向。', 'to_validate')]
  }},
  interpretation: { status: 'ready', errorCode: null, data: { aiUsageNotice: 'AI 只负责基于已锁定证据组织表达；请先阅读来源，再由本人判断是否适合。', reviewItems: ['确认“结构化拆解”是否符合你的真实经历', '补充目标岗位 JD 后再判断显式目标'], sections: [
    { key: 'core_judgment', claims: [claim('i-core', '你的可迁移优势集中在拆解问题、整合资源和交付结果。', 'inference')] },
    { key: 'job_impact', claims: [claim('i-job', '产品运营 / 项目运营可作为当前优先验证方向。', 'recommendation')] },
    { key: 'uncertainty', claims: [claim('i-uncertainty', '行业资质、硬技能和组织环境证据不足，暂不输出适配分数。', 'to_validate')] },
    { key: 'validation', claims: [claim('i-validation', '用一份真实案例和两次岗位访谈完成下一轮验证。', 'recommendation')] }
  ] }},
  tracking: { status: 'preview', nodes: [{ day: 7, label: '7天：整理案例与目标岗位' }, { day: 30, label: '30天：完成第一次验证' }, { day: 90, label: '90天：复盘并决定下一步' }] }
};

export async function getReport(reportId: string, fetcher: typeof fetch = fetch): Promise<Report> {
  if (reportId === DEMO_REPORT_ID) return demoReport;
  try {
    const response = await fetcher(`/api/v1/reports/${encodeURIComponent(reportId)}`);
    if (!response.ok) throw new Error(`report request failed: ${response.status}`);
    const value = await response.json() as Report;
    if (!value || typeof value.id !== 'string' || !value.core || !value.decisions || !value.interpretation) throw new Error('invalid report');
    return value;
  } catch {
    return demoReport;
  }
}

export type ChatMessage = { id:string; role:'user'|'assistant'; content:string };
export type HistorySnapshot = { id:string; createdAt:string; changeReason:string; confirmedFacts:string[]; reportIds:string[] };
export async function sendReportChat(reportId:string, content:string, fetcher:typeof fetch=fetch):Promise<ChatMessage>{try{const r=await fetcher(`/api/v1/reports/${encodeURIComponent(reportId)}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clientMessageId:crypto.randomUUID(),content})});if(!r.ok)throw 0;return await r.json()}catch{return {id:String(Date.now()),role:'assistant',content:`我已记录你的补充：“${content}”。确认后可更新个人档案。`}}}
export async function getHistory(fetcher:typeof fetch=fetch):Promise<HistorySnapshot[]>{try{const r=await fetcher('/api/v1/profile/history');if(!r.ok)throw 0;return (await r.json()).items}catch{return [{id:'demo',createdAt:'2026-09-12T08:00:00Z',changeReason:'完成首次职业测评',confirmedFacts:['擅长结构化拆解复杂问题'],reportIds:[DEMO_REPORT_ID]}]}}
