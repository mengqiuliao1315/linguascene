import { ApiError, getToken, handleUnauthorized } from "./api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export type NoteColor = "blue" | "green" | "amber" | "rose" | "violet";
export type NoteKind = "word" | "phrase" | "sentence" | "note";

export interface ReadingWord {
  word: string;
  lemma: string;
  meaning: string;
  phonetic: string;
  part_of_speech: string;
}

export interface ReadingPhrase {
  phrase: string;
  meaning: string;
  example: string;
}

export interface ReadingGrammar {
  point: string;
  explanation: string;
  example: string;
}

export interface ReadingNote {
  id: number;
  sentence_index: number;
  kind: NoteKind;
  text: string;
  meaning: string;
  note: string;
  color: NoteColor;

  start_offset: number;
  end_offset: number;
  created_at: string;
  in_vocabulary: boolean;
}

export interface ReadingSentence {
  index: number;
  paragraph: number;
  text: string;
  translation: string;
  main_clause: string;
  words: ReadingWord[];
  phrases: ReadingPhrase[];
  grammar: ReadingGrammar[];
  explanation: string;
  notes: ReadingNote[];
}

export type MaterialSource = "platform" | "mine" | "shared";

export interface Material {
  id: number;
  title: string;
  source: MaterialSource;
  author_name: string;
  content_type: string;
  level: string;
  word_count: number;
  read_minutes: number;
  is_public: boolean;
  is_mine: boolean;
  note_count: number;
  created_at: string | null;
}

export interface MaterialDetail extends Material {
  content: string;
  sentences: ReadingSentence[];
}

export interface ReadingAnalysis {
  level: string;
  sentences: ReadingSentence[];
  generated: boolean;
}

export type SentenceSkeleton = Pick<
  ReadingSentence,
  "index" | "paragraph" | "text"
>;

export interface AnalyzeStreamHandlers {

  onStart?: (skeleton: SentenceSkeleton[], total: number) => void;

  onSentence?: (sentence: ReadingSentence) => void;
  onDone?: (generated: boolean) => void;
}

export type MaterialKind = "article" | "content";

export interface SuggestedSpan {
  text: string;
  color: NoteColor;
  reason: string;
  start_offset: number;
  end_offset: number;
}

export interface SuggestResult {

  by_sentence: Record<string, SuggestedSpan[]>;

  generated: boolean;

  fallback_count: number;
  sentence_count: number;
}

export interface SuggestStreamHandlers {

  onStart?: (total: number) => void;

  onSentence?: (index: number, spans: SuggestedSpan[]) => void;
  onDone?: (summary: SuggestSummary) => void;
}

export interface SuggestSummary {
  generated: boolean;

  fallbackCount: number;
  sentenceCount: number;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (token && handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }
  if (!response.ok) {
    let detail = "请求失败";
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {

    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const readingApi = {
  materials: (source: string = "all") =>
    request<Material[]>(`/api/reading/materials?source=${source}`),

  material: (kind: MaterialKind, id: number) =>
    request<MaterialDetail>(`/api/reading/materials/${kind}/${id}`),

  upload: (file: File | null, title: string, text = "") => {
    const form = new FormData();
    form.append("title", title);
    if (file) form.append("file", file);
    if (text.trim()) form.append("text", text);
    return request<MaterialDetail>("/api/reading/materials/upload", {
      method: "POST",
      body: form,
    });
  },

  analyze: (kind: MaterialKind, id: number, force = false) =>
    request<ReadingAnalysis>(
      `/api/reading/materials/${kind}/${id}/analyze?force=${force}`,
      { method: "POST" }
    ),

  analyzeStream: async (
    kind: MaterialKind,
    id: number,
    options: { force?: boolean; signal?: AbortSignal } & AnalyzeStreamHandlers = {}
  ): Promise<void> => {
    const { force = false, signal, ...handlers } = options;
    let failure = "";

    await streamSse(
      `/api/reading/materials/${kind}/${id}/analyze/stream?force=${force}`,
      { signal, fallbackDetail: "生成失败" },
      (name, data) => {
        if (name === "start") {
          handlers.onStart?.(data.sentences ?? [], data.total ?? 0);
        } else if (name === "sentence") {
          if (data.sentence) handlers.onSentence?.(data.sentence);
        } else if (name === "done") {
          handlers.onDone?.(Boolean(data.generated));
        } else if (name === "error") {
          failure = data.detail || "生成失败";
        }
      }
    );

    if (failure) throw new ApiError(0, failure);
  },

  suggest: (kind: MaterialKind, id: number, sentenceIndexes: number[] = []) =>
    request<SuggestResult>(`/api/reading/materials/${kind}/${id}/suggest`, {
      method: "POST",
      body: JSON.stringify({ sentence_indexes: sentenceIndexes }),
    }),

  suggestStream: async (
    kind: MaterialKind,
    id: number,
    options: { sentenceIndexes?: number[]; signal?: AbortSignal } &
      SuggestStreamHandlers = {}
  ): Promise<void> => {
    const { sentenceIndexes = [], signal, ...handlers } = options;
    const query = sentenceIndexes.map((index) => `sentence_indexes=${index}`).join("&");
    let failure = "";

    await streamSse(
      `/api/reading/materials/${kind}/${id}/suggest/stream${query ? `?${query}` : ""}`,
      { signal, fallbackDetail: "生成建议失败" },
      (name, data) => {
        if (name === "start") {
          handlers.onStart?.(data.total ?? 0);
        } else if (name === "sentence") {
          handlers.onSentence?.(data.index ?? 0, data.spans ?? []);
        } else if (name === "done") {
          handlers.onDone?.({
            generated: Boolean(data.generated),
            fallbackCount: data.fallback_count ?? 0,
            sentenceCount: data.sentence_count ?? 0,
          });
        } else if (name === "error") {
          failure = data.detail || "生成建议失败";
        }
      }
    );

    if (failure) throw new ApiError(0, failure);
  },

  publish: (id: number, isPublic: boolean) =>
    request<Material>(
      `/api/reading/materials/content/${id}/publish?is_public=${isPublic}`,
      { method: "POST" }
    ),

  remove: (id: number) =>
    request<void>(`/api/reading/materials/content/${id}`, { method: "DELETE" }),

  hideSentence: (kind: MaterialKind, id: number, sentenceIndex: number) =>
    request<void>(
      `/api/reading/materials/${kind}/${id}/sentences/${sentenceIndex}/hide`,
      { method: "POST" }
    ),

  createNote: (
    kind: MaterialKind,
    id: number,
    payload: {
      sentence_index: number;
      kind: NoteKind;
      text: string;
      meaning?: string;
      note?: string;
      color?: NoteColor;
      start_offset?: number;
      end_offset?: number;
    }
  ) =>
    request<ReadingNote>(`/api/reading/materials/${kind}/${id}/notes`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateNote: (
    noteId: number,
    payload: { note?: string; meaning?: string; color?: NoteColor }
  ) =>
    request<ReadingNote>(`/api/reading/notes/${noteId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteNote: (noteId: number) =>
    request<void>(`/api/reading/notes/${noteId}`, { method: "DELETE" }),

  noteToVocabulary: (noteId: number) =>
    request<ReadingNote>(`/api/reading/notes/${noteId}/to-vocabulary`, {
      method: "POST",
    }),

  exportPdf: async (kind: MaterialKind, id: number, filename: string) => {

    for (let attempt = 0; attempt < EXPORT_ATTEMPTS; attempt += 1) {
      try {
        const blob = await fetchExportBlob(kind, id);
        triggerDownload(blob, filename);
        return;
      } catch (err) {
        if (err instanceof ApiError) throw err;

        if (err instanceof DOMException && err.name === "AbortError") {
          throw new ApiError(0, "导出超时：30 秒没等到后端返回，请稍后重试");
        }
        if (attempt + 1 >= EXPORT_ATTEMPTS) {
          throw new ApiError(0, "导出失败：没能连上后端服务，请确认后端正在运行后重试");
        }
        await delay(EXPORT_RETRY_DELAY_MS);
      }
    }
  },
};

async function fetchExportBlob(kind: MaterialKind, id: number): Promise<Blob> {
  const token = getToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), EXPORT_TIMEOUT_MS);

  try {
    const response = await fetch(
      `${API_BASE}/api/reading/materials/${kind}/${id}/export.pdf`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      }
    );
    if (token && handleUnauthorized(response.status)) {
      throw new ApiError(401, "登录已过期");
    }
    if (!response.ok) {
      throw new ApiError(response.status, await exportErrorMessage(response));
    }

    const blob = await response.blob();
    if (!blob.size) throw new ApiError(0, "导出的 PDF 是空的，请重试");
    return blob;
  } finally {
    clearTimeout(timer);
  }
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function streamSse(
  path: string,
  options: { signal?: AbortSignal; fallbackDetail: string },
  onEvent: (name: string, data: SseData) => void
): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: options.signal,
  });
  if (token && handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }
  if (!response.ok) {
    let detail = options.fallbackDetail;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {

    }
    throw new ApiError(response.status, detail);
  }
  if (!response.body) throw new ApiError(0, "当前浏览器不支持流式读取");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");

      const event = parseSseFrame(frame);
      if (event) onEvent(event.name, event.data);
    }
  }
  if (buffer.trim()) {
    const event = parseSseFrame(buffer);
    if (event) onEvent(event.name, event.data);
  }
}

const EXPORT_TIMEOUT_MS = 30_000;

const EXPORT_ATTEMPTS = 2;
const EXPORT_RETRY_DELAY_MS = 800;

async function exportErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();
    const detail = typeof data?.detail === "string" ? data.detail : "";
    if (detail) return detail;
  } catch {

  }
  if (response.status === 401) return "登录已过期，请重新登录";
  if (response.status === 404) return "找不到这篇文章，可能已被删除";
  if (response.status >= 500) return "服务器出错了，请稍后重试";
  return "导出失败";
}

interface SseData {
  total?: number;
  sentences?: SentenceSkeleton[];
  sentence?: ReadingSentence;
  generated?: boolean;
  fallback_count?: number;
  sentence_count?: number;
  index?: number;
  spans?: SuggestedSpan[];
  detail?: string;
}

function parseSseFrame(frame: string): { name: string; data: SseData } | null {
  let name = "";
  const payload: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) payload.push(line.slice(5).trimStart());
  }
  if (!name || payload.length === 0) return null;
  try {
    return { name, data: JSON.parse(payload.join("\n")) };
  } catch {

    return null;
  }
}

export const COLOR_STYLES: Record<NoteColor, string> = {
  blue: "bg-blue-100 text-blue-900",
  green: "bg-green-100 text-green-900",
  amber: "bg-amber-100 text-amber-900",
  rose: "bg-rose-100 text-rose-900",
  violet: "bg-violet-100 text-violet-900",
};

export const COLOR_DOTS: Record<NoteColor, string> = {
  blue: "bg-blue-400",
  green: "bg-green-400",
  amber: "bg-amber-400",
  rose: "bg-rose-400",
  violet: "bg-violet-400",
};

export const COLOR_ORDER: NoteColor[] = ["blue", "green", "amber", "rose", "violet"];

export const COLOR_LABELS: Record<NoteColor, string> = {
  blue: "生词",
  green: "好句",
  amber: "语法",
  rose: "疑问",
  violet: "待复习",
};

export const COLOR_MASK: Record<NoteColor, string> = {
  blue: "bg-blue-300",
  green: "bg-green-300",
  amber: "bg-amber-300",
  rose: "bg-rose-300",
  violet: "bg-violet-300",
};
