/**
 * 后端 API 客户端。
 *
 * Token 保存在 localStorage，仅用于身份认证；模型 API Key 始终只存在于后端。
 */
import type {
  Achievement,
  AdminUser,
  AiConnectionResult,
  AiModelListInput,
  AiModelListResult,
  AiProviderConfigInput,
  AiShare,
  AiShareInput,
  AiShareList,
  AiSharePrompt,
  AiStatus,
  ArticleAnalysis,
  ArticleCard,
  ArticleDetail,
  ChatResponse,
  Conversation,
  ConversationSummary,
  CreatedCredentials,
  Dashboard,
  GamificationProfile,
  LeaderboardEntry,
  Report,
  Scenario,
  SentenceAnalysis,
  Theme,
  User,
  UserContent,
  VocabularyEntry,
  WordExplanation,
} from "./types";

// 默认走同源 /api（由 next.config.mjs 代理到后端），避免跨域问题。
// 如需直连后端，设置 NEXT_PUBLIC_API_BASE。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

const TOKEN_KEY = "linguascene_token";

/**
 * 语音识别通道：用户自己的模型 / 服务端本地识别。
 *
 * 曾经还有第三条「浏览器识别」（Web Speech API），已按产品要求删除——它在
 * 内嵌 webview 里连不上浏览器厂商的识别服务，识别质量也差。
 */
export type VoiceEngine = "model" | "local";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** 确认未授权时清掉本地令牌并回到登录页；其它状态码原样交给调用方。 */
export function handleUnauthorized(status: number): boolean {
  if (status !== 401) return false;
  clearToken();
  if (
    typeof window !== "undefined" &&
    !window.location.pathname.startsWith("/login")
  ) {
    window.location.href = "/login";
  }
  return true;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, "无法连接后端服务");
  }

  if (handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }

  if (!response.ok) {
    let detail = "请求失败";
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // 响应不是 JSON，保留默认文案
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  register: (payload: { username: string; email: string; password: string }) =>
    request<{ access_token: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  authConfig: () =>
    request<{ allow_public_registration: boolean }>("/api/auth/config"),

  // ---------------------------------------------------------------- 管理员
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),

  adminCreateUser: (payload: {
    username: string;
    email: string;
    password: string;
    cefr_level?: string;
    role?: "USER" | "ADMIN";
  }) =>
    request<CreatedCredentials>("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminResetPassword: (id: number, password: string) =>
    request<{ success: boolean; password: string }>(
      `/api/admin/users/${id}/reset-password`,
      {
        method: "POST",
        body: JSON.stringify({ password }),
      }
    ),

  adminUpdateRole: (id: number, role: "USER" | "ADMIN") =>
    request<AdminUser>(`/api/admin/users/${id}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  adminUpdateUser: (
    id: number,
    payload: {
      username?: string;
      email?: string;
      password?: string;
      cefr_level?: string;
      role?: "USER" | "ADMIN";
    }
  ) =>
    request<AdminUser>(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  adminDeleteUser: (id: number) =>
    request<void>(`/api/admin/users/${id}`, { method: "DELETE" }),

  // ------------------------------------------------------------ 我的 AI 模型
  aiStatus: () => request<AiStatus>("/api/ai-settings"),

  createAiConfig: (payload: AiProviderConfigInput) =>
    request<AiStatus>("/api/ai-settings/configs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateAiConfig: (id: number, payload: AiProviderConfigInput) =>
    request<AiStatus>(`/api/ai-settings/configs/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteAiConfig: (id: number) =>
    request<AiStatus>(`/api/ai-settings/configs/${id}`, { method: "DELETE" }),

  setAiActive: (payload: { config_id?: number; share_id?: number }) =>
    request<AiStatus>("/api/ai-settings/active", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  testAiCredential: (payload: AiModelListInput) =>
    request<AiConnectionResult>("/api/ai-settings/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listAiModels: (payload: AiModelListInput) =>
    request<AiModelListResult>("/api/ai-settings/models", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ------------------------------------------------------------ 模型分享
  aiShares: () => request<AiShareList>("/api/ai-shares"),

  createAiShare: (payload: AiShareInput) =>
    request<AiShare>("/api/ai-shares", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  setAiShareActive: (id: number, is_active: boolean) =>
    request<AiShare>(`/api/ai-shares/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active }),
    }),

  deleteAiShare: (id: number) =>
    request<AiShareList>(`/api/ai-shares/${id}`, { method: "DELETE" }),

  adoptAiShare: (id: number) =>
    request<AiShare>(`/api/ai-shares/${id}/adopt`, { method: "POST" }),

  dismissAiShare: (id: number) =>
    request<AiSharePrompt>(`/api/ai-shares/${id}/dismiss`, { method: "POST" }),

  aiSharePrompt: () => request<AiSharePrompt>("/api/ai-shares/prompt"),

  login: (payload: { email: string; password: string }) =>
    request<{ access_token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  onboarding: (payload: { cefr_level: string; interests: string[] }) =>
    request<User>("/api/auth/onboarding", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  me: () => request<User>("/api/users/me"),

  updateMe: (
    payload: Partial<Pick<User, "cefr_level" | "theme">> & {
      interests?: string[];
      // 改用户名/邮箱属于换登录凭据，必须同时带上当前密码
      username?: string;
      email?: string;
      current_password?: string;
    }
  ) =>
    request<User>("/api/users/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  changePassword: (current_password: string, new_password: string) =>
    request<{ success: boolean }>("/api/users/me/password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  uploadAvatar: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<User>("/api/users/me/avatar", { method: "POST", body: form });
  },

  removeAvatar: () =>
    request<User>("/api/users/me/avatar", { method: "DELETE" }),

  dashboard: () => request<Dashboard>("/api/dashboard"),

  scenarios: (params?: { category?: string; level?: string }) => {
    const query = new URLSearchParams();
    if (params?.category) query.set("category", params.category);
    if (params?.level) query.set("level", params.level);
    const suffix = query.toString() ? `?${query}` : "";
    return request<Scenario[]>(`/api/scenarios${suffix}`);
  },

  scenario: (id: number) => request<Scenario>(`/api/scenarios/${id}`),

  /**
   * 开始场景对话。`restart=true` 表示用户选了「重新开始」，后端会先把该场景
   * 的旧记录清掉再建新的，历史里同一场景始终只剩一条。
   */
  startScenario: (id: number, restart = false) =>
    request<Conversation>(
      `/api/scenarios/${id}/start${restart ? "?restart=true" : ""}`,
      { method: "POST" }
    ),

  /** 开始自由对话；`restart=true` 的语义同上，覆盖上一次的 Free Talk。 */
  startFreeTalk: (restart = false) =>
    request<Conversation>(
      `/api/conversations/free-talk/start${restart ? "?restart=true" : ""}`,
      { method: "POST" }
    ),

  conversations: () => request<ConversationSummary[]>("/api/conversations"),

  conversation: (id: number) =>
    request<Conversation>(`/api/conversations/${id}`),

  deleteConversation: (id: number) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  sendMessage: (id: number, message: string) =>
    request<ChatResponse>(`/api/conversations/${id}/message`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  finishConversation: (id: number) =>
    request<Report>(`/api/conversations/${id}/finish`, { method: "POST" }),

  articles: (params?: { category?: string; level?: string }) => {
    const query = new URLSearchParams();
    if (params?.category) query.set("category", params.category);
    if (params?.level) query.set("level", params.level);
    const suffix = query.toString() ? `?${query}` : "";
    return request<ArticleCard[]>(`/api/articles${suffix}`);
  },

  article: (id: number) => request<ArticleDetail>(`/api/articles/${id}`),

  analyzeArticle: (id: number) =>
    request<ArticleAnalysis>(`/api/articles/${id}/analyze`, {
      method: "POST",
    }),

  translate: (text: string) =>
    request<WordExplanation>("/api/articles/translate", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  analyzeSentence: (sentence: string, context = "") =>
    request<SentenceAnalysis>("/api/articles/explain-sentence", {
      method: "POST",
      body: JSON.stringify({ sentence, context }),
    }),

  /** 上传文件或粘贴文本，二者至少提供一个。 */
  uploadContent: (file: File | null, title: string, text = "") => {
    const form = new FormData();
    form.append("title", title);
    if (file) form.append("file", file);
    if (text.trim()) form.append("text", text);
    return request<UserContent>("/api/content/upload", {
      method: "POST",
      body: form,
    });
  },

  contents: () => request<UserContent[]>("/api/content"),

  content: (id: number) =>
    request<UserContent & { content: string }>(`/api/content/${id}`),

  generateMaterial: (id: number) =>
    request<ArticleAnalysis>(`/api/content/${id}/generate-learning-material`, {
      method: "POST",
    }),

  vocabulary: (dueOnly = false) =>
    request<VocabularyEntry[]>(
      `/api/vocabulary${dueOnly ? "?due_only=true" : ""}`
    ),

  reviewToday: () => request<VocabularyEntry[]>("/api/vocabulary/review-today"),

  saveWord: (payload: {
    word: string;
    meaning?: string;
    phonetic?: string;
    example?: string;
    level?: string;
    source?: string;
  }) =>
    request<VocabularyEntry>("/api/vocabulary/save", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  reviewWord: (id: number, quality: number) =>
    request<{ word: string; mastery: number; next_review: string }>(
      `/api/vocabulary/${id}/review`,
      { method: "POST", body: JSON.stringify({ quality }) }
    ),

  deleteWord: (id: number) =>
    request<void>(`/api/vocabulary/${id}`, { method: "DELETE" }),

  // ---------------------------------------------------------------- 语音
  /** 语音输入能力：用户自己的模型能不能转写、还有哪些备选通道。 */
  audioStt: () =>
    request<{
      available: boolean;
      engine: VoiceEngine | "";
      model: string;
      local_model: string;
      reason: string;
      engines: { id: VoiceEngine; label: string; detail: string }[];
    }>("/api/audio/stt"),

  /**
   * 上传一段录音换文本。
   *
   * engine 是用户选定的通道：`local` 走服务端本地识别（界面默认这条，不连任何
   * API、不需要 Key），`model` 走他在 AI 模型页配的那家。后端不会替用户换通道
   * ——走不通时返回 503/502，由界面弹窗让用户自己决定。
   */
  transcribe: (
    blob: Blob,
    filename: string,
    language = "en",
    engine: VoiceEngine = "model"
  ) => {
    const form = new FormData();
    form.append("file", blob, filename);
    form.append("language", language);
    form.append("engine", engine);
    return request<{ text: string; engine: VoiceEngine }>(
      "/api/audio/transcribe",
      { method: "POST", body: form }
    );
  },

  gamificationProfile: () =>
    request<GamificationProfile>("/api/gamification/profile"),

  leaderboard: () =>
    request<LeaderboardEntry[]>("/api/gamification/leaderboard"),

  achievements: () => request<Achievement[]>("/api/gamification/achievements"),

  pendingAchievements: () =>
    request<Achievement[]>("/api/gamification/achievements/pending"),

  ackAchievements: (codes: string[]) =>
    request<{ updated: number }>("/api/gamification/achievements/ack", {
      method: "POST",
      body: JSON.stringify({ codes }),
    }),

  themes: () => request<Theme[]>("/api/gamification/themes"),
};
