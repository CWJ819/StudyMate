import type {
  ChunkDetail,
  ChunkSearchResult,
  Course,
  Health,
  Job,
  KnowledgeFramework,
  KnowledgeGap,
  KnowledgeNodeDetail,
  KnowledgeVersion,
  MasteryState,
  MaterialDetail,
  MaterialSummary,
  QuizDetail,
  QuizSubmission,
  Settings,
  StudyPlanDetail,
  StudyPlanSummary,
  StudyTask,
} from '../api/endpoints'

/** 本地今天的 YYYY-MM-DD（计划任务按相对日期布置，保证"今日任务"随时可测） */
function isoDaysFromNow(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

export const healthOk: Health = {
  status: 'ok',
  application: 'studymate',
  database: 'ok',
  environment: 'dev',
}

/** mock LLM 的设置（触发演示横幅） */
export const settingsMock: Settings = {
  app_env: 'dev',
  database_url: 'sqlite+pysqlite:///./data/test.db',
  storage_root: './data/uploads',
  llm_base_url: 'mock://local',
  llm_model: 'mock-model',
  llm_timeout_seconds: 60,
  llm_max_retries: 2,
  max_upload_bytes: 10485760,
  max_document_pages: 200,
  job_max_attempts: 3,
  llm_auth_configured: false,
}

/** 未配置 LLM 的设置（不显示演示横幅） */
export const settingsPlain: Settings = {
  ...settingsMock,
  llm_base_url: 'https://open.bigmodel.cn/api/paas/v4',
  llm_model: 'glm-4-flash',
}

export const course1: Course = {
  id: 'c1',
  name: '计算机网络·运输层',
  description: '第 3 章课件',
  active_framework_version_id: null,
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-03T08:00:00Z',
}

export const materialQueued: MaterialSummary = {
  id: 'm1',
  course_id: 'c1',
  filename: '第3章-运输层（新）.pptx',
  mime_type: 'application/vnd...presentation',
  size_bytes: 2048000,
  status: 'queued',
  error_code: null,
  page_count: 0,
  chunk_count: 0,
  no_text_pages: [],
  created_at: '2026-01-03T09:00:00Z',
  updated_at: '2026-01-03T09:00:00Z',
}

export const materialWarn: MaterialSummary = {
  id: 'm2',
  course_id: 'c1',
  filename: '运输层讲义.pdf',
  mime_type: 'application/pdf',
  size_bytes: 1048576,
  status: 'completed_with_warnings',
  error_code: null,
  page_count: 24,
  chunk_count: 18,
  no_text_pages: [2, 19],
  created_at: '2026-01-02T09:00:00Z',
  updated_at: '2026-01-02T09:05:00Z',
}

export const materialFailed: MaterialSummary = {
  id: 'm3',
  course_id: 'c1',
  filename: '损坏的扫描件.pdf',
  mime_type: 'application/pdf',
  size_bytes: 500000,
  status: 'failed',
  error_code: 'DOCUMENT_TOO_MANY_PAGES',
  page_count: 0,
  chunk_count: 0,
  no_text_pages: [],
  created_at: '2026-01-01T09:00:00Z',
  updated_at: '2026-01-01T09:01:00Z',
}

export const materialsC1: MaterialSummary[] = [materialQueued, materialWarn, materialFailed]

export const materialDetail: MaterialDetail = {
  ...materialWarn,
  pages: [
    {
      page_number: 1,
      extraction_status: 'extracted',
      error_code: null,
      text_preview: '第 3 章 运输层：UDP 与 TCP…',
      text_length: 520,
    },
    {
      page_number: 2,
      extraction_status: 'no_extractable_text',
      error_code: null,
      text_preview: null,
      text_length: 0,
    },
    {
      page_number: 3,
      extraction_status: 'extracted',
      error_code: null,
      text_preview: '慢启动与拥塞避免：cwnd 从 1 开始…',
      text_length: 610,
    },
  ],
}

export const searchResults: ChunkSearchResult[] = [
  {
    chunk_id: 'ch1',
    document_id: 'm2',
    filename: '运输层讲义.pdf',
    page_start: 18,
    page_end: 18,
    text: '慢启动：拥塞窗口 cwnd 从 1 个 MSS 开始，每收到一个 ACK 加一，指数增长……',
  },
  {
    chunk_id: 'ch2',
    document_id: 'm2',
    filename: '运输层讲义.pdf',
    page_start: 19,
    page_end: 19,
    text: '拥塞避免：cwnd 超过 ssthresh 后进入线性增长阶段……',
  },
]

export const chunkDetail: ChunkDetail = {
  id: 'ch1',
  document_id: 'm2',
  course_id: 'c1',
  filename: '运输层讲义.pdf',
  page_start: 18,
  page_end: 18,
  text: '慢启动：拥塞窗口 cwnd 从 1 个 MSS 开始，每收到一个 ACK 加一，指数增长；达到 ssthresh 后转入拥塞避免。（完整原文，比搜索摘要长，用于核对上下文。）',
}

// ---- 知识框架（F2）----

export const sourceKn1 = {
  document_id: 'm2',
  filename: '运输层讲义.pdf',
  page_number: 18,
  chunk_id: 'ch1',
  evidence_type: 'outline',
}

export const frameworkActive: KnowledgeFramework = {
  framework_version_id: 'fv1',
  version_number: 3,
  status: 'active',
  activated_at: '2026-01-03T10:00:00Z',
  tree: [
    {
      knowledge_node_id: 'kn-root',
      node_version_id: 'nv-root',
      section_label: '3',
      title: '运输层',
      content: null,
      level: 0,
      is_leaf: false,
      sources: [],
      children: [
        {
          knowledge_node_id: 'kn1',
          node_version_id: 'nv1',
          section_label: '3.1',
          title: '拥塞控制',
          content: null,
          level: 1,
          is_leaf: false,
          sources: [],
          children: [
            {
              knowledge_node_id: 'kn2',
              node_version_id: 'nv2',
              section_label: '3.1.1',
              title: '慢启动与拥塞避免',
              content: '慢启动阶段 cwnd 指数增长，达到 ssthresh 后进入拥塞避免线性增长。',
              level: 2,
              is_leaf: true,
              sources: [sourceKn1],
              children: [],
            },
          ],
        },
        {
          knowledge_node_id: 'kn3',
          node_version_id: 'nv3',
          section_label: '3.2',
          title: '可靠传输：GBN 与 SR',
          content: null,
          level: 1,
          is_leaf: true,
          sources: [],
          children: [],
        },
      ],
    },
  ],
  nodes: [
    {
      knowledge_node_id: 'kn-root',
      node_version_id: 'nv-root',
      section_label: '3',
      title: '运输层',
      content: null,
      level: 0,
      is_leaf: false,
      sources: [],
      children: [],
    },
    {
      knowledge_node_id: 'kn1',
      node_version_id: 'nv1',
      section_label: '3.1',
      title: '拥塞控制',
      content: null,
      level: 1,
      is_leaf: false,
      sources: [],
      children: [],
    },
    {
      knowledge_node_id: 'kn2',
      node_version_id: 'nv2',
      section_label: '3.1.1',
      title: '慢启动与拥塞避免',
      content: '慢启动阶段 cwnd 指数增长，达到 ssthresh 后进入拥塞避免线性增长。',
      level: 2,
      is_leaf: true,
      sources: [sourceKn1],
      children: [],
    },
    {
      knowledge_node_id: 'kn3',
      node_version_id: 'nv3',
      section_label: '3.2',
      title: '可靠传输：GBN 与 SR',
      content: null,
      level: 1,
      is_leaf: true,
      sources: [],
      children: [],
    },
  ] satisfies KnowledgeFramework['nodes'],
}

export const nodeDetailKn2: KnowledgeNodeDetail = {
  knowledge_node_id: 'kn2',
  node_version_id: 'nv2',
  framework_version_id: 'fv1',
  section_label: '3.1.1',
  title: '慢启动与拥塞避免',
  content: '慢启动阶段 cwnd 指数增长，达到 ssthresh 后进入拥塞避免线性增长。超时则门限减半重新慢启动。',
  level: 2,
  is_leaf: true,
  sources: [sourceKn1],
  relations: [
    {
      target_knowledge_node_id: 'kn3',
      target_title: '可靠传输：GBN 与 SR',
      relation_type: 'related',
      confidence: 0.6,
      evidence: null,
    },
  ],
}

export const knowledgeVersions: KnowledgeVersion[] = [
  {
    id: 'fv1',
    version_number: 3,
    status: 'active',
    created_at: '2026-01-03T10:00:00Z',
    activated_at: '2026-01-03T10:00:05Z',
  },
  {
    id: 'fv0',
    version_number: 2,
    status: 'failed',
    created_at: '2026-01-02T10:00:00Z',
    activated_at: null,
  },
]

export const masteryStates: MasteryState[] = [
  {
    knowledge_node_id: 'kn2',
    title: '慢启动与拥塞避免',
    alpha: 3.2,
    beta: 6.8,
    mastery_estimate: 0.42,
    evidence_count: 3,
    updated_at: '2026-01-03T11:00:00Z',
  },
]

export const jobSucceeded: Job = {
  id: 'job-ok',
  type: 'knowledge_build',
  status: 'succeeded',
  progress: 100,
  attempts: 1,
  max_attempts: 3,
  run_after: '2026-01-03T10:00:00Z',
  locked_at: null,
  error_code: null,
  error_summary: null,
  started_at: '2026-01-03T10:00:01Z',
  finished_at: '2026-01-03T10:00:05Z',
  created_at: '2026-01-03T10:00:00Z',
  updated_at: '2026-01-03T10:00:05Z',
}

export const jobFailed: Job = {
  ...jobSucceeded,
  id: 'job-bad',
  status: 'failed',
  error_code: 'LLM_TIMEOUT',
  error_summary: 'llm timeout after 60s',
  finished_at: '2026-01-03T10:01:00Z',
}

// ---- 测验与复习（F3）----

/** 4 题：单选×2 + 多选 + 简答，Q1 对、Q2 错、Q3 部分、Q4 待批改 */
export const quizOpen: QuizDetail = {
  quiz_id: 'qz1',
  course_id: 'c1',
  framework_version_id: 'fv1',
  status: 'open',
  created_at: '2026-01-03T12:00:00Z',
  questions: [
    {
      question_id: 'q1',
      ordinal: 1,
      question_type: 'single_choice',
      stem: '慢启动阶段，每经过一个 RTT，拥塞窗口 cwnd 的增长方式是？',
      options: [
        { id: 'q1o1', text: '指数增长' },
        { id: 'q1o2', text: '线性增长' },
        { id: 'q1o3', text: '保持不变' },
      ],
      difficulty: 'low',
      max_score: 2,
    },
    {
      question_id: 'q2',
      ordinal: 2,
      question_type: 'single_choice',
      stem: '收到 3 个重复 ACK 会触发什么？',
      options: [
        { id: 'q2o1', text: '快重传与快恢复' },
        { id: 'q2o2', text: '重新慢启动' },
      ],
      difficulty: 'low',
      max_score: 2,
    },
    {
      question_id: 'q3',
      ordinal: 3,
      question_type: 'multiple_choice',
      stem: '下列哪些属于拥塞控制的机制？（多选）',
      options: [
        { id: 'q3o1', text: '慢启动' },
        { id: 'q3o2', text: '拥塞避免' },
        { id: 'q3o3', text: '快重传' },
      ],
      difficulty: 'low',
      max_score: 3,
    },
    {
      question_id: 'q4',
      ordinal: 4,
      question_type: 'short_answer',
      stem: '简述滑动窗口机制中发送窗口的取值。',
      options: [],
      difficulty: 'low',
      max_score: 3,
    },
  ],
}

export const quizSubmission: QuizSubmission = {
  submission_id: 'sub1',
  quiz_id: 'qz1',
  status: 'graded',
  total_score: 5,
  max_score: 10,
  question_results: [
    {
      question_id: 'q1',
      score: 2,
      max_score: 2,
      grading_method: 'deterministic',
      correct: true,
      feedback_text: null,
    },
    {
      question_id: 'q2',
      score: 0,
      max_score: 2,
      grading_method: 'deterministic',
      correct: false,
      feedback_text: '收到 3 个重复 ACK 触发快重传与快恢复，只有超时才重新慢启动。',
    },
    {
      question_id: 'q3',
      score: 1,
      max_score: 3,
      grading_method: 'deterministic',
      correct: false,
      feedback_text: '漏选了快重传。',
    },
    {
      question_id: 'q4',
      score: 2,
      max_score: 3,
      grading_method: 'rubric_llm',
      correct: null,
      feedback_text: '要点基本覆盖，未提到 rwnd 的约束。',
    },
  ],
}

export const wrongbookGaps: KnowledgeGap[] = [
  {
    gap_id: 'gap1',
    knowledge_node_id: 'kn2',
    node_version_id: 'nv2',
    title: '慢启动与拥塞避免',
    gap_type: 'low_score',
    status: 'open',
    confidence: 0.8,
    evidence_count: 3,
    evidence_summary: {
      total_evidence: 5,
      low_score_evidence: 3,
      positive_evidence: 2,
      last_attempt_id: 'at-1',
      last_normalized_score: 0.4,
    },
    updated_at: '2026-01-03T12:30:00Z',
  },
  {
    gap_id: 'gap2',
    knowledge_node_id: 'kn3',
    node_version_id: 'nv3',
    title: '可靠传输：GBN 与 SR',
    gap_type: 'some_future_type',
    status: 'open',
    confidence: 0.5,
    evidence_count: 1,
    evidence_summary: {},
    updated_at: '2026-01-03T12:30:00Z',
  },
]

// ---- 复习计划（F4）：日期相对今天，t1/t2 排在今天 ----

function planTask(partial: Partial<StudyTask> & Pick<StudyTask, 'id' | 'title'>): StudyTask {
  return {
    task_type: 'review',
    scheduled_date: isoDaysFromNow(0),
    estimated_minutes: 30,
    priority: 1,
    status: 'pending',
    targets: [
      {
        knowledge_node_id: 'kn2',
        title: '慢启动与拥塞避免',
        target_role: 'primary',
      },
    ],
    ...partial,
  }
}

export const planTasksActive: StudyTask[] = [
  planTask({ id: 't1', title: 'Review 慢启动与拥塞避免', priority: 1 }),
  planTask({
    id: 't2',
    title: 'Practice 慢启动与拥塞避免',
    task_type: 'practice',
    priority: 2,
    status: 'in_progress',
    targets: [{ knowledge_node_id: 'kn2', title: '慢启动与拥塞避免', target_role: 'practice' }],
  }),
  planTask({
    id: 't3',
    title: 'Review 可靠传输：GBN 与 SR',
    scheduled_date: isoDaysFromNow(1),
    priority: 3,
    status: 'completed',
    targets: [{ knowledge_node_id: 'kn3', title: '可靠传输：GBN 与 SR', target_role: 'primary' }],
  }),
  planTask({
    id: 't4',
    title: 'Practice 可靠传输：GBN 与 SR',
    task_type: 'practice',
    scheduled_date: isoDaysFromNow(1),
    priority: 4,
    status: 'skipped',
    estimated_minutes: 15,
    targets: [{ knowledge_node_id: 'kn3', title: '可靠传输：GBN 与 SR', target_role: 'practice' }],
  }),
]

export const planActiveSummary: StudyPlanSummary = {
  id: 'pl1',
  course_id: 'c1',
  version_number: 2,
  exam_date: isoDaysFromNow(9),
  daily_minutes: 60,
  target_score: 85,
  status: 'active',
  task_count: planTasksActive.length,
  created_at: '2026-01-03T10:00:00Z',
}

export const planInactiveSummary: StudyPlanSummary = {
  id: 'pl0',
  course_id: 'c1',
  version_number: 1,
  exam_date: isoDaysFromNow(-2),
  daily_minutes: 45,
  target_score: 80,
  status: 'inactive',
  task_count: 1,
  created_at: '2025-12-20T10:00:00Z',
}

export const plansC1: StudyPlanSummary[] = [planActiveSummary, planInactiveSummary]

export const planDetailActive: StudyPlanDetail = {
  id: 'pl1',
  course_id: 'c1',
  version_number: 2,
  exam_date: isoDaysFromNow(9),
  daily_minutes: 60,
  target_score: 85,
  status: 'active',
  constraints: { algorithm_version: 'study-plan-v1' },
  created_at: '2026-01-03T10:00:00Z',
  tasks: planTasksActive,
}

export const planDetailInactive: StudyPlanDetail = {
  ...planDetailActive,
  id: 'pl0',
  version_number: 1,
  status: 'inactive',
  tasks: [
    planTask({
      id: 't0',
      title: 'Review 慢启动与拥塞避免',
      status: 'completed',
      scheduled_date: isoDaysFromNow(-2),
    }),
  ],
}
