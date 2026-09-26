export type CefrLevel = "A1" | "A2" | "B1" | "B2" | "C1";

export interface User {
  id: number;
  username: string;
  email: string;
  avatar: string | null;
  role: string;
  cefr_level: CefrLevel;
  interests: string[];
  level: number;
  level_name: string;
  xp: number;
  xp_to_next: number;
  streak: number;
  longest_streak: number;
  theme: string;
  created_at: string;
}

export interface ScenarioTask {
  id: number;
  task_key: string;
  task_order: number;
  description: string;
  required: boolean;
}

export interface Scenario {
  id: number;
  slug: string;
  title: string;
  title_zh: string;
  description: string;
  category: string;
  icon: string;
  level: CefrLevel;
  difficulty: number;
  estimated_minutes: number;
  ai_role: string;
  opening_line: string;
  goal: string;
  key_phrases: string[];
  key_vocabulary: string[];
  tasks: ScenarioTask[];
}

export interface Correction {
  original: string;
  corrected: string;
  explanation: string;
  correction_type: string;
  severity: number;
}

export interface NaturalExpression {
  expression: string;
  meaning: string;
  example: string;
}

export interface VocabularyItem {
  word: string;
  meaning: string;
  phonetic?: string;
  example?: string;
  is_new?: boolean;
}

export interface CoachNote {
  verdict: "good" | "fix" | "try";
  message_zh: string;
  tip_en: string;
}

export interface MessageFeedback {
  correction: Correction | null;
  natural_expression: NaturalExpression | null;
  new_vocabulary: VocabularyItem[];
  coach_note?: CoachNote | null;
}

export interface ScenarioHint {
  task_key: string;
  task_description: string;
  idea_zh: string;
  suggested_zh: string;
  suggested_en: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  feedback: MessageFeedback | null;
}

export interface Conversation {
  id: number;
  mode: "scenario" | "free_talk";
  task_progress: number;
  is_completed: boolean;
  xp_earned: number;
  started_at: string;
  finished_at: string | null;
  scenario: Scenario | null;
  hint: ScenarioHint | null;
  messages: Message[];
}

export interface ChatResponse {
  user_message: Message;
  ai_message: Message;
  correction: Correction | null;
  natural_expression: NaturalExpression | null;
  new_vocabulary: VocabularyItem[];
  hint: ScenarioHint | null;
  coach_note: CoachNote | null;
  task_progress: number;
  task_completed: boolean;
  completed_tasks: string[];
}

/**
 * 流式对话的第一帧：AI 这一轮说的话已经落库，反馈还在路上。
 *
 * 拆成两帧是为了让 AI 尽快开口——回复那一路的模型输出只有一句话，
 * 比连纠错、点评、提示一起算完快得多。
 */
export interface ChatReplyEvent {
  user_message: Message;
  ai_message: Message;
  /** 本地规则算出的提示，先顶上；模型那条更贴合的随反馈帧覆盖 */
  hint: ScenarioHint | null;
  task_progress: number;
  task_completed: boolean;
  completed_tasks: string[];
}

/** 流式对话的第二帧：纠错、地道表达、新词、点评与下一步提示。 */
export interface ChatFeedbackEvent {
  correction: Correction | null;
  natural_expression: NaturalExpression | null;
  new_vocabulary: VocabularyItem[];
  coach_note: CoachNote | null;
  hint: ScenarioHint | null;
  task_progress: number;
  task_completed: boolean;
  completed_tasks: string[];
}

export interface Report {
  conversation_id: number;
  scenario_title: string;
  summary: string;
  task_progress: number;
  scores: {
    grammar: number;
    vocabulary: number;
    naturalness: number;
    communication: number;
  };
  new_words: string[];
  key_phrases: string[];
  corrections_count: number;
  xp_earned: number;
  streak: number;
}

export interface ArticleCard {
  id: number;
  title: string;
  source: string;
  url: string;
  summary: string;
  level: CefrLevel;
  category: string;
  word_count: number;
  read_minutes: number;
  published_at: string;
}

export interface ArticleDetail extends ArticleCard {
  content: string;
}

export interface Phrase {
  phrase: string;
  meaning: string;
  example: string;
}

export interface GrammarPoint {
  point: string;
  explanation: string;
  example: string;
}

export interface ArticleAnalysis {
  summary: string;
  level: string;
  keywords: VocabularyItem[];
  phrases: Phrase[];
  grammar_points: GrammarPoint[];
  reading_questions: string[];
  speaking_questions: string[];
  writing_task: string;
}

export interface WordExplanation {
  word: string;
  pronunciation: string;
  part_of_speech: string;
  core_meanings: string[];
  meaning_in_context: string;
  collocations: string[];
  example_sentences: string[];
  related_words: string[];
  cefr_level: string;
}

export interface SentenceAnalysis {
  sentence: string;
  chinese_meaning: string;
  main_clause: string;
  structure: string;
  vocabulary: VocabularyItem[];
  collocations: Phrase[];
  grammar_points: GrammarPoint[];
  natural_alternative: string;
  cefr_level: string;
}

export interface VocabularyEntry {
  id: number;
  word: string;
  phonetic: string;
  meaning: string;
  example: string;
  level: string;
  mastery: number;
  review_count: number;
  source: string;
  next_review: string | null;
}

export interface DailyQuest {
  key: string;
  label: string;
  target: number;
  progress: number;
  xp: number;
  completed: boolean;
}

export interface Dashboard {
  greeting: string;
  username: string;
  streak: number;
  xp: number;
  level: number;
  level_name: string;
  level_progress: number;
  xp_to_next: number;
  today_mission: Scenario | null;
  recommended_scenarios: Scenario[];
  recommended_article: ArticleCard | null;
  daily_quests: DailyQuest[];
  review_due_count: number;
}

export interface LeaderboardEntry {
  rank: number;
  user_id: number;
  username: string;
  avatar: string | null;
  xp: number;
  is_me: boolean;
}

export interface Achievement {
  code: string;
  name: string;
  description: string;
  icon: string;
  unlocked: boolean;
  unlocked_at: string | null;
  // 未解锁时展示进度；已解锁时 progress === target
  progress: number;
  target: number;
}

export interface Theme {
  code: string;
  name: string;
  colors: string[];
}

export interface GamificationProfile {
  level: number;
  level_name: string;
  xp: number;
  xp_to_next: number;
  level_progress: number;
  streak: number;
  longest_streak: number;
  weekly_xp: number;
  active_days: string[];
  today_minutes: number;
  daily_goal_minutes: number;
}

export interface UserContent {
  id: number;
  title: string;
  content_type: string;
  status: string;
  created_at: string;
  word_count: number;
  preview: string;
}

export interface ConversationSummary {
  id: number;
  mode: string;
  scenario_id: number | null;
  scenario_title: string;
  scenario_icon: string;
  task_progress: number;
  is_completed: boolean;
  xp_earned: number;
  started_at: string;
  finished_at: string | null;
  /** 最后一条消息的时间：历史列表显示的就是它，而不是开始时间。 */
  last_message_at: string;
  /** 用户说的第一句话，自由对话靠它区分是哪一次聊天。 */
  preview: string;
}

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  role: "USER" | "ADMIN";
  cefr_level: CefrLevel;
  level: number;
  level_name: string;
  xp: number;
  streak: number;
  created_at: string;
  last_active_date: string | null;
  avatar: string | null;
  password_updated_at: string | null;
}

export interface CreatedCredentials {
  id: number;
  username: string;
  email: string;
  password: string;
}

// ------------------------------------------------------------------ AI 模型设置

/** 接入协议。绝大多数兼容服务都走 openai。 */
export type AiApiFormat =
  | "openai"
  | "openai_responses"
  | "anthropic"
  | "gemini";

export interface AiProviderConfig {
  id: number;
  name: string;
  base_url: string;
  api_format: AiApiFormat;
  /** 这条供应商下可选的模型名 */
  models: string[];
  /** 当前用这条供应商里的哪个模型 */
  active_model: string;
  key_hint: string;
  /** 是否是当前实际生效的那条 */
  is_active: boolean;
  updated_at: string | null;
}

/** 实际生效的来源：自己的供应商 / 采纳的分享 / 站点兜底 / 离线规则引擎 */
export type AiSource = "user" | "share" | "env" | "mock";

export interface AiStatus {
  /** 我接入的供应商，一人可有多条 */
  configs: AiProviderConfig[];
  active_source: AiSource;
  active_label: string;
  active_config_id: number | null;
  active_share_id: number | null;
  /** 别人分享出来、我尚可使用的模型 + 我分享出去的 */
  shares: AiShare[];
  /** 我当前采纳的那条分享；已被分享者停用/删除时 is_active=false */
  adopted_share: AiShare | null;
}

export interface AiProviderConfigInput {
  name?: string;
  base_url: string;
  api_key: string;
  api_format: AiApiFormat;
  models: string[];
  active_model: string;
}

export interface AiConnectionResult {
  success: boolean;
  message: string;
  /** ok：一次往返走通；warn：地址与 Key 没问题，只是模型这次太慢；fail：明确失败 */
  status?: "ok" | "warn" | "fail";
  /** 失败且像模型名的问题时，服务端带回来的真实模型名，可一键加入列表 */
  suggested_models?: string[];
}

/** 测试连接/拉取模型列表：api_key 留空表示沿用 config_id 里已保存的 Key。 */
export interface AiModelListInput {
  base_url: string;
  api_key: string;
  api_format: AiApiFormat;
  config_id?: number | null;
  /** 只有测试连接需要 */
  model?: string;
}

export interface AiModelListResult {
  success: boolean;
  message: string;
  models: string[];
}

// ------------------------------------------------------------------ AI 模型分享

/** 一条用户分享出来的模型接入信息。Key 永不回传，只有指纹尾号。 */
export interface AiShare {
  id: number;
  owner_id: number;
  owner_name: string;
  title: string;
  base_url: string;
  api_format: AiApiFormat;
  models: string[];
  active_model: string;
  note: string;
  is_active: boolean;
  is_mine: boolean;
  adoption_count: number;
  key_hint: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface AiShareList {
  mine: AiShare[];
  available: AiShare[];
  adopted_id: number | null;
}

/** 登录后的分享弹窗。available=false 时不弹。 */
export interface AiSharePrompt {
  available: boolean;
  share: AiShare | null;
  reason: string;
}

/** 创建分享：把自己的一条供应商配置分享出去，Key 由服务端取出。 */
export interface AiShareInput {
  config_id: number;
  title?: string;
  note?: string;
}

// 管理员场景管理：比普通 Scenario 多出提示词与发布状态
export interface AdminScenario extends Scenario {
  ai_role_prompt: string;
  is_published: boolean;
}

export interface ScenarioTaskInput {
  description: string;
  required: boolean;
}

export interface ScenarioInput {
  slug?: string;
  title: string;
  title_zh?: string;
  description?: string;
  category?: string;
  icon?: string;
  level?: CefrLevel;
  difficulty?: number;
  estimated_minutes?: number;
  ai_role?: string;
  ai_role_prompt?: string;
  opening_line?: string;
  goal?: string;
  key_phrases?: string[];
  key_vocabulary?: string[];
  tasks?: ScenarioTaskInput[];
  is_published?: boolean;
}
