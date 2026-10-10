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
  Report,
  Scenario,
  SentenceAnalysis,
  Theme,
  User,
  UserContent,
  VocabularyEntry,
  WordExplanation,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

const TOKEN_KEY = "linguascene_token";

export type VoiceEngine = "model" | "local";

// 令牌存放在 sessionStorage：关闭标签页/浏览器后即失效，下次打开网站必须重新登录。
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
  // 清除旧版本残留在 localStorage 里的令牌，避免历史登录状态继续生效。
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function handleUnauthorized(status: number): boolean {
  if (status !== 401) return false;
  clearToken();
  if (
    typeof window !== "undefined" &&
    !window.location.pathname.startsWith(`${BASE_PATH}/login`)
  ) {
    window.location.href = `${BASE_PATH}/login`;
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

  if (token && handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail.trim()) {
        detail = body.detail;
      }
    } catch {

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

  adminUsers: () => request<AdminUser[]>("/api/admin/users"),

  adminCredentials: (id: number) =>
    request<CreatedCredentials>(`/api/admin/users/${id}/credentials`),

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

  startScenario: (id: number, restart = false) =>
    request<Conversation>(
      `/api/scenarios/${id}/start${restart ? "?restart=true" : ""}`,
      { method: "POST" }
    ),

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

  translate: (text: string, context = "", fast = false) =>
    request<WordExplanation>("/api/articles/translate", {
      method: "POST",
      body: JSON.stringify({ text, context, fast }),
    }),

  analyzeSentence: (sentence: string, context = "") =>
    request<SentenceAnalysis>("/api/articles/explain-sentence", {
      method: "POST",
      body: JSON.stringify({ sentence, context }),
    }),

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

  audioStt: () =>
    request<{
      available: boolean;
      engine: VoiceEngine | "";
      model: string;
      local_model: string;
      local_reason: string;
      reason: string;
      engines: { id: VoiceEngine; label: string; detail: string }[];
    }>("/api/audio/stt"),

  transcribe: (
    blob: Blob,
    filename: string,
    language = "en",
    engine: VoiceEngine = "model",
    scenarioId?: number
  ) => {
    const form = new FormData();
    form.append("file", blob, filename);
    form.append("language", language);
    form.append("engine", engine);
    // 带上场景，服务端才能用该场景的重点句式/词汇给本地识别做提示。
    if (scenarioId) form.append("scenario_id", String(scenarioId));
    return request<{ text: string; engine: VoiceEngine }>(
      "/api/audio/transcribe",
      { method: "POST", body: form }
    );
  },

  gamificationProfile: () =>
    request<GamificationProfile>("/api/gamification/profile"),

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
