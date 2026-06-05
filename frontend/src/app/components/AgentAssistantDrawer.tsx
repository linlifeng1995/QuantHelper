"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Avatar, Button, Card, Collapse, Drawer, Input, List, Popconfirm, Select, Space, Switch, Tag, Typography, message } from "antd";
import { addToWatchlist as addToWatchlistStorage } from "../lib/watchlist-storage";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

export type AgentScene = "global_chat" | "stock_diagnosis" | "screen_explain" | "backtest_review" | "news_analysis";
type AgentProvider = "kimi" | "deepseek";

export type AgentDraft = {
  scene: AgentScene;
  userInput?: string;
  payload?: Record<string, unknown>;
};

type AgentResponse = {
  scene: AgentScene;
  render_mode?: "natural" | "structured";
  natural_text?: string;
  summary: string;
  key_points: string[];
  risks: string[];
  actions: string[];
  disclaimer: string;
  raw_text: string;
  provider: string;
  model: string;
  reasoning_content?: string;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
};

type ChatTurn = {
  role: "user" | "assistant";
  content: string;
  model?: string;
  reasoning_content?: string;
  sourceTicker?: string;
  result?: AgentResponse;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
};

type ChatSession = {
  id: string;
  title: string;
  scene: AgentScene;
  turns: ChatTurn[];
  updatedAt: number;
  createdAt?: number;
  pinned?: boolean;
};

type AgentTemplate = {
  id: string;
  name: string;
  scene: AgentScene;
  userInput: string;
  payload: Record<string, unknown>;
  isDefault?: boolean;
};

type PoolOption = {
  id: number;
  name: string;
};

type Props = {
  apiBase: string;
  open: boolean;
  onClose: () => void;
  draft: AgentDraft | null;
  onWatchlistChange?: () => void;
};

const FX_CNY_PER_USD = 7.2;
const PRICE_BASE_MODEL = "moonshot-v1-8k";

// Unified pricing baseline in USD per 1M tokens.
// Sources (2026-05 docs):
// - Kimi: moonshot-v1/k2.6 public pricing pages (CNY converted to USD)
// - DeepSeek: v4 pricing page cache-miss input price
const MODEL_PRICE_USD_PER_1M: Record<string, { input: number; output: number }> = {
  "moonshot-v1-auto": { input: 2.0 / FX_CNY_PER_USD, output: 10.0 / FX_CNY_PER_USD },
  "moonshot-v1-8k": { input: 2.0 / FX_CNY_PER_USD, output: 10.0 / FX_CNY_PER_USD },
  "moonshot-v1-32k": { input: 5.0 / FX_CNY_PER_USD, output: 20.0 / FX_CNY_PER_USD },
  "moonshot-v1-128k": { input: 10.0 / FX_CNY_PER_USD, output: 30.0 / FX_CNY_PER_USD },
  "kimi-k2-0711-preview": { input: 4.0 / FX_CNY_PER_USD, output: 21.0 / FX_CNY_PER_USD },
  "kimi-k2.6": { input: 6.5 / FX_CNY_PER_USD, output: 27.0 / FX_CNY_PER_USD },
  "deepseek-v4-flash": { input: 0.14, output: 0.28 },
  "deepseek-chat": { input: 0.14, output: 0.28 },
  "deepseek-reasoner": { input: 0.14, output: 0.28 },
};

function formatMultiplier(multiplier: number): string {
  if (!Number.isFinite(multiplier) || multiplier <= 0) return "-";
  if (Math.abs(multiplier - 1) < 0.05) return "1x";
  if (multiplier < 1) return `${multiplier.toFixed(2)}x`;
  return `${multiplier.toFixed(1)}x`;
}

function modelPriceMultiplierLabel(model: string): string | null {
  const basePrice = MODEL_PRICE_USD_PER_1M[PRICE_BASE_MODEL]?.input;
  const modelPrice = MODEL_PRICE_USD_PER_1M[model]?.input;
  if (!basePrice || !modelPrice) return null;
  return formatMultiplier(modelPrice / basePrice);
}

const PROVIDER_DEFAULTS: Record<AgentProvider, { baseUrl: string; model: string }> = {
  kimi: {
    baseUrl: "https://api.moonshot.cn/v1",
    model: "moonshot-v1-8k",
  },
  deepseek: {
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-v4-flash",
  },
};

const PROVIDER_MODEL_OPTIONS: Record<AgentProvider, string[]> = {
  kimi: [
    "kimi-k2.6",
    "kimi-k2-0711-preview",
    "moonshot-v1-8k",
    "moonshot-v1-32k",
    "moonshot-v1-128k",
    "moonshot-v1-auto",
  ],
  deepseek: ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
};

const TEMPLATE_STORAGE_KEY = "mq_agent_templates";
const STRUCTURED_MODE_STORAGE_KEY = "mq_agent_structured_mode";

const DEFAULT_AGENT_PROFILE_PAYLOAD: Record<string, unknown> = {
  agent_profile: {
    role: "A股研究助手",
    objective: "把页面数据解释清楚，并帮助用户形成下一步研究和复核思路",
    constraints: ["先说明数据依据", "不承诺收益", "区分事实、推断和需要验证的假设"],
  },
  analysis_framework: ["趋势", "估值", "资金", "风险事件"],
  output_preferences: {
    actionable: true,
    include_risk_level: true,
    include_position_hint: false,
  },
};

const DEFAULT_TEMPLATES: AgentTemplate[] = [
  {
    id: "tpl_global",
    name: "自然研究问答（默认）",
    scene: "global_chat",
    userInput: "",
    payload: DEFAULT_AGENT_PROFILE_PAYLOAD,
    isDefault: true,
  },
  {
    id: "tpl_stock_diag",
    name: "个股诊断",
    scene: "stock_diagnosis",
    userInput: "请自然说明这只股票当前最值得关注的变化、主要风险和下一步复核点。",
    payload: { ticker: "" },
    isDefault: true,
  },
  {
    id: "tpl_screen",
    name: "筛选解释",
    scene: "screen_explain",
    userInput: "请自然解释当前筛选结果的主要特征、可能偏向和需要留意的风险。",
    payload: {},
    isDefault: true,
  },
  {
    id: "tpl_backtest",
    name: "回测复盘",
    scene: "backtest_review",
    userInput: "请自然复盘这次回测说明了什么、哪些地方不稳健，以及下一轮该怎么验证。",
    payload: {},
    isDefault: true,
  },
  {
    id: "tpl_news",
    name: "新闻解析",
    scene: "news_analysis",
    userInput: "请自然分析这些新闻可能改变了什么预期，以及接下来需要跟踪哪些验证点。",
    payload: {},
    isDefault: true,
  },
];

function normalizeTemplates(savedTemplates: AgentTemplate[]): AgentTemplate[] {
  const builtinIds = new Set(DEFAULT_TEMPLATES.map((item) => item.id));
  const customTemplates = savedTemplates.filter((item) => !builtinIds.has(item.id));
  return [...DEFAULT_TEMPLATES, ...customTemplates];
}

function flattenTemplateContext(obj: unknown, prefix = "", out: Record<string, string> = {}): Record<string, string> {
  if (obj === null || obj === undefined) return out;
  if (Array.isArray(obj)) {
    out[prefix] = obj.map((x) => String(x)).join(", ");
    return out;
  }
  if (typeof obj === "object") {
    const rows = obj as Record<string, unknown>;
    Object.entries(rows).forEach(([key, value]) => {
      const nextPrefix = prefix ? `${prefix}.${key}` : key;
      flattenTemplateContext(value, nextPrefix, out);
    });
    return out;
  }
  if (prefix) out[prefix] = String(obj);
  return out;
}

function interpolateTemplateString(text: string, context: Record<string, string>): string {
  return String(text || "").replace(/\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g, (_, rawKey: string) => {
    const key = String(rawKey || "").trim();
    return context[key] ?? "";
  });
}

function interpolateTemplatePayload(input: unknown, context: Record<string, string>): unknown {
  if (typeof input === "string") return interpolateTemplateString(input, context);
  if (Array.isArray(input)) return input.map((item) => interpolateTemplatePayload(item, context));
  if (input && typeof input === "object") {
    const out: Record<string, unknown> = {};
    Object.entries(input as Record<string, unknown>).forEach(([key, value]) => {
      out[key] = interpolateTemplatePayload(value, context);
    });
    return out;
  }
  return input;
}

function sceneLabel(scene: AgentScene): string {
  if (scene === "stock_diagnosis") return "个股诊断";
  if (scene === "screen_explain") return "筛选解释";
  if (scene === "backtest_review") return "回测复盘";
  if (scene === "news_analysis") return "新闻解析";
  return "全局助手";
}

function normalizeApiKey(value: string): string {
  const trimmed = (value || "").trim();
  if (!trimmed) return "";
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function maskKey(value: string): string {
  const key = normalizeApiKey(value);
  if (!key) return "未填写";
  if (key.length <= 8) return "已填写";
  return `已填写（***${key.slice(-4)}）`;
}

function sortSessions(items: ChatSession[]): ChatSession[] {
  return [...items].sort((a, b) => {
    const ap = !!a.pinned;
    const bp = !!b.pinned;
    if (ap !== bp) return ap ? -1 : 1;
    return b.updatedAt - a.updatedAt;
  });
}

function downloadTextFile(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function extractTickerFromPayload(payload: Record<string, unknown>): string {
  const direct = String(payload?.ticker || "").trim();
  if (direct) return direct;
  const fromSummary = String((payload?.stock_summary as Record<string, unknown> | undefined)?.ticker || "").trim();
  if (fromSummary) return fromSummary;
  return "";
}

function actionTargetText(ticker: string): string {
  return ticker ? `(${ticker})` : "";
}

function renderAssistantText(result: AgentResponse): string {
  const lines: string[] = [];
  if (result.summary) {
    lines.push(`结论：${result.summary}`);
  }
  if (result.key_points?.length) {
    lines.push("", "关键点：");
    result.key_points.forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
  }
  if (result.risks?.length) {
    lines.push("", "风险：");
    result.risks.forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
  }
  if (result.actions?.length) {
    lines.push("", "建议动作：");
    result.actions.forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
  }
  if (!lines.length) {
    return result.raw_text?.trim() || "未返回可展示内容。";
  }
  return lines.join("\n");
}

export default function AgentAssistantDrawer({ apiBase, open, onClose, draft, onWatchlistChange }: Props) {
  const [provider, setProvider] = useState<AgentProvider>("kimi");
  const [accessToken, setAccessToken] = useState("");
  const [kimiApiKey, setKimiApiKey] = useState("");
  const [kimiBaseUrl, setKimiBaseUrl] = useState("https://api.moonshot.cn/v1");
  const [kimiModel, setKimiModel] = useState("moonshot-v1-8k");
  const [deepseekApiKey, setDeepseekApiKey] = useState("");
  const [deepseekBaseUrl, setDeepseekBaseUrl] = useState("https://api.deepseek.com");
  const [deepseekModel, setDeepseekModel] = useState("deepseek-v4-flash");
  const [scene, setScene] = useState<AgentScene>("global_chat");
  const [userInput, setUserInput] = useState("");
  const [payload, setPayload] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const stopStreamingRef = useRef(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [showThinking, setShowThinking] = useState(true);
  const [structuredMode, setStructuredMode] = useState(false);
  const [configCheckStatus, setConfigCheckStatus] = useState<string>("");
  const [templates, setTemplates] = useState<AgentTemplate[]>(DEFAULT_TEMPLATES);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(DEFAULT_TEMPLATES[0].id);
  const [poolOptions, setPoolOptions] = useState<PoolOption[]>([]);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const [agentConfigPanels, setAgentConfigPanels] = useState<string[]>([]);

  const activeSession = useMemo(
    () => sessions.find((item) => item.id === activeSessionId) ?? null,
    [sessions, activeSessionId],
  );
  const chatTurns = activeSession?.turns ?? [];

  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedProvider = (window.localStorage.getItem("mq_agent_provider") ?? "kimi").trim().toLowerCase();
    const savedStructuredMode = (window.localStorage.getItem(STRUCTURED_MODE_STORAGE_KEY) ?? "0").trim();
    const legacyApiKey = window.localStorage.getItem("mq_agent_api_key") ?? "";
    const legacyBaseUrl = window.localStorage.getItem("mq_agent_base_url") ?? "";
    const legacyModel = window.localStorage.getItem("mq_agent_model") ?? "";
    const savedKimiApiKey = window.localStorage.getItem("mq_kimi_api_key") ?? legacyApiKey;
    const savedKimiBaseUrl = window.localStorage.getItem("mq_kimi_base_url") ?? legacyBaseUrl ?? "https://api.moonshot.cn/v1";
    const savedKimiModel = window.localStorage.getItem("mq_kimi_model") ?? legacyModel ?? "moonshot-v1-8k";
    setProvider(savedProvider === "deepseek" ? "deepseek" : "kimi");
    setStructuredMode(savedStructuredMode === "1" || savedStructuredMode.toLowerCase() === "true");
    setAccessToken(window.localStorage.getItem("mq_agent_access_token") ?? "");
    setKimiApiKey(savedKimiApiKey);
    setKimiBaseUrl(savedKimiBaseUrl);
    setKimiModel(savedKimiModel);
    setDeepseekApiKey(window.localStorage.getItem("mq_deepseek_api_key") ?? "");
    setDeepseekBaseUrl(window.localStorage.getItem("mq_deepseek_base_url") ?? "https://api.deepseek.com");
    setDeepseekModel(window.localStorage.getItem("mq_deepseek_model") ?? "deepseek-v4-flash");
    // Legacy key migration: keep backward compatibility with old single-provider storage.
    if (!window.localStorage.getItem("mq_kimi_api_key") && legacyApiKey.trim()) {
      window.localStorage.setItem("mq_kimi_api_key", legacyApiKey.trim());
    }
    if (!window.localStorage.getItem("mq_kimi_base_url") && legacyBaseUrl.trim()) {
      window.localStorage.setItem("mq_kimi_base_url", legacyBaseUrl.trim());
    }
    if (!window.localStorage.getItem("mq_kimi_model") && legacyModel.trim()) {
      window.localStorage.setItem("mq_kimi_model", legacyModel.trim());
    }
    try {
      const raw = window.localStorage.getItem("mq_agent_sessions") ?? "[]";
      const saved = JSON.parse(raw) as ChatSession[];
      if (Array.isArray(saved) && saved.length > 0) {
        const sorted = sortSessions(saved);
        setSessions(sorted);
        setActiveSessionId(sorted[0].id);
      }
    } catch {
      // ignore invalid localStorage content
    }

    try {
      const rawTemplates = window.localStorage.getItem(TEMPLATE_STORAGE_KEY) ?? "[]";
      const savedTemplates = JSON.parse(rawTemplates) as AgentTemplate[];
      if (Array.isArray(savedTemplates) && savedTemplates.length > 0) {
        const normalizedTemplates = normalizeTemplates(savedTemplates);
        setTemplates(normalizedTemplates);
        setSelectedTemplateId(normalizedTemplates[0].id);
      }
    } catch {
      // ignore invalid localStorage content
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("mq_agent_access_token", accessToken);
  }, [accessToken]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("mq_agent_provider", provider);
  }, [provider]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STRUCTURED_MODE_STORAGE_KEY, structuredMode ? "1" : "0");
  }, [structuredMode]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("mq_kimi_api_key", kimiApiKey);
    window.localStorage.setItem("mq_kimi_base_url", kimiBaseUrl);
    window.localStorage.setItem("mq_kimi_model", kimiModel);
  }, [kimiApiKey, kimiBaseUrl, kimiModel]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("mq_deepseek_api_key", deepseekApiKey);
    window.localStorage.setItem("mq_deepseek_base_url", deepseekBaseUrl);
    window.localStorage.setItem("mq_deepseek_model", deepseekModel);
  }, [deepseekApiKey, deepseekBaseUrl, deepseekModel]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("mq_agent_sessions", JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(TEMPLATE_STORAGE_KEY, JSON.stringify(templates));
  }, [templates]);

  useEffect(() => {
    if (!open) return;
    void loadPoolOptions();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [open, chatTurns.length, loading]);

  function buildSessionTitle(targetScene: AgentScene) {
    return `${sceneLabel(targetScene)} ${new Date().toLocaleString("zh-CN", { hour12: false })}`;
  }

  function createSession(targetScene: AgentScene = scene) {
    const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const next: ChatSession = {
      id,
      title: buildSessionTitle(targetScene),
      scene: targetScene,
      turns: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      pinned: false,
    };
    setSessions((current) => sortSessions([next, ...current]).slice(0, 30));
    setActiveSessionId(id);
  }

  function ensureActiveSessionId(targetScene: AgentScene = scene): string {
    if (activeSessionId) {
      return activeSessionId;
    }
    const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const next: ChatSession = {
      id,
      title: buildSessionTitle(targetScene),
      scene: targetScene,
      turns: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      pinned: false,
    };
    setSessions((current) => sortSessions([next, ...current]).slice(0, 30));
    setActiveSessionId(id);
    return id;
  }

  function setSessionTurnsById(sessionId: string, turns: ChatTurn[], targetScene: AgentScene = scene) {
    setSessions((current) => {
      const existing = current.find((item) => item.id === sessionId);
      // Use first user message as title on first save
      let newTitle: string | undefined;
      if (existing && existing.turns.length === 0) {
        const firstUserMsg = turns.find((t) => t.role === "user");
        if (firstUserMsg) {
          const raw = firstUserMsg.content.trim();
          newTitle = raw.length > 32 ? raw.slice(0, 32) + "…" : raw;
        }
      }
      const found = !!existing;
      const nextList = found
        ? current.map((item) =>
            item.id === sessionId
              ? { ...item, scene: targetScene, turns, updatedAt: Date.now(), ...(newTitle ? { title: newTitle } : {}) }
              : item,
          )
        : [
            {
              id: sessionId,
              title: buildSessionTitle(targetScene),
              scene: targetScene,
              turns,
              createdAt: Date.now(),
              updatedAt: Date.now(),
              pinned: false,
            },
            ...current,
          ];
      return sortSessions(nextList).slice(0, 30);
    });
  }

  function renameActiveSession() {
    if (!activeSessionId) return;
    const current = sessions.find((s) => s.id === activeSessionId);
    const nextTitle = window.prompt("输入会话新名称", current?.title || "")?.trim();
    if (!nextTitle) return;
    setSessions((prev) => prev.map((s) => (s.id === activeSessionId ? { ...s, title: nextTitle, updatedAt: Date.now() } : s)));
  }

  function togglePinSession() {
    if (!activeSessionId) return;
    setSessions((prev) =>
      sortSessions(
        prev.map((s) => (s.id === activeSessionId ? { ...s, pinned: !s.pinned, updatedAt: Date.now() } : s)),
      ),
    );
  }

  function exportActiveSessionJson() {
    const session = sessions.find((s) => s.id === activeSessionId);
    if (!session) return;
    const filename = `agent_session_${session.id}.json`;
    downloadTextFile(filename, JSON.stringify(session, null, 2));
  }

  function exportActiveSessionMarkdown() {
    const session = sessions.find((s) => s.id === activeSessionId);
    if (!session) return;
    const lines: string[] = [];
    lines.push(`# ${session.title}`);
    lines.push("");
    lines.push(`- 场景: ${sceneLabel(session.scene)}`);
    lines.push(`- 更新时间: ${new Date(session.updatedAt).toLocaleString("zh-CN", { hour12: false })}`);
    lines.push("");
    session.turns.forEach((turn, idx) => {
      lines.push(`## ${idx + 1}. ${turn.role === "user" ? "你" : "助手"}`);
      if (turn.model) {
        lines.push(`模型: ${turn.model}`);
      }
      lines.push("");
      lines.push(turn.content || "");
      lines.push("");
    });
    const filename = `agent_session_${session.id}.md`;
    downloadTextFile(filename, lines.join("\n"));
  }

  function deleteSession(sessionId: string) {
    setSessions((current) => {
      const next = current.filter((item) => item.id !== sessionId);
      if (activeSessionId === sessionId) {
        setActiveSessionId(next[0]?.id ?? "");
      }
      return next;
    });
  }

  function applyTemplateById(templateId: string) {
    const tpl = templates.find((item) => item.id === templateId);
    if (!tpl) return;
    const context = {
      scene,
      today: new Date().toISOString().slice(0, 10),
      ...flattenTemplateContext(payload),
    };
    const nextUserInput = interpolateTemplateString(tpl.userInput || "", context);
    const nextPayload = (interpolateTemplatePayload(tpl.payload || {}, context) || {}) as Record<string, unknown>;
    setSelectedTemplateId(tpl.id);
    setScene(tpl.scene);
    setUserInput(nextUserInput);
    setPayload(nextPayload);
    setError("");
  }

  function saveCurrentAsTemplate() {
    const name = window.prompt("模板名称", `${sceneLabel(scene)}模板`)?.trim();
    if (!name) return;
    const next: AgentTemplate = {
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      name,
      scene,
      userInput,
      payload,
      isDefault: false,
    };
    setTemplates((prev) => [next, ...prev]);
    setSelectedTemplateId(next.id);
    void message.success("模板已保存");
  }

  function overwriteSelectedTemplate() {
    const tpl = templates.find((item) => item.id === selectedTemplateId);
    if (!tpl || tpl.isDefault) {
      void message.warning("默认模板不允许覆盖，请另存为新模板");
      return;
    }
    setTemplates((prev) =>
      prev.map((item) =>
        item.id === selectedTemplateId
          ? { ...item, scene, userInput, payload }
          : item,
      ),
    );
    void message.success("模板已更新");
  }

  function deleteSelectedTemplate() {
    const tpl = templates.find((item) => item.id === selectedTemplateId);
    if (!tpl || tpl.isDefault) {
      void message.warning("默认模板不能删除");
      return;
    }
    const ok = window.confirm(`确认删除模板「${tpl.name}」？`);
    if (!ok) return;
    setTemplates((prev) => {
      const next = prev.filter((item) => item.id !== selectedTemplateId);
      setSelectedTemplateId(next[0]?.id || DEFAULT_TEMPLATES[0].id);
      return next.length > 0 ? next : DEFAULT_TEMPLATES;
    });
  }

  async function loadPoolOptions() {
    try {
      const resp = await fetch(`${apiBase}/api/pools`);
      const json = await resp.json().catch(() => null);
      const rows = Array.isArray(json?.pools) ? json.pools : [];
      const next = rows
        .map((item: Record<string, unknown>) => ({ id: Number(item.id || 0), name: String(item.name || "") }))
        .filter((item: PoolOption) => item.id > 0 && item.name);
      setPoolOptions(next);
      return next;
    } catch {
      return [] as PoolOption[];
    }
  }

  async function createPlanFromTurn(turn: ChatTurn) {
    if (!turn.result) {
      void message.error("当前消息缺少结构化结果，暂无法创建计划");
      return;
    }
    const ticker = (turn.sourceTicker || "").trim();
    if (!ticker) {
      void message.error("未找到 ticker，无法创建计划");
      return;
    }
    const req = {
      ticker,
      action: "buy",
      confidence: "medium",
      position_pct: 5,
      reasons: turn.result?.key_points || [],
      risks: turn.result?.risks || [],
      note: turn.result?.summary || "由 Agent 一键创建",
      status: "draft",
    };
    const resp = await fetch(`${apiBase}/api/plans`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const json = await resp.json().catch(() => null);
    if (!resp.ok) {
      const detail = typeof json?.detail === "string" ? json.detail : `创建计划失败 (${resp.status})`;
      void message.error(detail);
      return;
    }
    void message.success(`计划已创建 ${actionTargetText(ticker)}`);
  }

  function addWatchlistFromTurn(turn: ChatTurn) {
    if (!turn.result) {
      void message.error("当前消息缺少结构化结果，暂无法加入观察列表");
      return;
    }
    const ticker = (turn.sourceTicker || "").trim();
    if (!ticker) {
      void message.error("未找到 ticker，无法加入观察列表");
      return;
    }
    addToWatchlistStorage({
      ticker,
      入选原因: turn.result?.summary || "由 Agent 建议加入",
      风格标签: turn.result?.actions || [],
    });
    void message.success(`已加入观察列表 ${actionTargetText(ticker)}`);
    onWatchlistChange?.();
  }

  async function addToPoolFromTurn(turn: ChatTurn) {
    if (!turn.result) {
      void message.error("当前消息缺少结构化结果，暂无法加入股票池");
      return;
    }
    const ticker = (turn.sourceTicker || "").trim();
    if (!ticker) {
      void message.error("未找到 ticker，无法加入股票池");
      return;
    }
    let pools = poolOptions;
    if (pools.length === 0) {
      pools = await loadPoolOptions();
    }

    let targetPoolId = Number(window.prompt("输入目标股票池 ID（为空则新建）", pools[0]?.id ? String(pools[0].id) : "") || "0");
    if (!targetPoolId) {
      const newPoolName = window.prompt("输入新股票池名称", "Agent 临时池")?.trim();
      if (!newPoolName) return;
      const createResp = await fetch(`${apiBase}/api/pools`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newPoolName, pool_type: "custom", description: "由 Agent 一键创建" }),
      });
      const createJson = await createResp.json().catch(() => null);
      if (!createResp.ok || !createJson?.id) {
        const detail = typeof createJson?.detail === "string" ? createJson.detail : `创建股票池失败 (${createResp.status})`;
        void message.error(detail);
        return;
      }
      targetPoolId = Number(createJson.id);
      void loadPoolOptions();
    }

    const addResp = await fetch(`${apiBase}/api/pools/${targetPoolId}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker,
        reason: turn.result?.summary || "由 Agent 建议加入",
        score: 0,
        snapshot: {
          key_points: turn.result?.key_points || [],
          actions: turn.result?.actions || [],
        },
      }),
    });
    const addJson = await addResp.json().catch(() => null);
    if (!addResp.ok) {
      const detail = typeof addJson?.detail === "string" ? addJson.detail : `加入股票池失败 (${addResp.status})`;
      void message.error(detail);
      return;
    }
    void message.success(`已加入股票池 #${targetPoolId} ${actionTargetText(ticker)}`);
  }

  async function animateAssistantReply(
    sessionId: string,
    baseTurns: ChatTurn[],
    fullText: string,
    model?: string,
    reasoningContent?: string,
  ) {
    const lastAssistant = baseTurns[baseTurns.length - 1];
    const total = fullText.length;
    if (total <= 0) {
      const finalTurns = [
        ...baseTurns.slice(0, -1),
        {
          role: "assistant" as const,
          content: "",
          model,
          reasoning_content: reasoningContent,
          sourceTicker: lastAssistant?.sourceTicker,
          result: lastAssistant?.result,
          usage: lastAssistant?.usage,
        },
      ];
      setSessionTurnsById(sessionId, finalTurns, scene);
      return;
    }
    const step = total > 1500 ? 18 : total > 700 ? 10 : 6;
    for (let i = 0; i < total; i += step) {
      if (stopStreamingRef.current) {
        break;
      }
      const partial = fullText.slice(0, i + step);
      const nextTurns = [
        ...baseTurns.slice(0, -1),
        {
          role: "assistant" as const,
          content: partial,
          model,
          sourceTicker: lastAssistant?.sourceTicker,
          result: lastAssistant?.result,
          usage: lastAssistant?.usage,
        },
      ];
      setSessionTurnsById(sessionId, nextTurns, scene);
      await new Promise((resolve) => setTimeout(resolve, 14));
    }
    // Final update: exact content + reasoning_content
    const finalTurns = [
      ...baseTurns.slice(0, -1),
      {
        role: "assistant" as const,
        content: fullText,
        model,
        reasoning_content: reasoningContent,
        sourceTicker: lastAssistant?.sourceTicker,
        result: lastAssistant?.result,
        usage: lastAssistant?.usage,
      },
    ];
    setSessionTurnsById(sessionId, finalTurns, scene);
  }

  function updateActiveTurns(turns: ChatTurn[]) {
    if (!activeSessionId) {
      const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const next: ChatSession = {
        id,
        title: buildSessionTitle(scene),
        scene,
        turns,
        updatedAt: Date.now(),
      };
      setSessions((current) => [next, ...current].slice(0, 30));
      setActiveSessionId(id);
      return;
    }
    setSessions((current) =>
      sortSessions(
        current.map((item) =>
          item.id === activeSessionId
            ? { ...item, scene, turns, updatedAt: Date.now() }
            : item,
        ),
      ),
    );
  }

  useEffect(() => {
    if (!draft) {
      return;
    }
    setScene(draft.scene);
    setUserInput(draft.userInput ?? "");
    setPayload(draft.payload ?? {});
    if (!activeSessionId) {
      createSession(draft.scene);
    }
  }, [draft]);

  const activeApiKey = provider === "deepseek" ? deepseekApiKey : kimiApiKey;
  const activeBaseUrl = provider === "deepseek" ? deepseekBaseUrl : kimiBaseUrl;
  const activeModel = provider === "deepseek"
    ? (deepseekModel || PROVIDER_DEFAULTS.deepseek.model)
    : (kimiModel || PROVIDER_DEFAULTS.kimi.model);
  const activeNormalizedApiKey = normalizeApiKey(activeApiKey);
  const configExpanded = agentConfigPanels.includes("agent_config");
  const effectivePayload = useMemo(() => {
    return {
      ...DEFAULT_AGENT_PROFILE_PAYLOAD,
      ...payload,
      agent_profile: {
        ...(DEFAULT_AGENT_PROFILE_PAYLOAD.agent_profile as Record<string, unknown>),
        ...((payload.agent_profile as Record<string, unknown> | undefined) || {}),
      },
    };
  }, [payload]);

  const payloadPreview = useMemo(() => {
    try {
      return JSON.stringify(effectivePayload, null, 2);
    } catch {
      return "{}";
    }
  }, [effectivePayload]);

  function updateActiveApiKey(nextValue: string) {
    if (provider === "deepseek") {
      setDeepseekApiKey(nextValue);
      return;
    }
    setKimiApiKey(nextValue);
  }

  function updateActiveBaseUrl(nextValue: string) {
    if (provider === "deepseek") {
      setDeepseekBaseUrl(nextValue);
      return;
    }
    setKimiBaseUrl(nextValue);
  }

  function updateActiveModel(nextValue: string) {
    if (provider === "deepseek") {
      setDeepseekModel(nextValue);
      return;
    }
    setKimiModel(nextValue);
  }

  function applyProviderConfig() {
    const normalizedKey = normalizeApiKey(activeApiKey);
    const normalizedUrl = (activeBaseUrl || "").trim();
    const normalizedModel = (activeModel || "").trim();
    if (provider === "deepseek") {
      setDeepseekApiKey(normalizedKey);
      setDeepseekBaseUrl(normalizedUrl);
      setDeepseekModel(normalizedModel || PROVIDER_DEFAULTS.deepseek.model);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("mq_deepseek_api_key", normalizedKey);
        window.localStorage.setItem("mq_deepseek_base_url", normalizedUrl || PROVIDER_DEFAULTS.deepseek.baseUrl);
        window.localStorage.setItem("mq_deepseek_model", normalizedModel || PROVIDER_DEFAULTS.deepseek.model);
      }
    } else {
      setKimiApiKey(normalizedKey);
      setKimiBaseUrl(normalizedUrl);
      setKimiModel(normalizedModel || PROVIDER_DEFAULTS.kimi.model);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("mq_kimi_api_key", normalizedKey);
        window.localStorage.setItem("mq_kimi_base_url", normalizedUrl || PROVIDER_DEFAULTS.kimi.baseUrl);
        window.localStorage.setItem("mq_kimi_model", normalizedModel || PROVIDER_DEFAULTS.kimi.model);
      }
    }
    void message.success(`${provider === "deepseek" ? "DeepSeek" : "Kimi"} 配置已更新，Key 状态：${maskKey(normalizedKey)}`);
  }

  async function testProviderConfig() {
    setConfigCheckStatus("检测中...");
    try {
      const response = await fetch(`${apiBase}/api/agent/invoke`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken.trim() ? { Authorization: `Bearer ${accessToken.trim()}` } : {}),
        },
        body: JSON.stringify({
          scene: "global_chat",
          user_input: "请只回复：OK",
          payload: {},
          messages: [],
          response_style: "natural",
          provider_config: {
            provider,
            api_key: activeNormalizedApiKey || undefined,
            base_url: activeBaseUrl.trim() || undefined,
            model: activeModel.trim() || undefined,
          },
        }),
      });
      const json = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = typeof json?.detail === "string" ? json.detail : `请求失败 (${response.status})`;
        setConfigCheckStatus(`失败：${detail}`);
        return;
      }
      setConfigCheckStatus(`成功：${provider === "deepseek" ? "DeepSeek" : "Kimi"} 可用（模型 ${activeModel}）`);
    } catch (exc) {
      const text = exc instanceof Error ? exc.message : "网络异常";
      setConfigCheckStatus(`失败：${text}`);
    }
  }

  const modelOptions = useMemo(() => {
    const baseModels = PROVIDER_MODEL_OPTIONS[provider];
    return baseModels.map((model) => {
      const multiplier = modelPriceMultiplierLabel(model);
      return {
        value: model,
        label: multiplier ? `${model} (${multiplier})` : model,
      };
    });
  }, [provider]);

  function renderStructuredBlocks(result: AgentResponse) {
    const hasAny = (result.key_points?.length || 0) > 0 || (result.risks?.length || 0) > 0 || (result.actions?.length || 0) > 0;
    if (!hasAny) return null;
    return (
      <Collapse
        size="small"
        ghost
        style={{ marginTop: 8 }}
        items={[
          {
            key: "structured",
            label: "结构化要点",
            children: (
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {result.key_points?.length ? (
                  <div>
                    <Text strong>关键点</Text>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {result.key_points.map((item, idx) => (
                        <li key={`kp-${idx}`}><Text>{item}</Text></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {result.risks?.length ? (
                  <div>
                    <Text strong>风险</Text>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {result.risks.map((item, idx) => (
                        <li key={`rk-${idx}`}><Text>{item}</Text></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {result.actions?.length ? (
                  <div>
                    <Text strong>建议动作</Text>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {result.actions.map((item, idx) => (
                        <li key={`ac-${idx}`}><Text>{item}</Text></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </Space>
            ),
          },
        ]}
      />
    );
  }

  function displayTextForTurn(turn: ChatTurn): string {
    if (turn.role !== "assistant" || !turn.result) return turn.content;
    if (structuredMode) {
      return renderAssistantText(turn.result);
    }
    const naturalText = (turn.result.natural_text || "").trim();
    if (naturalText) return naturalText;
    const summary = (turn.result.summary || "").trim();
    const rawText = (turn.result.raw_text || "").trim();
    const looksLikeJson = rawText.startsWith("{") && rawText.endsWith("}");
    if (summary) return summary;
    if (rawText && !looksLikeJson) return rawText;
    return turn.content || renderAssistantText(turn.result);
  }

  useEffect(() => {
    // Keep model aligned with selected provider to avoid showing stale cross-provider model
    const allowed = PROVIDER_MODEL_OPTIONS[provider];
    if (!allowed.includes(activeModel)) {
      updateActiveModel(PROVIDER_DEFAULTS[provider].model);
    }
  }, [provider, activeModel]);

  async function invoke() {
    const trimmed = userInput.trim();
    if (!trimmed) {
      setError("请先输入问题。");
      return;
    }
    stopStreamingRef.current = false;
    setLoading(true);
    setError("");
    try {
      const sessionId = ensureActiveSessionId(scene);
      const currentTurns = sessions.find((item) => item.id === sessionId)?.turns ?? chatTurns;
      const history = currentTurns.slice(-10).map((turn) => ({ role: turn.role, content: turn.content }));
      const response = await fetch(`${apiBase}/api/agent/invoke`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken.trim() ? { Authorization: `Bearer ${accessToken.trim()}` } : {}),
        },
        body: JSON.stringify({
          scene,
          user_input: trimmed,
          payload: effectivePayload,
          messages: history,
          response_style: structuredMode ? "structured" : "natural",
          provider_config: {
            provider,
            api_key: activeNormalizedApiKey || undefined,
            base_url: activeBaseUrl.trim() || undefined,
            model: activeModel.trim() || undefined,
          },
        }),
      });
      const json = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = typeof json?.detail === "string" ? json.detail : `请求失败 (${response.status})`;
        throw new Error(detail);
      }
      const result = json as AgentResponse;
      const naturalText = (result.natural_text || "").trim();
      const modeHint = result.render_mode || "natural";
      const assistantText = structuredMode || modeHint === "structured"
        ? renderAssistantText(result)
        : (naturalText || (result.summary || "").trim() || renderAssistantText(result));
      const sourceTicker = extractTickerFromPayload(effectivePayload);
      const stagedTurns: ChatTurn[] = [
        ...currentTurns,
        { role: "user", content: trimmed },
        {
          role: "assistant",
          content: "",
          model: result.model,
          sourceTicker,
          result,
          usage: result.usage,
        },
      ];
      setSessionTurnsById(sessionId, stagedTurns, scene);
      await animateAssistantReply(sessionId, stagedTurns, assistantText, result.model, result.reasoning_content || undefined);
      setUserInput("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Agent 调用失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Drawer
      title="AI 助手"
      width="96vw"
      open={open}
      onClose={onClose}
      destroyOnHidden
      styles={{ body: { padding: 0 } }}
    >
      <div className={`mq-agent-shell ${configExpanded ? "with-config" : "without-config"}`}>
        <aside className="mq-agent-sidebar">
          <div className="mq-agent-sidebar-head">
            <div>
              <Text strong>会话</Text>
              <div><Text type="secondary" style={{ fontSize: 12 }}>{sessions.length} 个会话</Text></div>
            </div>
            <Button type="primary" size="small" onClick={() => createSession(scene)}>新建</Button>
          </div>
          <List
            className="mq-agent-session-list"
            dataSource={sessions}
            locale={{ emptyText: "暂无会话" }}
            renderItem={(item) => (
              <List.Item
                className={`mq-agent-session-item ${item.id === activeSessionId ? "active" : ""}`}
                onClick={() => setActiveSessionId(item.id)}
                actions={[
                  <Button key="pin" size="small" type="text" onClick={(e) => { e.stopPropagation(); setActiveSessionId(item.id); togglePinSession(); }}>{item.pinned ? "取消置顶" : "置顶"}</Button>,
                  <Popconfirm
                    key="del"
                    title="删除该会话？"
                    description="删除后无法恢复。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={(e) => { e?.stopPropagation(); deleteSession(item.id); }}
                  >
                    <Button size="small" type="text" danger onClick={(e) => e.stopPropagation()}>删除</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={<span>{item.pinned ? "📌 " : ""}{item.title}</span>}
                  description={`${sceneLabel(item.scene)} · ${item.turns.length} 条`}
                />
              </List.Item>
            )}
          />
          <div className="mq-agent-sidebar-foot">
            <Space wrap>
              <Button size="small" onClick={renameActiveSession} disabled={!activeSessionId}>重命名</Button>
              <Button size="small" onClick={exportActiveSessionJson} disabled={!activeSessionId}>JSON</Button>
              <Button size="small" onClick={exportActiveSessionMarkdown} disabled={!activeSessionId}>MD</Button>
            </Space>
          </div>
        </aside>

        <main className="mq-agent-main">
          <header className="mq-agent-main-head">
            <Space wrap>
              <Tag color="blue">{sceneLabel(scene)}</Tag>
              <Select
                value={provider}
                onChange={(value) => {
                  const next = value as AgentProvider;
                  setProvider(next);
                  if (next === "deepseek") {
                    if (!deepseekBaseUrl.trim()) setDeepseekBaseUrl(PROVIDER_DEFAULTS.deepseek.baseUrl);
                    if (!deepseekModel.trim() || !PROVIDER_MODEL_OPTIONS.deepseek.includes(deepseekModel)) {
                      setDeepseekModel(PROVIDER_DEFAULTS.deepseek.model);
                    }
                  } else {
                    if (!kimiBaseUrl.trim()) setKimiBaseUrl(PROVIDER_DEFAULTS.kimi.baseUrl);
                    if (!kimiModel.trim() || !PROVIDER_MODEL_OPTIONS.kimi.includes(kimiModel)) {
                      setKimiModel(PROVIDER_DEFAULTS.kimi.model);
                    }
                  }
                }}
                style={{ width: 130 }}
                options={[
                  { value: "kimi", label: "Kimi" },
                  { value: "deepseek", label: "DeepSeek" },
                ]}
              />
              <Select value={activeModel} onChange={updateActiveModel} style={{ width: 250 }} options={modelOptions} />
              <Select
                value={selectedTemplateId}
                onChange={setSelectedTemplateId}
                style={{ width: 220 }}
                options={templates.map((tpl) => ({ value: tpl.id, label: `${tpl.name}${tpl.isDefault ? " (内置)" : ""}` }))}
              />
              <Button onClick={() => applyTemplateById(selectedTemplateId)}>应用模板</Button>
              <Button onClick={() => setAgentConfigPanels((prev) => (prev.includes("agent_config") ? [] : ["agent_config"]))}>
                {configExpanded ? "收起配置" : "展开配置"}
              </Button>
              <Space size={4}>
                <Switch size="small" checked={structuredMode} onChange={setStructuredMode} />
                <Text type="secondary" style={{ fontSize: 12 }}>结构化模式</Text>
              </Space>
              {provider === "deepseek" ? (
                <Space size={4}>
                  <Switch size="small" checked={showThinking} onChange={setShowThinking} />
                  <Text type="secondary" style={{ fontSize: 12 }}>显示思考</Text>
                </Space>
              ) : null}
            </Space>
          </header>

          {error ? <Alert type="error" showIcon message={error} style={{ margin: "8px 12px" }} /> : null}

          <div className="mq-agent-chat-scroll">
            {chatTurns.length === 0 ? <div className="mq-agent-empty">开始提问吧，我会结合当前页面数据给出建议。</div> : null}
            {chatTurns.map((turn, idx) => (
              <div key={`${turn.role}-${idx}`} className={`mq-agent-msg-row ${turn.role}`}>
                {turn.role === "assistant" ? <Avatar className="mq-agent-avatar bot">AI</Avatar> : null}
                <div className={`mq-agent-bubble ${turn.role}`}>
                  <div className="mq-agent-bubble-head">
                    <Space size={6} wrap>
                      <Tag color={turn.role === "user" ? "blue" : "green"}>{turn.role === "user" ? "你" : "助手"}</Tag>
                      {turn.model ? <Tag>{turn.model}</Tag> : null}
                      {turn.usage?.total_tokens ? <Tag>tokens: {turn.usage.total_tokens}</Tag> : null}
                    </Space>
                  </div>
                  {showThinking && turn.reasoning_content ? (
                    <Collapse size="small" style={{ marginBottom: 6 }} items={[{ key: "thinking", label: "思考过程", children: <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap", fontSize: 12 }}>{turn.reasoning_content}</Paragraph> }]} />
                  ) : null}
                  <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{displayTextForTurn(turn)}</Paragraph>
                  {turn.role === "assistant" && turn.result && !structuredMode ? renderStructuredBlocks(turn.result) : null}
                  {turn.role === "assistant" ? (
                    <Space wrap style={{ marginTop: 8 }}>
                      <Button size="small" onClick={() => void createPlanFromTurn(turn)}>创建计划</Button>
                      <Button size="small" onClick={() => void addWatchlistFromTurn(turn)}>加入观察列表</Button>
                      <Button size="small" onClick={() => void addToPoolFromTurn(turn)}>加入股票池</Button>
                    </Space>
                  ) : null}
                </div>
                {turn.role === "user" ? <Avatar className="mq-agent-avatar user">你</Avatar> : null}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          <footer className="mq-agent-composer">
            <TextArea
              value={userInput}
              onChange={(event) => setUserInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (!loading) {
                    void invoke();
                  }
                }
              }}
              autoSize={{ minRows: 2, maxRows: 6 }}
              placeholder="输入问题后按 Enter 发送，Shift+Enter 换行"
            />
            <div className="mq-agent-composer-bar">
              <Space>
                <Button type="primary" loading={loading} onClick={() => void invoke()}>发送</Button>
                {loading ? <Button danger onClick={() => { stopStreamingRef.current = true; }}>停止生成</Button> : null}
                <Button onClick={() => setUserInput("")}>清空输入</Button>
                <Button onClick={() => updateActiveTurns([])}>清空对话</Button>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前调用: {provider === "deepseek" ? "DeepSeek" : "Kimi"} · Key {maskKey(activeApiKey)}
              </Text>
            </div>
            <Alert type="warning" showIcon message="本结果仅用于研究与复盘，不构成确定性投资建议。" />
          </footer>
        </main>

        {configExpanded ? (
          <aside className="mq-agent-right">
            <Collapse
              ghost
              activeKey={agentConfigPanels}
              onChange={(keys) => {
                const next = Array.isArray(keys) ? keys.map((k) => String(k)) : [String(keys)];
                setAgentConfigPanels(next);
              }}
              items={[
                {
                  key: "agent_config",
                  label: "Agent 配置",
                  children: (
                    <Space direction="vertical" size={12} style={{ width: "100%" }}>
                      <Card size="small" className="mq-card" title="连接设置">
                        <Space direction="vertical" size={10} style={{ width: "100%" }}>
                          <div>
                            <Text type="secondary">访问口令（可选）</Text>
                            <Input.Password
                              value={accessToken}
                              onChange={(event) => setAccessToken(event.target.value)}
                              placeholder="输入后端配置的 AGENT_ACCESS_TOKEN"
                            />
                          </div>
                          <div>
                            <Text type="secondary">{provider === "deepseek" ? "DeepSeek" : "Kimi"} API Key</Text>
                            <Input.Password value={activeApiKey} onChange={(event) => updateActiveApiKey(event.target.value)} placeholder="sk-..." />
                            <Space style={{ marginTop: 8 }} wrap>
                              <Button size="small" onClick={applyProviderConfig}>更新配置</Button>
                              <Button size="small" onClick={() => void testProviderConfig()}>测试配置</Button>
                              <Text type="secondary">{maskKey(activeApiKey)}</Text>
                            </Space>
                            {configCheckStatus ? <div><Text type="secondary">连通性：{configCheckStatus}</Text></div> : null}
                          </div>
                          <div>
                            <Text type="secondary">Base URL</Text>
                            <Input value={activeBaseUrl} onChange={(event) => updateActiveBaseUrl(event.target.value)} placeholder={PROVIDER_DEFAULTS[provider].baseUrl} />
                          </div>
                        </Space>
                      </Card>

                      <Card size="small" className="mq-card" title="模板管理">
                        <Space direction="vertical" size={8} style={{ width: "100%" }}>
                          <Space wrap>
                            <Button size="small" onClick={saveCurrentAsTemplate}>另存模板</Button>
                            <Button size="small" onClick={overwriteSelectedTemplate}>覆盖模板</Button>
                            <Button size="small" danger onClick={deleteSelectedTemplate}>删除模板</Button>
                          </Space>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            支持变量：{"{{ticker}}"}、{"{{stock_summary.ticker}}"}、{"{{scene}}"}、{"{{today}}"}
                          </Text>
                        </Space>
                      </Card>

                      <Collapse
                        ghost
                        items={[
                          {
                            key: "ctx",
                            label: "上下文预览",
                            children: (
                              <Paragraph style={{ marginBottom: 0 }}>
                                <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{payloadPreview}</pre>
                              </Paragraph>
                            ),
                          },
                        ]}
                      />
                    </Space>
                  ),
                },
              ]}
            />
          </aside>
        ) : null}
      </div>
    </Drawer>
  );
}
