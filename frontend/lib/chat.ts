/**
 * 对话页的流式客户端。
 *
 * 一轮对话的「回复」与「反馈」在后端是两路并行生成的，分帧下发：
 * `reply_chunk`（逐块文本）× N → `reply`（完整回复，已落库）→
 * `feedback`（纠错、地道表达、新词、点评、下一步提示）。
 *
 * 回复走流式纯文本：首 token 到达就往前端推，用户不必等整句生成完才看到
 * AI 开口。反馈晚几秒到也不影响对话继续。
 *
 * 顺带做两件小事：
 * 1. 读流用 fetch 而不是 EventSource —— EventSource 没法带 Authorization 头；
 * 2. 翻译结果按文本缓存并支持预取，用户点「翻译」时通常已经命中。
 */
import { ApiError, api, getToken, handleUnauthorized, request } from "./api";
import type { ChatFeedbackEvent, ChatReplyEvent, ChatResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export interface TurnStreamHandlers {
  onReplyChunk?: (text: string) => void;
  onReply?: (payload: ChatReplyEvent) => void;
  onFeedback?: (payload: ChatFeedbackEvent) => void;
  onDone?: (payload: { task_progress: number; task_completed: boolean }) => void;
}

/**
 * 发一条消息并读流。
 *
 * 传 AbortSignal 是为了「换篇 / 重发」时能掐断：一轮对话要跑两路模型调用，
 * 没人要了还在烧钱。
 */
export async function streamTurn(
  conversationId: number,
  text: string,
  handlers: TurnStreamHandlers = {},
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const response = await fetch(
    `${API_BASE}/api/conversations/${conversationId}/message/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message: text }),
      signal,
    }
  );

  if (handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }
  if (!response.ok) {
    let detail = "发送失败";
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
  let failure = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    // SSE 用空行分帧。末尾可能只有半帧，留在 buffer 里等下一个 chunk，
    // 否则最后一条会被切成两半解析失败。
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");

      const event = parseSseFrame(frame);
      if (!event) continue;
      if (event.name === "reply_chunk") {
        handlers.onReplyChunk?.(String(event.data.text ?? ""));
      } else if (event.name === "reply") {
        handlers.onReply?.(event.data as unknown as ChatReplyEvent);
      } else if (event.name === "feedback") {
        handlers.onFeedback?.(event.data as unknown as ChatFeedbackEvent);
      } else if (event.name === "done") {
        handlers.onDone?.({
          task_progress: Number(event.data.task_progress ?? 0),
          task_completed: Boolean(event.data.task_completed),
        });
      } else if (event.name === "error") {
        failure = String(event.data.detail ?? "生成失败");
      }
    }
  }

  if (buffer.trim()) {
    const event = parseSseFrame(buffer);
    if (event) {
      if (event.name === "reply_chunk") {
        handlers.onReplyChunk?.(String(event.data.text ?? ""));
      } else if (event.name === "reply") {
        handlers.onReply?.(event.data as unknown as ChatReplyEvent);
      } else if (event.name === "feedback") {
        handlers.onFeedback?.(event.data as unknown as ChatFeedbackEvent);
      } else if (event.name === "done") {
        handlers.onDone?.({
          task_progress: Number(event.data.task_progress ?? 0),
          task_completed: Boolean(event.data.task_completed),
        });
      } else if (event.name === "error") {
        failure = String(event.data.detail ?? "生成失败");
      }
    }
  }

  // 错误是当事件发下来的（响应头早就发出去了，后端没法改状态码），
  // 收集到这里再抛，调用方一处 catch 就能统一处理。
  if (failure) throw new ApiError(0, failure);
}

/** 拆一帧 SSE：取出事件名与 JSON 数据。注释行（以 : 开头）直接忽略。 */
function parseSseFrame(frame: string): {
  name: string;
  data: Record<string, unknown>;
} | null {
  let name = "";
  const payload: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) payload.push(line.slice(5).trimStart());
  }
  if (!name || payload.length === 0) return null;
  try {
    return { name, data: JSON.parse(payload.join("\n")) as Record<string, unknown> };
  } catch {
    return null;
  }
}

// ------------------------------------------------------------- 翻译预取

/**
 * 翻译结果缓存。
 *
 * 缓存的是 Promise 而不是字符串：预取和用户点击可能几乎同时发生，
 * 缓存 Promise 才能让两者共用同一次请求，而不是各发一遍。
 */
const translationCache = new Map<string, Promise<string>>();
const TRANSLATION_CACHE_LIMIT = 200;

function trimTranslationCache(): void {
  while (translationCache.size > TRANSLATION_CACHE_LIMIT) {
    const oldest = translationCache.keys().next().value;
    if (oldest === undefined) return;
    translationCache.delete(oldest);
  }
}

function fetchTranslation(text: string): Promise<string> {
  const key = text.trim();
  if (!key) return Promise.resolve("");

  const hit = translationCache.get(key);
  if (hit) return hit;

  const task = request<{ translation: string }>("/api/ai/translate", {
    method: "POST",
    body: JSON.stringify({ text: key }),
  })
    .then((result) => result.translation ?? "")
    .catch(() => "");
  translationCache.set(key, task);
  // 失败或空结果不留在缓存里，否则一次网络抖动会被钉死成「永远翻译不出来」
  task.then((value) => {
    if (!value) translationCache.delete(key);
  });

  trimTranslationCache();
  return task;
}

/** 取翻译，命中缓存时是即时的。 */
export function loadTranslation(text: string): Promise<string> {
  return fetchTranslation(text);
}

/**
 * 提前把翻译取回来。
 *
 * AI 回复一到就调用：等用户去点「翻译」时结果通常已经在手上，
 * 点开就是即时的，不必再等一次模型往返。
 */
export function prefetchTranslation(text: string): void {
  if (!text.trim()) return;
  void fetchTranslation(text);
}

/** 一次性发送（非流式）。流式端点不可用时兜底。 */
export function sendMessageOnce(
  conversationId: number,
  text: string
): Promise<ChatResponse> {
  return api.sendMessage(conversationId, text);
}
