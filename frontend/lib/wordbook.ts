import { ApiError, BASE_PATH, getToken, handleUnauthorized } from "./api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export interface WordExample {
  en: string;
  zh: string;
}

export interface WordCard {
  id: number;
  word: string;
  phonetic_uk: string;
  phonetic_us: string;
  part_of_speech: string;
  meaning: string;
  meaning_zh: string;
  example: string;
  examples: WordExample[];
  level: string;
  books: string[];
  tags: string[];
  unit: string;
  audio_uk: string;
  audio_us: string;
  in_vocabulary: boolean;
  mastery: number;
  review_count: number;

  status: WordStatus;
  due_date: string;
}

export type WordStatus = "new" | "learning" | "review" | "mastered";
export type StudyAction = "forget" | "remember" | "mastered";

export interface StudySummary {
  date: string;
  book: string;
  target: number;
  done: number;
  remaining: number;
  available: number;
  mastered: number;
}

export interface StudyQueue {
  book: string;
  remaining: number;
  items: WordCard[];
}

export interface StudyAnswerResult extends WordCard {
  action: StudyAction;
  xp_gained: number;
  task: DailyTask;
}

export interface Wordbook {
  code: string;
  name: string;
  name_zh: string;
  description: string;
  icon: string;
  level: string;
  word_count: number;
  learned: number;
}

export interface WordPage {
  total: number;
  offset: number;
  limit: number;
  items: WordCard[];
}

export interface QuizQuestion {
  word: WordCard;

  options: string[];
}

export interface QuizSession {

  active: boolean;

  total: number;

  remaining: number;

  answered: number;
  correct_count: number;
  wrong_count: number;

  finished: boolean;
  question: QuizQuestion | null;
}

export interface QuizAnswerResult {
  correct: boolean;

  answer: string;
  session: QuizSession;
}

export interface DailyTask {
  date: string;
  targets: {
    words: number;
    scenarios: number;
    articles: number;
    minutes: number;
  };
  done: {
    words: number;
    scenarios: number;
    articles: number;
    minutes: number;
  };
  xp_earned: number;
  bonus_xp: number;
  awarded: {
    words: boolean;
    scenarios: boolean;
    articles: boolean;
  };
  is_complete: boolean;
  progress: number;
  overachievement: number;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

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
    let detail = "请求失败";
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {

    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const wordbookApi = {
  books: () => request<{ items: Wordbook[] }>("/api/wordbook/wordbooks"),

  myWords: (offset = 0, limit = 100) =>
    request<WordPage>(`/api/wordbook/cards${qs({ only_my: true, offset, limit })}`),

  quizState: () => request<QuizSession>("/api/wordbook/quiz"),

  quizStart: (count: number, mode: "fresh" | "resume" = "fresh") =>
    request<QuizSession>("/api/wordbook/quiz", {
      method: "POST",
      body: JSON.stringify({ count, mode }),
    }),

  quizAnswer: (wordId: number, choice: string) =>
    request<QuizAnswerResult>("/api/wordbook/quiz/answer", {
      method: "POST",
      body: JSON.stringify({ word_id: wordId, choice }),
    }),

  quizReset: () => request<{ ok: boolean }>("/api/wordbook/quiz", { method: "DELETE" }),

  remove: (id: number) =>
    request<WordCard>(`/api/wordbook/my/word/${id}`, { method: "DELETE" }),

  collect: (id: number) =>
    request<WordCard>(`/api/wordbook/word/${id}/collect`, { method: "POST" }),

  studySummary: (book?: string) =>
    request<StudySummary>(`/api/wordbook/study/summary${qs({ book })}`),

  studyQueue: (params: { book?: string; limit?: number }) =>
    request<StudyQueue>(`/api/wordbook/study/queue${qs(params)}`),

  answer: (id: number, action: StudyAction, book?: string) =>
    request<StudyAnswerResult>(`/api/wordbook/word/${id}/study`, {
      method: "POST",
      body: JSON.stringify({ action, book }),
    }),

  dailyTask: () => request<DailyTask>("/api/wordbook/daily-task"),

  saveDailyTask: (targets: {
    target_words?: number;
    target_scenarios?: number;
    target_articles?: number;
    target_minutes?: number;
  }) =>
    request<DailyTask>("/api/wordbook/daily-task", {
      method: "PUT",
      body: JSON.stringify(targets),
    }),

  audioUrl: (word: string, accent: "us" | "uk" = "us") =>
    `${BASE_PATH}/api/wordbook/audio/${encodeURIComponent(word)}?accent=${accent}`,
};
