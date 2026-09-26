/**
 * 精读前端客户端。
 *
 * 独立于 lib/api.ts，复用其中的 token 与错误类型，
 * 避免把大批新方法塞进已有对象里。
 */
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
  /** 选中文字在句内的字符区间；0/0 表示老笔记，回退到按文本匹配 */
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

/** 骨架事件里的句子：只有位置和原文，讲解还没生成出来。 */
export type SentenceSkeleton = Pick<
  ReadingSentence,
  "index" | "paragraph" | "text"
>;

/** 逐句讲解的流式回调。 */
export interface AnalyzeStreamHandlers {
  /** 全部句子的骨架。拿到就能先把原文排出来，不必等模型。 */
  onStart?: (skeleton: SentenceSkeleton[], total: number) => void;
  /** 跑完一句发一句，按句序到达（后端的并发批会先攒着，句序缺口补上才发）。 */
  onSentence?: (sentence: ReadingSentence) => void;
  onDone?: (generated: boolean) => void;
}

export type MaterialKind = "article" | "content";

/** AI 建议的一条标注，区间已由服务端按原文算好。 */
export interface SuggestedSpan {
  text: string;
  color: NoteColor;
  reason: string;
  start_offset: number;
  end_offset: number;
}

export interface SuggestResult {
  /** sentence_index -> 该句的建议 */
  by_sentence: Record<string, SuggestedSpan[]>;
  /** 全部句子都由模型产出才是 true */
  generated: boolean;
  /** 有多少句退化成了离线词表 */
  fallback_count: number;
  sentence_count: number;
}

/** 逐句建议的流式回调。 */
export interface SuggestStreamHandlers {
  /** 要建议的句子总数。拿到就能先把进度显示出来。 */
  onStart?: (total: number) => void;
  /** 跑完一句发一句。并发完成，顺序不保证，按 index 归位。 */
  onSentence?: (index: number, spans: SuggestedSpan[]) => void;
  onDone?: (summary: SuggestSummary) => void;
}

export interface SuggestSummary {
  generated: boolean;
  /** 有多少句退化成了离线词表 */
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
  if (handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }
  if (!response.ok) {
    let detail = "请求失败";
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // 非 JSON 响应，保留默认文案
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

  /** 上传文件或粘贴文本，二者至少提供一个。 */
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

  /**
   * 逐句讲解的流式请求：跑完一句回调一句，不必等整篇。
   *
   * 用 fetch 读 ReadableStream 而不是 EventSource——EventSource 没法带
   * Authorization 头，token 只能塞进 query，会漏进访问日志。
   *
   * 传 AbortSignal 是为了离开页面时能掐断：一篇长文的模型调用要跑几十秒，
   * 没人看了还在烧钱。
   */
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

    // 错误是当事件发下来的（响应头早就发出去了，后端没法改状态码），
    // 收集到这里再抛，调用方一处 catch 就能统一处理。
    if (failure) throw new ApiError(0, failure);
  },

  /** 请求标注建议。sentenceIndexes 留空表示整篇。 */
  suggest: (kind: MaterialKind, id: number, sentenceIndexes: number[] = []) =>
    request<SuggestResult>(`/api/reading/materials/${kind}/${id}/suggest`, {
      method: "POST",
      body: JSON.stringify({ sentence_indexes: sentenceIndexes }),
    }),

  /**
   * 逐句标注建议的流式请求：跑完一句回调一句。
   *
   * 一次性接口要等所有句子都过完模型才返回，长文的「挑选中…」得转很久；
   * 这里改成建议一到就先画在对应句子上，边出边挑。
   */
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

  /** 导出 PDF 需要带 token，因此走 fetch 拿 blob 再触发下载。 */
  exportPdf: async (kind: MaterialKind, id: number, filename: string) => {
    // 只重试「连接层」失败：fetch 直接 reject，也就是请求根本没拿到响应
    // （dev server / 后端正在重启、keep-alive 连接被对端掐断）。
    // HTTP 层有状态码的错误不重试——重试也是同一个结果，白白让按钮多转一圈。
    for (let attempt = 0; attempt < EXPORT_ATTEMPTS; attempt += 1) {
      try {
        const blob = await fetchExportBlob(kind, id);
        triggerDownload(blob, filename);
        return;
      } catch (err) {
        if (err instanceof ApiError) throw err;
        // 超时说明请求已经发出去了、只是后端在忙，重试等于再等一个 30s，不划算。
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

/**
 * 拉一次 PDF。后端排版是同步跑的，正常 1 秒内就回来；超时上限只是为了防止
 * 后端卡住时按钮永远转圈。每次尝试各算各的倒计时，不共用。
 */
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
    if (handleUnauthorized(response.status)) {
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

/** 下载由浏览器异步接管。紧接着 revoke 会让部分浏览器（Chrome）直接取消这次
 *  下载，表现成「点了没反应、也没报错」，所以等它起步之后再释放。 */
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

/**
 * 读一条 SSE 流，逐帧交给 onEvent。
 *
 * 逐句讲解和逐句建议走的是同一套分帧逻辑（半帧要留在 buffer 里等下一个
 * chunk），抽在这里免得两边各写一遍、各埋一个半帧解析的坑。
 *
 * 事件名与 data 都交给调用方解释：两条流的字段并不相同。
 */
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
  if (handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }
  if (!response.ok) {
    let detail = options.fallbackDetail;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // 非 JSON 响应，保留默认文案
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

    // SSE 用空行分帧。末尾可能只有半帧，留在 buffer 里等下一个 chunk，
    // 否则最后一句会被切成两半解析失败。
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

/** 导出超时上限：正常只要 0.2 秒上下，超过说明后端卡住了，别再无限等。
 *  这里从 120s 收到 30s——用户盯着一个转圈的按钮等两分钟，只会以为页面死了，
 *  30 秒还没结果就该给出明确的错，而不是继续转。 */
const EXPORT_TIMEOUT_MS = 30_000;

/** 连接层失败的尝试次数：dev server / 后端重启造成的抖动，隔一下重试一次就过去了。 */
const EXPORT_ATTEMPTS = 2;
const EXPORT_RETRY_DELAY_MS = 800;

/** 尽量把后端给的原因透出来；后端出错时是 {"detail": "..."}。 */
async function exportErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();
    const detail = typeof data?.detail === "string" ? data.detail : "";
    if (detail) return detail;
  } catch {
    // 不是 JSON（比如网关直接吐 HTML），退到按状态码给话术
  }
  if (response.status === 401) return "登录已过期，请重新登录";
  if (response.status === 404) return "找不到这篇文章，可能已被删除";
  if (response.status >= 500) return "服务器出错了，请稍后重试";
  return "导出失败";
}

/** SSE 帧里的 data。逐句讲解与逐句建议共用，按需取用各自的字段。 */
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

/** 拆一帧 SSE：取出事件名与 JSON 数据。注释行（以 : 开头）直接忽略。 */
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
    // 半截帧或后端发来的非 JSON，跳过这一帧，别把整条流带崩
    return null;
  }
}

/** 高亮配色，与后端导出 PDF 用的一套颜色保持一致。 */
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

/** 每种颜色的默认语义。精读时颜色是分类轴，不只是装饰。 */
export const COLOR_LABELS: Record<NoteColor, string> = {
  blue: "生词",
  green: "好句",
  amber: "语法",
  rose: "疑问",
  violet: "待复习",
};

/** 遮罩复习模式下用的实色块，比常规高亮更重，遮得住文字。 */
export const COLOR_MASK: Record<NoteColor, string> = {
  blue: "bg-blue-300",
  green: "bg-green-300",
  amber: "bg-amber-300",
  rose: "bg-rose-300",
  violet: "bg-violet-300",
};
