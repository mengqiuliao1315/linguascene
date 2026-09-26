"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { RequireAuth, useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

const LEVELS = [
  { value: "A1", label: "A1", note: "入门" },
  { value: "A2", label: "A2", note: "基础" },
  { value: "B1", label: "B1", note: "进阶" },
  { value: "B2", label: "B2", note: "中高级" },
];

const INTERESTS = ["Daily Life", "Travel", "Workplace", "Technology", "Culture"];

function OnboardingForm() {
  const { setUser } = useAuth();
  const router = useRouter();
  const [level, setLevel] = useState("B1");
  const [interests, setInterests] = useState<string[]>(["Travel", "Workplace"]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function toggleInterest(value: string) {
    setInterests((prev) =>
      prev.includes(value)
        ? prev.filter((item) => item !== value)
        : [...prev, value]
    );
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError("");
    try {
      const user = await api.onboarding({
        cefr_level: level,
        interests,
      });
      setUser(user);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 py-10">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-slate-900">选择你的起点</h1>
      </div>

      <section className="space-y-3">
        <p className="section-title">英语等级</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {LEVELS.map((item) => (
            <button
              key={item.value}
              onClick={() => setLevel(item.value)}
              className={`card flex flex-col items-center gap-1 p-5 transition ${
                level === item.value
                  ? "border-brand-500 ring-2 ring-brand-100"
                  : "hover:border-brand-300"
              }`}
            >
              <span className="text-xl font-semibold text-slate-900">
                {item.label}
              </span>
              <span className="text-xs text-slate-400">{item.note}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <p className="section-title">想提升的方向</p>
        <div className="flex flex-wrap gap-2">
          {INTERESTS.map((item) => (
            <button
              key={item}
              onClick={() => toggleInterest(item)}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                interests.includes(item)
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-slate-200 bg-white text-slate-600 hover:border-brand-300"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </section>

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}

      <button
        onClick={handleSubmit}
        disabled={submitting}
        className="btn-primary w-full"
      >
        {submitting ? "保存中…" : "开始学习"}
      </button>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <RequireAuth>
      <OnboardingForm />
    </RequireAuth>
  );
}
