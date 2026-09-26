"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Avatar, EmptyState, Spinner } from "@/components/ui";
import { RequireAuth } from "@/lib/auth";
import { socialApi, type ChatMessage, type Friend, type FriendRequest } from "@/lib/social";

function FriendsView() {
  const searchParams = useSearchParams();
  const initial = Number(searchParams.get("to") ?? 0);

  const [friends, setFriends] = useState<Friend[]>([]);
  const [incoming, setIncoming] = useState<FriendRequest[]>([]);
  const [outgoing, setOutgoing] = useState<FriendRequest[]>([]);
  const [active, setActive] = useState<number | null>(initial || null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<number | null>(active);
  activeRef.current = active;

  const loadLists = useCallback(async () => {
    try {
      const [fs, reqs] = await Promise.all([
        socialApi.friends(),
        socialApi.friendRequests(),
      ]);
      setFriends(fs);
      setIncoming(reqs.incoming);
      setOutgoing(reqs.outgoing);
      setActive((prev) => {
        if (prev && fs.some((friend) => friend.user_id === prev)) return prev;
        if (initial && fs.some((friend) => friend.user_id === initial)) return initial;
        return fs[0]?.user_id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [initial]);

  useEffect(() => {
    void loadLists();
  }, [loadLists]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    socialApi
      .messages(active)
      .then((rows) => {
        if (!cancelled && activeRef.current === active) setMessages(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [active]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !active) return;

    const target = active;
    setDraft("");
    try {
      const sent = await socialApi.sendMessage(target, text);
      if (activeRef.current === target) {
        setMessages((prev) => [...prev, sent]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
      setDraft(text);
    }
  }

  async function handleRespond(request: FriendRequest, accept: boolean) {
    try {
      if (accept) await socialApi.acceptFriend(request.friendship_id);
      else await socialApi.declineFriend(request.friendship_id);
      await loadLists();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  const activeFriend = friends.find((f) => f.user_id === active);

  if (loading) return <Spinner />;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}

      {incoming.length > 0 ? (
        <section className="card space-y-3 p-5">
          <h2 className="text-sm font-semibold text-slate-900">好友申请</h2>
          <ul className="space-y-2">
            {incoming.map((req) => (
              <li key={req.friendship_id} className="flex items-center gap-3">
                <Avatar
                  username={req.username}
                  avatar={req.avatar}
                  className="h-8 w-8 text-xs"
                />
                <Link href={`/u/${req.user_id}`} className="flex-1 text-sm text-slate-700">
                  {req.username}
                </Link>
                <button
                  onClick={() => handleRespond(req, true)}
                  className="btn-primary !py-1.5 text-xs"
                >
                  通过
                </button>
                <button
                  onClick={() => handleRespond(req, false)}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-500 hover:border-rose-300"
                >
                  忽略
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {outgoing.length > 0 ? (
        <p className="px-1 text-xs text-slate-400">
          已发送 {outgoing.length} 条申请，等待对方通过
        </p>
      ) : null}

      {friends.length === 0 ? (
        <EmptyState text="还没有好友，去排行榜里找人加吧" />
      ) : (
        <div className="grid gap-5 lg:grid-cols-3">
          <aside className="card space-y-1 p-3 lg:col-span-1">
            <p className="px-2 pb-2 text-xs font-medium text-slate-500">
              好友 {friends.length}
            </p>
            {friends.map((friend) => (
              <button
                key={friend.user_id}
                onClick={() => setActive(friend.user_id)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition ${
                  active === friend.user_id ? "bg-brand-50" : "hover:bg-slate-50"
                }`}
              >
                <span className="relative flex shrink-0">
                  <Avatar
                    username={friend.username}
                    avatar={friend.avatar}
                    className="h-9 w-9 text-sm"
                  />
                  {friend.online_today ? (
                    <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500" />
                  ) : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-slate-800">
                    {friend.username}
                  </span>
                  <span className="block text-[11px] text-slate-400">
                    Lv.{friend.level} · 🔥 {friend.streak}
                  </span>
                </span>
              </button>
            ))}
          </aside>

          <section className="card flex h-[32rem] flex-col p-0 lg:col-span-2">
            {activeFriend ? (
              <>
                <header className="flex items-center gap-3 border-b border-slate-100 p-4">
                  <Avatar
                    username={activeFriend.username}
                    avatar={activeFriend.avatar}
                    className="h-9 w-9 text-sm"
                  />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-slate-900">
                      {activeFriend.username}
                    </p>
                    <p className="text-[11px] text-slate-400">
                      {activeFriend.online_today ? "今天活跃" : "最近没来"}
                    </p>
                  </div>
                  <Link
                    href={`/u/${activeFriend.user_id}`}
                    className="text-xs text-slate-400 hover:text-brand-600"
                  >
                    主页
                  </Link>
                </header>

                <div className="flex-1 space-y-3 overflow-y-auto p-4">
                  {messages.length === 0 ? (
                    <p className="py-10 text-center text-xs text-slate-400">
                      还没有消息，打个招呼吧
                    </p>
                  ) : (
                    messages.map((message) => (
                      <div
                        key={message.id}
                        className={`flex ${message.mine ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[75%] rounded-2xl px-3.5 py-2 text-sm ${
                            message.mine
                              ? "bg-brand-600 text-white"
                              : "bg-slate-100 text-slate-800"
                          }`}
                        >
                          {message.content}
                        </div>
                      </div>
                    ))
                  )}
                  <div ref={bottomRef} />
                </div>

                <form onSubmit={handleSend} className="flex gap-2 border-t border-slate-100 p-3">
                  <input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="说点什么…"
                    className="input flex-1 !py-2 text-sm"
                  />
                  <button type="submit" disabled={!draft.trim()} className="btn-primary !py-2 text-sm">
                    发送
                  </button>
                </form>
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-slate-400">
                选一个好友开始聊天
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default function FriendsPage() {
  return (
    <RequireAuth>
      <AppShell>
        <FriendsView />
      </AppShell>
    </RequireAuth>
  );
}
