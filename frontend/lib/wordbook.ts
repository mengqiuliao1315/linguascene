/**
 * 词书 / 单词卡 / 每日任务 / 排行榜 的类型与 API。
 */
import { ApiError, getToken } from "./api";

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
  /** new | learning | review | mastered —— mastered 不再进任何学习队列 */
  status: WordStatus;
  due_date: string;
}

export type WordStatus = "new" | "learning" | "review" | "mastered";
export type StudyMode = "new" | "review";
export type StudyAction = "forget" | "remember" | "mastered";

export interface StudyProgress {
  target: number;
  done: number;
  remaining: number;
}

export interface StudySummary {
  date: string;
  book: string;
  new: StudyProgress & { available: number };
  review: StudyProgress & { due: number };
  mastered: number;
}

export interface StudyQueue {
  mode: StudyMode;
  book: string;
  remaining: number;
  items: WordCard[];
}

export interface StudyAnswerResult extends WordCard {
  action: StudyAction;
  mode: StudyMode;
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
  /** 4 个中文释义选项，其中一个是正确答案 */
  options: string[];
}

export interface QuizSession {
  /** 是否有一轮进行中的测验 */
  active: boolean;
  /** 本轮总题数 */
  total: number;
  /** 还没答对的词数 */
  remaining: number;
  /** 已答对数 */
  answered: number;
  correct_count: number;
  wrong_count: number;
  /** 队列清空 = 本轮完成 */
  finished: boolean;
  question: QuizQuestion | null;
}

export interface QuizAnswerResult {
  correct: boolean;
  /** 正确答案文案，选错时用来提示 */
  answer: string;
  session: QuizSession;
}

export interface DailyTask {
  date: string;
  targets: {
    words: number;
    new_words: number;
    review_words: number;
    scenarios: number;
    articles: number;
    minutes: number;
  };
  done: {
    words: number;
    new_words: number;
    review_words: number;
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

export type LeaderboardKind = "xp" | "streak" | "contribution";

export interface BoardEntry {
  rank: number;
  user_id: number;
  username: string;
  avatar: string | null;
  score: number;
  level?: number;
  longest?: number;
}

export interface BoardResult {
  kind: LeaderboardKind;
  entries: BoardEntry[];
  me: { rank: number; score: number; in_top: boolean } | null;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    let detail = "请求失败";
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // 非 JSON 响应，保留默认文案
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

  cards: (params: {
    book?: string;
    unit?: string;
    offset?: number;
    limit?: number;
    keyword?: string;
    only_my?: boolean;
  } = {}) => request<WordPage>(`/api/wordbook/cards${qs(params)}`),

  /** 我的单词本：词书收词、精读、划词翻译都会落到这里。 */
  myWords: (offset = 0, limit = 100) =>
    request<WordPage>(`/api/wordbook/cards${qs({ only_my: true, offset, limit })}`),

  /** 当前测验进度（没开始过时 active 为 false）。 */
  quizState: () => request<QuizSession>("/api/wordbook/quiz"),

  /** 开始测验：fresh 重新抽题，resume 接着上次没答完的继续。 */
  quizStart: (count: number, mode: "fresh" | "resume" = "fresh") =>
    request<QuizSession>("/api/wordbook/quiz", {
      method: "POST",
      body: JSON.stringify({ count, mode }),
    }),

  /** 作答一道题。选错会回到队尾，稍后重新出现。 */
  quizAnswer: (wordId: number, choice: string) =>
    request<QuizAnswerResult>("/api/wordbook/quiz/answer", {
      method: "POST",
      body: JSON.stringify({ word_id: wordId, choice }),
    }),

  /** 放弃当前测验，清掉保存的进度。 */
  quizReset: () => request<{ ok: boolean }>("/api/wordbook/quiz", { method: "DELETE" }),

  /** 把单词移出我的单词本。 */
  remove: (id: number) =>
    request<WordCard>(`/api/wordbook/my/word/${id}`, { method: "DELETE" }),

  word: (id: number) => request<WordCard>(`/api/wordbook/word/${id}`),

  collect: (id: number) =>
    request<WordCard>(`/api/wordbook/word/${id}/collect`, { method: "POST" }),

  review: (id: number, correct: boolean) =>
    request<WordCard & { correct: boolean; xp_gained: number }>(
      `/api/wordbook/word/${id}/review`,
      { method: "POST", body: JSON.stringify({ correct }) }
    ),

  studySummary: (book?: string) =>
    request<StudySummary>(`/api/wordbook/study/summary${qs({ book })}`),

  studyQueue: (params: { mode: StudyMode; book?: string; limit?: number }) =>
    request<StudyQueue>(`/api/wordbook/study/queue${qs(params)}`),

  answer: (id: number, action: StudyAction, mode: StudyMode, book?: string) =>
    request<StudyAnswerResult>(`/api/wordbook/word/${id}/study`, {
      method: "POST",
      body: JSON.stringify({ action, mode, book }),
    }),

  dailyTask: () => request<DailyTask>("/api/wordbook/daily-task"),

  saveDailyTask: (targets: {
    target_words?: number;
    target_new_words?: number;
    target_review_words?: number;
    target_scenarios?: number;
    target_articles?: number;
    target_minutes?: number;
  }) =>
    request<DailyTask>("/api/wordbook/daily-task", {
      method: "PUT",
      body: JSON.stringify(targets),
    }),

  leaderboard: (kind: LeaderboardKind = "xp", limit = 50) =>
    request<BoardResult>(`/api/wordbook/leaderboard${qs({ type: kind, limit })}`),

  /** 浏览器直连音频；后端没有音频时返回 404，调用方回退到 Web Speech。 */
  audioUrl: (word: string, accent: "us" | "uk" = "us") =>
    `/api/wordbook/audio/${encodeURIComponent(word)}?accent=${accent}`,
};
