import { ApiError, api, getToken, handleUnauthorized, request } from "./api";
import type { ChatFeedbackEvent, ChatReplyEvent, ChatResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export interface TurnStreamHandlers {
  onReplyChunk?: (text: string) => void;
  onReply?: (payload: ChatReplyEvent) => void;
  onFeedback?: (payload: ChatFeedbackEvent) => void;
  onDone?: (payload: { task_progress: number; task_completed: boolean }) => void;
}

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

  if (token && handleUnauthorized(response.status)) {
    throw new ApiError(401, "登录已过期");
  }
  if (!response.ok) {
    let detail = "发送失败";
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
  let failure = "";

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

  if (failure) throw new ApiError(0, failure);
}

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

  task.then((value) => {
    if (!value) translationCache.delete(key);
  });

  trimTranslationCache();
  return task;
}

export function loadTranslation(text: string): Promise<string> {
  return fetchTranslation(text);
}

export function prefetchTranslation(text: string): void {
  if (!text.trim()) return;
  void fetchTranslation(text);
}

export function sendMessageOnce(
  conversationId: number,
  text: string
): Promise<ChatResponse> {
  return api.sendMessage(conversationId, text);
}
