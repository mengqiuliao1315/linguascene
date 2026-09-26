/**
 * 模型设置。
 *
 * 左侧是来源列表，右侧是选中项的详情：
 * - 我接入的供应商（可以添加多个，每个下面可以存多个模型，选一个当前使用）
 * - 我采纳的、别人分享的模型
 * - 我分享出去给别人用的模型（可随时停用/删除）
 *
 * 全站没有"管理员免费模型"，任何可用的模型都来自某个用户的配置或分享。
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AiProviderIcon } from "@/components/AiProviderIcon";
import { AppShell } from "@/components/AppShell";
import { EmptyState, Modal, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import {
  AI_FORMAT_OPTIONS,
  AI_PRESET_GROUPS,
  DEFAULT_AI_FORMAT,
  formatLabel,
  formatShortLabel,
  presetsByGroup,
  shortBaseUrl,
  type AiPreset,
} from "@/lib/aiFormats";
import type { AiApiFormat, AiProviderConfig, AiShare, AiStatus } from "@/lib/types";

const SOURCE_TEXT: Record<string, string> = {
  user: "我自己的模型",
  share: "别人分享的模型",
  env: "站点默认模型",
  mock: "离线规则引擎",
};

/** 左侧列表里给每种来源配的图标底色。 */
const SOURCE_ACCENT: Record<string, string> = {
  user: "bg-brand-500 text-white",
  share: "bg-violet-500 text-white",
  env: "bg-slate-500 text-white",
  mock: "bg-slate-400 text-white",
};

/** 来源图标里的水果标志：比首字温和，几个来源也不会看起来一模一样。 */
const SOURCE_FRUIT: Record<string, string> = {
  user: "🍎",
  share: "🍇",
  env: "🥝",
  mock: "🍋",
};

const SOURCE_FRUIT_FALLBACK = ["🍑", "🍒", "🍉", "🍓", "🥭"];

/** 来源图标：统一的圆角方块 + 水果标志，避免列表里全是同一种圆点。 */
function SourceIcon({ source }: { source: string }) {
  // 按来源名取一个固定的水果，看起来是随机分配的，但重渲染时不会跳来跳去
  const fruit =
    SOURCE_FRUIT[source] ??
    SOURCE_FRUIT_FALLBACK[
      Math.abs([...source].reduce((sum, ch) => sum + ch.charCodeAt(0), 0)) %
        SOURCE_FRUIT_FALLBACK.length
    ];
  return (
    <span
      aria-hidden
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[13px] leading-none ${
        SOURCE_ACCENT[source] ?? "bg-slate-400 text-white"
      }`}
    >
      {fruit}
    </span>
  );
}

type PaneKey = "new" | "adopted" | `config:${number}` | `share:${number}`;

function StatusDot({ color }: { color: "green" | "orange" | "slate" }) {
  const tone = {
    green: "bg-emerald-500",
    orange: "bg-amber-500",
    slate: "bg-slate-300",
  }[color];
  return <span className={`h-2 w-2 shrink-0 rounded-full ${tone}`} />;
}

function AiSettingsView() {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // 「地址和 Key 都没问题，只是模型这次太慢」这类结论：不是错误，但也不是绿
  const [warning, setWarning] = useState("");
  const [pane, setPane] = useState<PaneKey>("new");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  // 当前编辑的供应商表单
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiFormat, setApiFormat] = useState<AiApiFormat>(DEFAULT_AI_FORMAT);
  const [models, setModels] = useState<string[]>([]);
  const [activeModel, setActiveModel] = useState("");
  const [modelInput, setModelInput] = useState("");
  const [addingModel, setAddingModel] = useState(false);
  // 「自动获取」拿到的候选，和已保存的 models 分开，避免点一下就混进列表
  const [fetched, setFetched] = useState<string[]>([]);
  // 当前表单里的地址来自哪个预设：写在 Base URL 下面，让「地址是自动填好的」一目了然
  const [presetLabel, setPresetLabel] = useState("");

  /**
   * 表单当前反映的是哪个 pane。
   *
   * 切换左侧列表和「一键填充预设」都会把 pane 改成 "new"，但只有前者需要清空
   * 表单——预设刚填好的 Base URL 会被同步 effect 当成「切到了新建」清掉。
   * 记下表单已经对上哪个 pane，同步时对上了就跳过。
   */
  const formPaneRef = useRef<PaneKey | null>(null);
  // 填完预设后把光标送到唯一还需要用户动手的地方（API Key）
  const apiKeyRef = useRef<HTMLInputElement | null>(null);
  const [focusKeyToken, setFocusKeyToken] = useState(0);

  // 分享表单
  const [shareTitle, setShareTitle] = useState("");
  const [shareNote, setShareNote] = useState("");
  const [sharing, setSharing] = useState(false);

  const applyStatus = useCallback((next: AiStatus) => {
    setStatus(next);
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    api
      .aiStatus()
      .then((next) => {
        applyStatus(next);
        // 默认选中当前生效的那条，没有就打开"新建"
        if (next.active_config_id) setPane(`config:${next.active_config_id}`);
        else if (next.adopted_share && next.active_share_id) setPane("adopted");
        else if (next.configs.length > 0) setPane(`config:${next.configs[0].id}`);
        else setPane("new");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [applyStatus]);

  useEffect(load, [load]);

  const configs = status?.configs ?? [];
  const myShares = status?.shares.filter((s) => s.is_mine) ?? [];
  const otherShares = status?.shares.filter((s) => !s.is_mine) ?? [];

  /** 当前正在编辑的那条供应商；新建时为 null。 */
  const editing: AiProviderConfig | null = useMemo(() => {
    if (!status || !pane.startsWith("config:")) return null;
    const id = Number(pane.slice("config:".length));
    return status.configs.find((c) => c.id === id) ?? null;
  }, [status, pane]);

  /** 把表单填成某条供应商（或清空准备新建）。 */
  const fillForm = useCallback((config: AiProviderConfig | null) => {
    // 记下这次填的是哪条：同步 effect 据此判断表单要不要重新载入
    formPaneRef.current = config ? (`config:${config.id}` as PaneKey) : "new";
    setName(config?.name ?? "");
    setBaseUrl(config?.base_url ?? "");
    setApiFormat(config?.api_format ?? DEFAULT_AI_FORMAT);
    setModels(config?.models ?? []);
    setActiveModel(config?.active_model ?? "");
    setApiKey("");
    setFetched([]);
    setModelInput("");
    setAddingModel(false);
    setPresetLabel("");
  }, []);

  /** 切换右侧详情，顺手清掉上一条的提示，避免串台。 */
  const selectPane = useCallback((key: PaneKey) => {
    setPane(key);
    setError("");
    setNotice("");
    setWarning("");
  }, []);

  // 切换选中的供应商时同步表单。表单已经对上了就跳过，否则会把手动填好的
  // 预设（applyPreset 填完地址后同样把 pane 设成 "new"）当成切换给冲掉。
  useEffect(() => {
    if (formPaneRef.current === pane) return;
    if (pane === "new") fillForm(null);
    else if (editing) fillForm(editing);
  }, [pane, editing, fillForm]);

  useEffect(() => {
    if (!focusKeyToken) return;
    apiKeyRef.current?.focus();
  }, [focusKeyToken]);

  function applyPreset(preset: AiPreset) {
    setCatalogOpen(false);
    setError("");
    setNotice("");
    setWarning("");

    // 这里不要再调用 fillForm(null)：它会连续触发一组“清空新建表单”的
    // state 更新，和下面的预设填充更新混在一起时，React 的并发调度可能让
    // 最终画面又回到空地址。一次性把表单标记为 new，并明确写入每个字段，
    // 同步 effect 看到同一个 pane 后也不会覆盖预设值。
    formPaneRef.current = "new";
    setPane("new");
    setName(preset.custom ? "" : preset.label);
    setBaseUrl(preset.custom ? "" : preset.base_url);
    setApiFormat(preset.api_format);
    setModels(preset.custom || !preset.model ? [] : [preset.model]);
    setActiveModel(preset.custom ? "" : preset.model);
    setApiKey("");
    setFetched([]);
    setModelInput("");
    setAddingModel(false);
    setPresetLabel(preset.custom ? "" : preset.label);

    if (preset.custom) {
      // 自定义供应商只预选协议，地址、模型名都交给用户；Base URL 下面那排
      // 「快速填入」留着他随时抄一个常见服务商的地址
      setNotice("选好接入协议后填入 Base URL 与 API Key，再添加模型；地址记不住就点下面的常见服务商");
      return;
    }
    setNotice(`已填入 ${preset.label} 的地址与模型名，补上 API Key 就能用`);
    setFocusKeyToken((token) => token + 1);
  }

  /**
   * 表单里的一键填入：只补地址、协议（以及空着的名称和模型）。
   *
   * 走「创建自定义供应商」进来的人也一样要填 Base URL，这里让常见服务商
   * 的地址随手可得——不用去背、也不用回目录里重新选一次。
   */
  function quickFill(preset: AiPreset) {
    setError("");
    setNotice("");
    setWarning("");
    setBaseUrl(preset.base_url);
    setApiFormat(preset.api_format);
    setFetched([]);
    setPresetLabel(preset.label);
    if (!name.trim()) setName(preset.label);
    if (models.length === 0 && preset.model) {
      setModels([preset.model]);
      setActiveModel(preset.model);
      setNotice(`已填入 ${preset.label} 的地址与模型名，补上 API Key 就能用`);
      return;
    }
    setNotice(`已填入 ${preset.label} 的地址（${shortBaseUrl(preset.base_url)}）`);
  }

  function handleAddModel() {
    const next = modelInput.trim();
    if (!next || models.includes(next)) {
      setModelInput("");
      setAddingModel(false);
      return;
    }
    setModels((prev) => [...prev, next]);
    if (!activeModel) setActiveModel(next);
    setModelInput("");
    setAddingModel(false);
  }

  function handleRemoveModel(target: string) {
    const rest = models.filter((m) => m !== target);
    setModels(rest);
    if (activeModel === target) setActiveModel(rest[0] ?? "");
  }

  async function handleFetchModels() {
    setError("");
    setNotice("");
    setWarning("");
    setFetchingModels(true);
    try {
      const result = await api.listAiModels({
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        api_format: apiFormat,
        config_id: editing?.id ?? null,
      });
      if (result.success) {
        setFetched(result.models);
        setNotice(result.message);
      } else {
        setError(result.message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取模型列表失败");
    } finally {
      setFetchingModels(false);
    }
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    setWarning("");
    if (!baseUrl.trim()) {
      setError("请填写 Base URL");
      return;
    }
    if (models.length === 0) {
      setError("请至少添加一个模型");
      return;
    }
    if (!editing && !apiKey.trim()) {
      setError("首次配置必须填写 API Key");
      return;
    }

    setSaving(true);
    const payload = {
      name: name.trim(),
      base_url: baseUrl.trim(),
      api_key: apiKey.trim(),
      api_format: apiFormat,
      models,
      active_model: activeModel,
    };
    try {
      const next = editing
        ? await api.updateAiConfig(editing.id, payload)
        : await api.createAiConfig(payload);
      applyStatus(next);
      const savedId = editing?.id ?? next.active_config_id;
      if (savedId) setPane(`config:${savedId}`);
      setApiKey("");
      setNotice(editing ? "已保存" : "已添加，之后的 AI 调用会用它");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setError("");
    setNotice("");
    setWarning("");
    setTesting(true);
    try {
      const result = await api.testAiCredential({
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        api_format: apiFormat,
        config_id: editing?.id ?? null,
        model: activeModel,
      });
      // 服务端在「模型名被否掉」时会带回真实可用的模型名：直接放进候选列表，
      // 用户点一下就能换成能用的名字，不用再对着 400 猜。
      const suggested = result.suggested_models ?? [];
      if (suggested.length > 0) {
        setFetched((prev) => [...new Set([...prev, ...suggested])]);
      }
      if (!result.success) {
        setError(result.message);
      } else if (result.status === "warn") {
        // 地址和 Key 都没问题，只是模型这次太慢：给黄色提示，别让用户以为填错了
        setWarning(result.message);
      } else {
        setNotice(result.message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试失败");
    } finally {
      setTesting(false);
    }
  }

  async function handleUseConfig(config: AiProviderConfig) {
    setError("");
    setNotice("");
    setWarning("");
    try {
      applyStatus(await api.setAiActive({ config_id: config.id }));
      setNotice(`之后的 AI 调用会用「${config.name || config.active_model}」`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换失败");
    }
  }

  async function handleDeleteConfig(config: AiProviderConfig) {
    if (
      !window.confirm(
        `删除「${config.name || config.active_model}」？删除后这条下的模型都不能再用。`
      )
    )
      return;
    setError("");
    setNotice("");
    setWarning("");
    try {
      const next = await api.deleteAiConfig(config.id);
      applyStatus(next);
      setPane(next.configs.length > 0 ? `config:${next.configs[0].id}` : "new");
      setNotice("已删除");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleAdopt(share: AiShare) {
    setError("");
    setNotice("");
    setWarning("");
    try {
      await api.adoptAiShare(share.id);
      const next = await api.aiStatus();
      applyStatus(next);
      setPane("adopted");
      setNotice(`已采纳「${share.title}」，之后的 AI 调用会用它`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "采纳失败");
    }
  }

  async function handleUseShare(share: AiShare) {
    setError("");
    try {
      applyStatus(await api.setAiActive({ share_id: share.id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换失败");
    }
  }

  async function handleToggleShare(share: AiShare) {
    setError("");
    try {
      await api.setAiShareActive(share.id, !share.is_active);
      applyStatus(await api.aiStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDeleteShare(share: AiShare) {
    if (!window.confirm(`删除分享「${share.title}」？其他人会立即看不到。`)) return;
    setError("");
    try {
      await api.deleteAiShare(share.id);
      applyStatus(await api.aiStatus());
      setNotice("已删除分享");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleCreateShare(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setError("");
    setNotice("");
    setSharing(true);
    try {
      await api.createAiShare({
        config_id: editing.id,
        title: shareTitle.trim(),
        note: shareNote.trim(),
      });
      setShareOpen(false);
      setShareTitle("");
      setShareNote("");
      applyStatus(await api.aiStatus());
      setNotice("已分享，其他用户登录后可以选择采纳");
    } catch (err) {
      setError(err instanceof Error ? err.message : "分享失败");
    } finally {
      setSharing(false);
    }
  }

  if (loading) return <Spinner />;
  if (!status) return <EmptyState text={error || "加载失败"} />;

  const canSave = models.length > 0 && baseUrl.trim().length > 0;
  const canShare = editing !== null && models.length > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">模型设置</h1>
          <p className="mt-1 text-xs text-slate-500">
            添加自己的模型供应商，可加多个、每个下面可放多个模型；也可以采纳别人分享的模型。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCatalogOpen(true)}
          className="btn-primary shrink-0"
        >
          + 添加供应商
        </button>
      </div>

      {error ? (
        <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>
      ) : null}
      {warning ? (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {warning}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-xl bg-brand-50 px-3 py-2 text-xs text-brand-700">{notice}</p>
      ) : null}

      <section className="card flex items-center gap-3 p-4">
        <span className="text-xs text-slate-500">当前生效</span>
        <span className="chip-brand">
          {SOURCE_TEXT[status.active_source] ?? status.active_source}
        </span>
        <span className="text-sm text-slate-700">{status.active_label}</span>
      </section>

      <div className="card grid gap-0 overflow-hidden md:grid-cols-[260px_1fr]">
        {/* 左侧：来源列表 */}
        <aside className="border-b border-slate-200 bg-slate-50/60 p-3 md:border-b-0 md:border-r">
          <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            我的接入（{configs.length}）
          </p>
          {configs.length === 0 ? (
            <p className="px-3 py-2 text-[11px] text-slate-400">
              还没有添加模型，点右上角「添加供应商」
            </p>
          ) : (
            <ul className="space-y-1">
              {configs.map((config) => (
                <li key={config.id}>
                  <button
                    type="button"
                    onClick={() => selectPane(`config:${config.id}`)}
                    className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                      pane === `config:${config.id}`
                        ? "bg-white font-medium text-brand-700 shadow-sm"
                        : "text-slate-600 hover:bg-white/70"
                    }`}
                  >
                    <SourceIcon source="user" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">
                        {config.name || config.active_model}
                      </span>
                      <span className="block truncate text-[11px] font-normal text-slate-400">
                        {config.models.length} 个模型 · {config.active_model}
                      </span>
                    </span>
                    <StatusDot
                      color={
                        config.is_active
                          ? "green"
                          : config.active_model
                            ? "orange"
                            : "slate"
                      }
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {status.adopted_share ? (
            <>
              <p className="mt-4 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                采纳的分享
              </p>
              <ul className="space-y-1">
                <li>
                  <button
                    type="button"
                    onClick={() => selectPane("adopted")}
                    className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                      pane === "adopted"
                        ? "bg-white font-medium text-brand-700 shadow-sm"
                        : "text-slate-600 hover:bg-white/70"
                    }`}
                  >
                    <SourceIcon source="share" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">
                        {status.adopted_share.title}
                      </span>
                      <span className="block truncate text-[11px] font-normal text-slate-400">
                        {status.adopted_share.is_active
                          ? `来自 ${status.adopted_share.owner_name}`
                          : "已失效"}
                      </span>
                    </span>
                    <StatusDot
                      color={
                        status.active_share_id === status.adopted_share.id
                          ? "green"
                          : status.adopted_share.is_active
                            ? "orange"
                            : "slate"
                      }
                    />
                  </button>
                </li>
              </ul>
            </>
          ) : null}

          <p className="mt-4 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            我分享的（{myShares.length}）
          </p>
          {myShares.length === 0 ? (
            <p className="px-3 py-2 text-[11px] text-slate-400">还没有分享</p>
          ) : (
            <ul className="space-y-1">
              {myShares.map((share) => (
                <li key={share.id}>
                  <button
                    type="button"
                    onClick={() => selectPane(`share:${share.id}` as PaneKey)}
                    className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                      pane === `share:${share.id}`
                        ? "bg-white font-medium text-brand-700 shadow-sm"
                        : "text-slate-600 hover:bg-white/70"
                    }`}
                  >
                    <SourceIcon source="share" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{share.title}</span>
                      <span className="block truncate text-[11px] font-normal text-slate-400">
                        {share.adoption_count} 人采纳
                      </span>
                    </span>
                    <StatusDot color={share.is_active ? "green" : "orange"} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <p className="mt-4 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            可用的分享（{otherShares.length}）
          </p>
          {otherShares.length === 0 ? (
            <p className="px-3 py-2 text-[11px] text-slate-400">暂无</p>
          ) : (
            <ul className="space-y-1">
              {otherShares.map((share) => (
                <li
                  key={share.id}
                  className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-slate-600"
                >
                  <SourceIcon source="share" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{share.title}</span>
                    <span className="block truncate text-[11px] text-slate-400">
                      {share.owner_name}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => handleAdopt(share)}
                    className="shrink-0 text-[11px] text-brand-600 underline-offset-2 hover:underline"
                  >
                    采纳
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* 右侧：详情 */}
        <div className="p-5">
          {pane === "new" || editing ? (
            <form onSubmit={handleSave} className="space-y-4" autoComplete="off">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="truncate text-base font-semibold text-slate-900">
                    {name || activeModel || "新的模型供应商"}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {editing
                      ? `已保存 ${editing.key_hint}`
                      : "填好地址和 Key，添加至少一个模型就能用"}
                  </p>
                </div>
                {editing ? (
                  <span
                    className={editing.is_active ? "chip-brand" : "chip-slate"}
                  >
                    {editing.is_active ? "使用中" : "未使用"}
                  </span>
                ) : null}
              </div>

              <label className="block space-y-1">
                <span className="text-xs font-medium text-slate-500">
                  名称（可选）
                </span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如 我的 DeepSeek"
                  autoComplete="off"
                  className="input text-xs"
                />
              </label>

              <div className="space-y-1">
                <label className="block space-y-1">
                  <span className="text-xs font-medium text-slate-500">Base URL</span>
                  <input
                    required
                    value={baseUrl}
                    onChange={(event) => {
                      setBaseUrl(event.target.value);
                      setFetched([]);
                      // 手动改了地址就不再算「预设填好的」
                      setPresetLabel("");
                    }}
                    placeholder="https://api.example.com/v1"
                    autoComplete="off"
                    className="input font-mono text-xs"
                  />
                </label>
                {presetLabel ? (
                  <p className="text-[11px] text-brand-600">
                    已按「{presetLabel}」预设填好，可自行修改
                  </p>
                ) : null}
                {/* 常见服务商的一键填入：自定义供应商也能抄地址，不用背域名 */}
                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  <span className="text-[11px] text-slate-400">快速填入：</span>
                  {presetsByGroup("常见服务商").map((preset) => (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={() => quickFill(preset)}
                      className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600 transition hover:border-brand-300 hover:bg-brand-50/50 hover:text-brand-700"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              <label className="block space-y-1">
                <span className="text-xs font-medium text-slate-500">API 格式</span>
                <select
                  value={apiFormat}
                  onChange={(event) => {
                    setApiFormat(event.target.value as AiApiFormat);
                    setFetched([]);
                  }}
                  className="input text-xs"
                >
                  {AI_FORMAT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}（{option.endpoint}）
                    </option>
                  ))}
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs font-medium text-slate-500">API Key</span>
                <input
                  ref={apiKeyRef}
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={
                    editing ? "留空则沿用已保存的 Key" : "输入 API Key"
                  }
                  autoComplete="new-password"
                  className="input font-mono text-xs"
                />
              </label>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-500">
                    模型列表（点一个设为当前使用）
                  </span>
                  <button
                    type="button"
                    onClick={() => setAddingModel((open) => !open)}
                    className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-brand-300"
                  >
                    + 添加模型
                  </button>
                </div>

                {addingModel ? (
                  <div className="flex gap-2">
                    <input
                      autoFocus
                      value={modelInput}
                      onChange={(event) => setModelInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          handleAddModel();
                        }
                      }}
                      placeholder="模型名，例如 deepseek-chat"
                      list="ai-model-options"
                      autoComplete="off"
                      className="input flex-1 font-mono text-xs"
                    />
                    <button
                      type="button"
                      onClick={handleAddModel}
                      className="btn-primary shrink-0 text-xs"
                    >
                      添加
                    </button>
                  </div>
                ) : null}

                <datalist id="ai-model-options">
                  {[...new Set([...models, ...fetched])].map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>

                {models.length === 0 ? (
                  <div className="flex items-start gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-3 py-4 text-xs text-slate-400">
                    <span aria-hidden>ⓘ</span>
                    <span>还没有模型，添加至少一个后这条供应商才可用。</span>
                  </div>
                ) : (
                  <ul className="space-y-1.5">
                    {models.map((item) => (
                      <li
                        key={item}
                        className={`flex items-center gap-2 rounded-xl border px-3 py-2 ${
                          item === activeModel
                            ? "border-brand-300 bg-brand-50/50"
                            : "border-slate-200 bg-white"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => setActiveModel(item)}
                          className="min-w-0 flex-1 text-left font-mono text-xs text-slate-700"
                        >
                          {item}
                        </button>
                        {item === activeModel ? (
                          <span className="chip-brand shrink-0">当前</span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setActiveModel(item)}
                            className="shrink-0 text-[11px] text-brand-600 underline-offset-2 hover:underline"
                          >
                            用这个
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleRemoveModel(item)}
                          className="shrink-0 text-[11px] text-slate-400 transition hover:text-rose-500"
                        >
                          移除
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={handleFetchModels}
                    disabled={fetchingModels || !baseUrl.trim()}
                    className="text-[11px] text-brand-600 underline-offset-2 hover:underline disabled:text-slate-300"
                  >
                    {fetchingModels ? "获取中…" : "自动获取模型列表"}
                  </button>
                  {fetched.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => {
                        setModels((prev) => [
                          ...prev,
                          ...fetched.filter((m) => !prev.includes(m)),
                        ]);
                        if (!activeModel && fetched[0]) setActiveModel(fetched[0]);
                        setNotice(`已加入 ${fetched.length} 个候选模型`);
                      }}
                      className="text-[11px] text-brand-600 underline-offset-2 hover:underline"
                    >
                      把获取到的 {fetched.length} 个都加入列表
                    </button>
                  ) : null}
                </div>

                {/* 测试连接失败时服务端带回来的真实模型名：点一下直接换成能用的 */}
                {fetched.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-slate-400">
                      这条地址下的模型：
                    </span>
                    {fetched.slice(0, 8).map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => {
                          if (!models.includes(item)) {
                            setModels((prev) => [...prev, item]);
                          }
                          setActiveModel(item);
                          setNotice(`已选用 ${item}`);
                        }}
                        className={`rounded-full border px-2 py-0.5 font-mono text-[11px] transition ${
                          item === activeModel
                            ? "border-brand-300 bg-brand-50 text-brand-700"
                            : "border-slate-200 bg-white text-slate-600 hover:border-brand-300 hover:text-brand-700"
                        }`}
                      >
                        {item}
                      </button>
                    ))}
                    {fetched.length > 8 ? (
                      <span className="text-[11px] text-slate-400">
                        …共 {fetched.length} 个
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <p className="text-[11px] text-slate-400">
                Key 加密保存在服务端，不会回传到浏览器，也不会展示给管理员。
              </p>

              <div className="flex flex-wrap gap-2">
                <button
                  type="submit"
                  disabled={saving || !canSave}
                  className="btn-primary"
                >
                  {saving ? "保存中…" : editing ? "保存" : "添加"}
                </button>
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testing || !baseUrl.trim() || !activeModel}
                  className="btn-ghost"
                >
                  {testing ? "测试中…" : "测试连接"}
                </button>
                {editing ? (
                  <>
                    <button
                      type="button"
                      onClick={() => handleUseConfig(editing)}
                      disabled={editing.is_active}
                      className="btn-ghost"
                    >
                      {editing.is_active ? "正在使用" : "设为当前使用"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setShareOpen(true);
                        setShareTitle(name || activeModel || "我的模型");
                      }}
                      disabled={!canShare}
                      className="btn-ghost"
                    >
                      分享给别人
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteConfig(editing)}
                      className="rounded-xl border border-slate-200 px-4 py-2 text-xs text-rose-500 transition hover:border-rose-300"
                    >
                      删除
                    </button>
                  </>
                ) : null}
              </div>
            </form>
          ) : null}

          {pane === "adopted" && status.adopted_share ? (
            <div className="space-y-4">
              <p className="text-base font-semibold text-slate-900">我采纳的分享</p>
              {status.adopted_share.is_active ? (
                <>
                  <div className="rounded-xl border border-brand-200 bg-brand-50/40 p-4">
                    <p className="text-sm text-slate-900">
                      {status.adopted_share.title}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      来自 {status.adopted_share.owner_name} ·{" "}
                      {status.adopted_share.active_model}（
                      {formatLabel(status.adopted_share.api_format)}）
                    </p>
                    {status.adopted_share.models.length > 1 ? (
                      <p className="mt-2 text-[11px] text-slate-500">
                        可用的模型：
                        {status.adopted_share.models.join("、")}
                      </p>
                    ) : null}
                    {status.adopted_share.note ? (
                      <p className="mt-2 text-xs text-slate-500">
                        {status.adopted_share.note}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleUseShare(status.adopted_share!)}
                      disabled={status.active_share_id === status.adopted_share.id}
                      className="btn-primary"
                    >
                      {status.active_share_id === status.adopted_share.id
                        ? "正在使用"
                        : "用这个"}
                    </button>
                  </div>
                </>
              ) : (
                <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  分享者已停止分享或删除，这个模型不再可用，请另选来源。
                </p>
              )}
            </div>
          ) : null}

          {typeof pane === "string" && pane.startsWith("share:") ? (
            (() => {
              const id = Number(pane.slice("share:".length));
              const share = myShares.find((s) => s.id === id);
              if (!share) return <EmptyState text="这条分享已不存在" />;
              return (
                <div className="space-y-4">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-base font-semibold text-slate-900">
                      {share.title}
                    </p>
                    <span className={share.is_active ? "chip-brand" : "chip-slate"}>
                      {share.is_active ? "分享中" : "已停止"}
                    </span>
                  </div>
                  <dl className="space-y-2 text-xs">
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-400">Base URL</dt>
                      <dd className="break-all font-mono text-slate-700">
                        {share.base_url}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-400">模型</dt>
                      <dd className="font-mono text-slate-700">
                        {share.models.join("、")}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-400">API 格式</dt>
                      <dd className="text-slate-700">
                        {formatLabel(share.api_format)}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-400">API Key</dt>
                      <dd className="text-slate-700">{share.key_hint}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-400">采纳人数</dt>
                      <dd className="text-slate-700">{share.adoption_count}</dd>
                    </div>
                  </dl>
                  {share.note ? (
                    <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
                      {share.note}
                    </p>
                  ) : null}
                  <p className="text-[11px] text-slate-400">
                    停止分享后其他人立即看不到，但记录保留，随时可以重新开启。
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => handleToggleShare(share)}
                      className={share.is_active ? "btn-ghost" : "btn-primary"}
                    >
                      {share.is_active ? "停止分享" : "重新分享"}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteShare(share)}
                      className="rounded-xl border border-slate-200 px-4 py-2 text-xs text-rose-500 transition hover:border-rose-300"
                    >
                      删除分享
                    </button>
                  </div>
                </div>
              );
            })()
          ) : null}
        </div>
      </div>

      {/* 添加供应商目录 */}
      <Modal
        open={catalogOpen}
        onClose={() => setCatalogOpen(false)}
        title="添加供应商"
        maxWidth="max-w-2xl"
      >
        <p className="text-xs text-slate-500">
          选一个常见服务商，Base URL 与模型名会自动填好，你只要补上 API Key；也可以选「创建自定义供应商」自己填地址。
        </p>

        {AI_PRESET_GROUPS.map((group) => {
          const presets = presetsByGroup(group);
          if (presets.length === 0) return null;
          return (
            <div key={group} className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {group}
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {presets.map((preset) => (
                  <button
                    key={preset.key}
                    type="button"
                    onClick={() => applyPreset(preset)}
                    className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-left transition hover:border-brand-300 hover:bg-brand-50/40"
                  >
                    <AiProviderIcon preset={preset} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-900">
                        {preset.label}
                      </span>
                      {/* 卡片上直接写清会填进去的地址：选之前就知道 Base URL 是什么 */}
                      <span
                        className={`block truncate text-[11px] ${
                          preset.custom
                            ? "text-slate-400"
                            : "font-mono text-slate-500"
                        }`}
                      >
                        {preset.custom
                          ? "自己填 Base URL 与模型名"
                          : shortBaseUrl(preset.base_url)}
                      </span>
                    </span>
                    {!preset.custom && preset.api_format !== "openai" ? (
                      <span className="chip-slate shrink-0">
                        {formatShortLabel(preset.api_format)}
                      </span>
                    ) : null}
                    <span className="text-slate-300">›</span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </Modal>

      {/* 分享给别人 */}
      <Modal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        title="分享我的模型"
        footer={
          <>
            <button
              type="submit"
              form="share-form"
              disabled={sharing}
              className="btn-primary flex-1"
            >
              {sharing ? "分享中…" : "确认分享"}
            </button>
            <button
              type="button"
              onClick={() => setShareOpen(false)}
              className="btn-ghost"
            >
              取消
            </button>
          </>
        }
      >
        <form id="share-form" onSubmit={handleCreateShare} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-500">分享名称</span>
            <input
              value={shareTitle}
              onChange={(event) => setShareTitle(event.target.value)}
              placeholder="别人会看到这个名字"
              className="input text-xs"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-500">说明（可选）</span>
            <input
              value={shareNote}
              onChange={(event) => setShareNote(event.target.value)}
              placeholder="例如：额度不多，悠着点用"
              className="input text-xs"
            />
          </label>
          <p className="rounded-xl bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
            将分享这条供应商的 Base URL、模型列表与 API Key。Key
            会加密保存，其他用户看不到明文。
          </p>
        </form>
      </Modal>
    </div>
  );
}

export default function AiSettingsPage() {
  return (
    <RequireAuth>
      <AppShell>
        <AiSettingsView />
      </AppShell>
    </RequireAuth>
  );
}
