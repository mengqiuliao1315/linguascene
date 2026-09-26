/**
 * 计划、统计、好友、私信、论坛的前端客户端。
 */

import { ApiError, getToken, handleUnauthorized } from "./api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

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
      detail = (await response.json()).detail ?? detail;
    } catch {
      // 非 JSON 响应，保留默认文案
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ------------------------------------------------------------------ 类型

export interface Quest {
  id: number | null;
  key: string;
  label: string;
  icon: string;
  target: number;
  progress: number;
  xp: number;
  completed: boolean;
  custom: boolean;
  metric: string;
}

export interface QuestMetric {
  key: string;
  label: string;
  unit: string;
}

export interface HeatCell {
  date: string;
  count: number;
  level: number;
}

export interface Heatmap {
  cells: HeatCell[];
  total_days: number;
  current_streak: number;
  longest_streak: number;
  total_active_days: number;
}

export interface ChartBar {
  user_id: number;
  username: string;
  avatar: string | null;
  value: number;
  is_me: boolean;
}

export interface LeaderRow extends ChartBar {
  rank: number;
  level: number;
  level_name: string;
  streak: number;
}

export interface Leaderboard {
  bars: ChartBar[];
  entries: LeaderRow[];
}

export interface UserStats {
  user_id: number;
  username: string;
  avatar: string | null;
  role: string;
  cefr_level: string;
  level: number;
  level_name: string;
  xp: number;
  streak: number;
  longest_streak: number;
  created_at: string | null;
  contribution: number;
  published_articles: number;
  forum_posts: number;
  forum_comments: number;
  likes_received: number;
  words_today: number;
  articles_today: number;
  words_total: number;
  scenarios_done: number;
  active_days: number;
}

export interface Friend {
  user_id: number;
  username: string;
  avatar: string | null;
  level: number;
  level_name: string;
  xp: number;
  streak: number;
  online_today: boolean;
  friendship_id: number | null;
}

export interface FriendRequest {
  friendship_id: number;
  user_id: number;
  username: string;
  avatar: string | null;
  created_at: string;
  incoming: boolean;
}

export type FriendState = "none" | "friends" | "outgoing" | "incoming" | "self";

export interface FriendStatus {
  state: FriendState;
  friendship_id: number | null;
}

export interface ChatMessage {
  id: number;
  sender_id: number;
  recipient_id: number;
  content: string;
  created_at: string;
  mine: boolean;
}

export interface ChatThread {
  user_id: number;
  username: string;
  avatar: string | null;
  last_message: string;
  last_at: string | null;
  unread: number;
}

export interface ForumAuthor {
  user_id: number;
  username: string;
  avatar: string | null;
  level: number;
  level_name: string;
}

export interface ForumPost {
  id: number;
  title: string;
  summary: string;
  truncated: boolean;
  cover: string | null;
  content?: string;
  tags: string[];
  author: ForumAuthor;
  view_count: number;
  like_count: number;
  comment_count: number;
  liked: boolean;
  is_pinned: boolean;
  is_mine: boolean;
  created_at: string;
  updated_at: string | null;
}

export type ForumSort = "new" | "hot" | "active";

export interface ForumPage {
  items: ForumPost[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface PopularTag {
  tag: string;
  count: number;
}

export interface ForumComment {
  id: number;
  content: string;
  author: ForumAuthor;
  is_mine: boolean;
  created_at: string;
}

// ------------------------------------------------------------------ 接口

export const socialApi = {
  // 计划
  quests: () => request<Quest[]>("/api/quests"),
  questMetrics: () => request<QuestMetric[]>("/api/quests/metrics"),
  createQuest: (payload: {
    label: string;
    metric: string;
    target: number;
    xp: number;
    icon: string;
  }) => request<Quest>("/api/quests", { method: "POST", body: JSON.stringify(payload) }),
  updateQuest: (
    id: number,
    payload: Partial<{ label: string; metric: string; target: number; xp: number; icon: string }>
  ) => request<Quest>(`/api/quests/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  // 完成与否由用户自己打勾，服务端只记「今天这条计划被打了勾」
  checkQuest: (id: number, completed: boolean) =>
    request<Quest>(`/api/quests/${id}/check`, {
      method: "POST",
      body: JSON.stringify({ completed }),
    }),
  deleteQuest: (id: number) => request<void>(`/api/quests/${id}`, { method: "DELETE" }),

  // 统计
  heatmap: (days = 182) => request<Heatmap>(`/api/stats/heatmap?days=${days}`),
  userHeatmap: (userId: number, days = 182) =>
    request<Heatmap>(`/api/stats/heatmap/${userId}?days=${days}`),
  leaderboard: (metric: "xp" | "streak" | "contribution" = "xp") =>
    request<Leaderboard>(`/api/stats/leaderboard?metric=${metric}`),
  userStats: (userId: number) => request<UserStats>(`/api/stats/users/${userId}`),

  // 好友
  friends: () => request<Friend[]>("/api/friends"),
  friendRequests: () =>
    request<{ incoming: FriendRequest[]; outgoing: FriendRequest[] }>("/api/friends/requests"),
  friendStatus: (userId: number) => request<FriendStatus>(`/api/friends/status/${userId}`),
  addFriend: (userId: number) =>
    request<FriendStatus>(`/api/friends/${userId}`, { method: "POST" }),
  acceptFriend: (friendshipId: number) =>
    request<void>(`/api/friends/requests/${friendshipId}/accept`, { method: "POST" }),
  declineFriend: (friendshipId: number) =>
    request<void>(`/api/friends/requests/${friendshipId}/decline`, { method: "POST" }),
  removeFriend: (userId: number) =>
    request<void>(`/api/friends/${userId}`, { method: "DELETE" }),

  // 私信
  threads: () => request<ChatThread[]>("/api/chat/threads"),
  unread: () => request<{ unread: number }>("/api/chat/unread"),
  messages: (userId: number) => request<ChatMessage[]>(`/api/chat/${userId}`),
  sendMessage: (userId: number, content: string) =>
    request<ChatMessage>(`/api/chat/${userId}`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),

  // 论坛
  posts: (params?: {
    tag?: string;
    q?: string;
    sort?: ForumSort;
    offset?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.tag) query.set("tag", params.tag);
    if (params?.q) query.set("q", params.q);
    if (params?.sort) query.set("sort", params.sort);
    if (params?.offset) query.set("offset", String(params.offset));
    if (params?.limit) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<ForumPage>(`/api/forum/posts${suffix}`);
  },
  popularTags: (limit = 12) =>
    request<PopularTag[]>(`/api/forum/tags?limit=${limit}`),
  post: (id: number, countView = true) =>
    request<ForumPost>(`/api/forum/posts/${id}?count_view=${countView}`),
  createPost: (payload: { title: string; content: string; tags: string[] }) =>
    request<ForumPost>("/api/forum/posts", { method: "POST", body: JSON.stringify(payload) }),
  updatePost: (id: number, payload: { title?: string; content?: string; tags?: string[] }) =>
    request<ForumPost>(`/api/forum/posts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deletePost: (id: number) => request<void>(`/api/forum/posts/${id}`, { method: "DELETE" }),
  likePost: (id: number) =>
    request<{ liked: boolean; like_count: number }>(`/api/forum/posts/${id}/like`, {
      method: "POST",
    }),
  pinPost: (id: number, pinned: boolean) =>
    request<ForumPost>(`/api/forum/posts/${id}/pin?pinned=${pinned}`, { method: "POST" }),
  comments: (postId: number) => request<ForumComment[]>(`/api/forum/posts/${postId}/comments`),
  addComment: (postId: number, content: string) =>
    request<ForumComment>(`/api/forum/posts/${postId}/comments`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  deleteComment: (commentId: number) =>
    request<void>(`/api/forum/comments/${commentId}`, { method: "DELETE" }),
  uploadImage: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ url: string }>("/api/forum/images", {
      method: "POST",
      body: form,
    });
  },
};

/**
 * 热力图配色：与全站蓝白基调一致，越活跃越深。
 *
 * level 0 是空白色（slate-100）留给无记录；level 1 必须用 brand-200——
 * brand-100 在白卡片上几乎和空白色一样，只学 1~2 次的日子会看不出有记录。
 * 整体压浅一档（最深处只到 brand-500），比原来的 brand-700 更透气。
 */
export const HEAT_COLORS = [
  "bg-slate-100",
  "bg-brand-200",
  "bg-brand-300",
  "bg-brand-400",
  "bg-brand-500",
];
