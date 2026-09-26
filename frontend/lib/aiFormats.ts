/**
 * AI 接入格式与常见服务商预设。
 *
 * 一个凭据由 Base URL、接入协议（api_format）和 Key 三部分组成：
 * 只要服务端兼容下面某种协议，就能接入；官方直连与各类兼容服务一视同仁。
 */

import type { AiApiFormat } from "@/lib/types";

export interface AiFormatOption {
  value: AiApiFormat;
  label: string;
  /** 该协议对应的端点，展示在选项里方便对照 */
  endpoint: string;
}

export const AI_FORMAT_OPTIONS: AiFormatOption[] = [
  {
    value: "openai",
    label: "OpenAI 兼容",
    endpoint: "/chat/completions",
  },
  {
    value: "openai_responses",
    label: "OpenAI Responses",
    endpoint: "/responses",
  },
  {
    value: "anthropic",
    label: "Anthropic Messages",
    endpoint: "/v1/messages",
  },
  {
    value: "gemini",
    label: "Google Gemini",
    endpoint: "generativelanguage.googleapis.com",
  },
];

export const DEFAULT_AI_FORMAT: AiApiFormat = "openai";

export interface AiPreset {
  /** 稳定标识，用作列表 key */
  key: string;
  label: string;
  /** 目录里的分组标题 */
  group: string;
  base_url: string;
  model: string;
  api_format: AiApiFormat;
  /** 图标方块的完整 class（底色 + 文字色） */
  accent: string;
  /** 图标里显示的字 */
  initial: string;
  /** 自定义供应商：地址与模型名留空，交给用户自己填 */
  custom?: boolean;
}

export const AI_PRESET_GROUPS = ["常见服务商", "自定义"] as const;

export function presetsByGroup(group: string): AiPreset[] {
  return AI_PRESETS.filter((preset) => preset.group === group);
}

/** 一键填充用的常见服务商。地址与模型名都可以在表单里改。 */
export const AI_PRESETS: AiPreset[] = [
  {
    key: "deepseek",
    label: "DeepSeek",
    group: "常见服务商",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    api_format: "openai",
    accent: "bg-blue-500 text-white",
    initial: "D",
  },
  {
    key: "kimi",
    label: "Kimi",
    group: "常见服务商",
    base_url: "https://api.moonshot.cn/v1",
    model: "moonshot-v1-8k",
    api_format: "openai",
    accent: "bg-indigo-500 text-white",
    initial: "K",
  },
  {
    key: "bigmodel",
    label: "智谱 BigModel",
    group: "常见服务商",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4-flash",
    api_format: "openai",
    accent: "bg-purple-500 text-white",
    initial: "智",
  },
  {
    key: "dashscope",
    label: "阿里云百炼",
    group: "常见服务商",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-plus",
    api_format: "openai",
    accent: "bg-orange-500 text-white",
    initial: "通",
  },
  {
    key: "siliconflow",
    label: "硅基流动",
    group: "常见服务商",
    base_url: "https://api.siliconflow.cn/v1",
    model: "Qwen/Qwen2.5-7B-Instruct",
    api_format: "openai",
    accent: "bg-teal-500 text-white",
    initial: "硅",
  },
  {
    key: "minimax",
    label: "MiniMax",
    group: "常见服务商",
    base_url: "https://api.minimax.chat/v1",
    model: "abab6.5s-chat",
    api_format: "openai",
    accent: "bg-rose-500 text-white",
    initial: "M",
  },
  {
    key: "openai",
    label: "OpenAI",
    group: "常见服务商",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    api_format: "openai",
    accent: "bg-slate-800 text-white",
    initial: "O",
  },
  {
    key: "anthropic",
    label: "Anthropic",
    group: "常见服务商",
    base_url: "https://api.anthropic.com",
    model: "claude-3-5-sonnet-latest",
    api_format: "anthropic",
    accent: "bg-amber-600 text-white",
    initial: "A",
  },
  {
    key: "gemini",
    label: "Google Gemini",
    group: "常见服务商",
    base_url: "https://generativelanguage.googleapis.com",
    model: "gemini-1.5-flash",
    api_format: "gemini",
    accent: "bg-sky-500 text-white",
    initial: "G",
  },
  {
    key: "xai",
    label: "xAI",
    group: "常见服务商",
    base_url: "https://api.x.ai/v1",
    model: "grok-beta",
    api_format: "openai",
    accent: "bg-slate-700 text-white",
    initial: "x",
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    group: "常见服务商",
    base_url: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4o-mini",
    api_format: "openai",
    accent: "bg-violet-500 text-white",
    initial: "R",
  },
  {
    key: "custom",
    label: "创建自定义供应商",
    group: "自定义",
    base_url: "",
    model: "",
    api_format: "openai",
    accent: "border border-dashed border-slate-300 bg-white text-slate-400",
    initial: "+",
    custom: true,
  },
];

export function formatLabel(value: string): string {
  return AI_FORMAT_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

/**
 * 地址的短写法：去掉协议与尾斜杠，只留域名和路径。
 *
 * 卡片上要能一眼看出「选这个会填进去哪个地址」，`https://api.siliconflow.cn/v1`
 * 太长，`api.siliconflow.cn/v1` 正好。
 */
export function shortBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

/** 格式短名：卡片角落只放非默认格式（Anthropic / Gemini 这些），避免满屏「OpenAI 兼容」。 */
export function formatShortLabel(value: AiApiFormat): string {
  return (
    {
      openai: "OpenAI",
      openai_responses: "Responses",
      anthropic: "Anthropic",
      gemini: "Gemini",
    } as Record<AiApiFormat, string>
  )[value];
}
