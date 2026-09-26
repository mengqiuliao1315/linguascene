"use client";

import { useState } from "react";

import { ErrorText } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      <div className="hidden flex-1 flex-col justify-between bg-brand-600 p-12 text-white lg:flex">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/20">
            L
          </span>
          LinguaScene
        </div>
        <div className="space-y-6">
          <h1 className="text-4xl font-bold leading-tight">
            Learn English
            <br />
            by living it.
          </h1>
          <div className="flex flex-wrap gap-2 text-sm">
            {["☕ Ordering Coffee", "✈️ Airport Check-in", "💼 Job Interview"].map(
              (item) => (
                <span
                  key={item}
                  className="rounded-full bg-white/15 px-3 py-1.5"
                >
                  {item}
                </span>
              )
            )}
          </div>
        </div>
        <p className="text-sm text-white/60">场景 · 对话 · 纠错 · 成长</p>
      </div>

      <div className="flex flex-1 items-center justify-center px-6">
        <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-5">
          <div className="lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 font-bold text-white">
              L
            </span>
          </div>

          <h2 className="text-2xl font-semibold text-slate-900">登录</h2>

          <div className="space-y-3">
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="邮箱"
              className="input"
            />
            <input
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="密码"
              className="input"
            />
          </div>

          <ErrorText>{error}</ErrorText>

          <button
            type="submit"
            disabled={submitting}
            className="btn-primary w-full"
          >
            {submitting ? "登录中…" : "登录"}
          </button>

          <p className="text-center text-xs text-slate-400">
            账号由管理员统一开通
          </p>
        </form>
      </div>
    </div>
  );
}
