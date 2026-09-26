"use client";

import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EmptyState, ScenarioCard, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { staticOpeningUrl } from "@/lib/openingAudio";
import { prefetchSpeech } from "@/lib/speech";
import type { Scenario } from "@/lib/types";

const CATEGORIES = ["全部", "Daily Life", "Travel", "Workplace", "Social"];

function ScenariosContent() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [category, setCategory] = useState("全部");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .scenarios()
      .then(setScenarios)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  const grouped = useMemo(() => {
    const filtered =
      category === "全部"
        ? scenarios
        : scenarios.filter((item) => item.category === category);
    return filtered;
  }, [scenarios, category]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {CATEGORIES.map((item) => (
          <button
            key={item}
            onClick={() => setCategory(item)}
            className={`rounded-xl px-4 py-2 text-sm transition ${
              category === item
                ? "bg-brand-600 text-white"
                : "border border-slate-200 bg-white text-slate-600 hover:border-brand-300"
            }`}
          >
            {item}
          </button>
        ))}
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState text={error} />
      ) : grouped.length === 0 ? (
        <EmptyState text="暂无场景" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {grouped.map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              id={scenario.id}
              icon={scenario.icon}
              title={scenario.title}
              titleZh={scenario.title_zh}
              level={scenario.level}
              minutes={scenario.estimated_minutes}
              role={scenario.ai_role}
              // 鼠标停在卡片上就把这句开场白的音频取回来：内置场景是项目里的
              // 静态文件，点进去时它已经在浏览器缓存里，开口就是即时的。
              onHover={() =>
                prefetchSpeech(scenario.opening_line, {
                  url: staticOpeningUrl(scenario.slug, scenario.opening_line),
                  urgent: true,
                })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ScenariosPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ScenariosContent />
      </AppShell>
    </RequireAuth>
  );
}
