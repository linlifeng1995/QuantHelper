"use client";

import {
  Alert,
  Button,
  Card,
  Collapse,
  ConfigProvider,
  Drawer,
  Input,
  InputNumber,
  Layout,
  Menu,
  Modal,
  Progress,
  Row,
  Col,
  Select,
  Slider,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  theme,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DashboardOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  FundProjectionScreenOutlined,
  PlusOutlined,
  ReloadOutlined,
  StockOutlined,
} from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type SectionKey = "dashboard" | "update" | "screen" | "backtest";

type CacheSummary = {
  cache: {
    coverage_pct: number;
    expected_count: number;
    present_count: number;
    missing_count: number;
    missing_tickers: string[];
    stale_count: number;
    stale_tickers: string[];
    cache_start: string;
    cache_end: string;
  };
  readiness: {
    price_ok: boolean;
    fundamental_ok: boolean;
    factor_ok: boolean;
    issues: string[];
    repair_actions: string[];
    factor_status: Record<string, boolean>;
    fundamental_missing: Record<string, number>;
  };
  diagnostic: {
    status: "normal" | "suggest_update" | "needs_repair";
    status_text: string;
    can_screen: boolean;
    usage_status: "live" | "research" | "blocked";
    usage_label: string;
    usage_advice: string;
    lag_trading_days?: number | null;
    latest_trade_date?: string | null;
    price_complete: boolean;
    price_current: boolean;
    fundamental_ok: boolean;
    factor_ok: boolean;
    recommended_action?: UpdateAction | null;
    recommended_label: string;
    conclusion: string;
    full_conclusion: string;
    fundamental_explanation: string;
    anomalies: {
      missing_price_count: number;
      stale_price_count: number;
      fundamental_missing_total: number;
      fundamental_missing: Record<string, number>;
      unavailable_factors: string[];
      issues: string[];
      repair_actions: string[];
      missing_tickers: string[];
      stale_tickers: string[];
    };
  };
  latest_task?: UpdateTask | null;
  pool_count: number;
  price_symbol_count: number;
  price_row_count: number;
};

type FactorTemplate = {
  weights: Record<string, number>;
  filters: Record<string, number | boolean>;
};

type IndustryOption = {
  name: string;
  count: number;
};

type BacktestStrategyMeta = {
  category: string;
  description: string;
};

type TradeSignal = {
  date: string;
  ticker: string;
  action: "buy" | "sell";
  action_text: string;
  price: number;
  strategy: string;
  reason: string;
};

type TradeAdvice = {
  ticker: string;
  strategy: string;
  status: string;
  last_price: number;
  reference_stop: number;
  risk_level: "低" | "中" | "高" | string;
  suggestion: string;
  last_entry_date?: string | null;
  last_exit_date?: string | null;
};

type ScreenRow = {
  ticker: string;
  名称?: string;
  行业?: string;
  综合评分?: number;
  动量分?: number;
  质量分?: number;
  估值分?: number;
  成长分?: number;
  风险控制分?: number;
  资金情绪分?: number;
  ROE?: number;
  GROWTH?: number;
  PE?: number;
  PB?: number;
  ret_20d?: number;
  ret_60d?: number;
  ret_120d?: number;
  vol_60d?: number;
  max_drawdown_120d?: number;
  风格标签?: string[];
  进攻分?: number;
  防守分?: number;
  估值压力?: number;
  波动风险?: number;
  回撤风险?: number;
  流动性风险?: number;
  决策解释?: string;
  行业内动量分位?: number;
  行业内质量分位?: number;
  行业内估值分位?: number;
  入选原因?: string;
  added_at?: string;
  updated_at?: string;
};

type UpdateAction = "sync_latest" | "repair_price" | "refresh_fundamentals" | "rebuild_price";

type UpdateTask = {
  id: string;
  action: UpdateAction;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  chunk_progress: number;
  message: string;
  result?: {
    stats?: Record<string, number>;
    cache_range?: string[];
  } | null;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number | null;
};

type BacktestResult = {
  metrics: Record<string, number | null>;
  strategies: Array<Record<string, string | number | null>>;
  pool: ScreenRow[];
  stats: Record<string, number>;
  cache_range: string[];
  price_shape: { rows: number; columns: number };
  preflight: Record<string, unknown>;
  equity_curve: Array<{ date: string; equity: number }>;
  benchmark_curve?: Array<{ date: string; equity: number }>;
  benchmark_available: boolean;
  signals: TradeSignal[];
  advice: TradeAdvice[];
  selected_strategies?: string[];
};

const updateActionLabels: Record<UpdateAction, string> = {
  sync_latest: "更新到最新交易日",
  repair_price: "补齐缺失/落后的行情",
  refresh_fundamentals: "更新财务与估值数据",
  rebuild_price: "重新下载全部历史行情",
};

const actionMeta: Record<UpdateAction, { when: string; updates: string; overwrite: string; duration: string; risk: "低" | "中" | "高" }> = {
  sync_latest: {
    when: "缓存未覆盖最新交易日，或需要刷新股票池快照时。",
    updates: "增量行情、股票池、基础面快照。",
    overwrite: "不会清空已有行情，只追加缺失日期。",
    duration: "通常数分钟，取决于并发数和待补日期。",
    risk: "低",
  },
  repair_price: {
    when: "概览提示有缺失价格或日期落后标的时。",
    updates: "仅补齐异常股票的行情缓存。",
    overwrite: "不会清空缓存，只合并修复结果。",
    duration: "通常较快，取决于异常股票数量。",
    risk: "低",
  },
  refresh_fundamentals: {
    when: "ROE、GROWTH 或估值字段缺失影响因子时。",
    updates: "财务指标、估值和股票池基础字段。",
    overwrite: "只更新股票池字段，不重建价格缓存。",
    duration: "通常数分钟。",
    risk: "中",
  },
  rebuild_price: {
    when: "缓存严重损坏，普通修复无法恢复时。",
    updates: "从起始日期重新下载全市场历史行情。",
    overwrite: "会重新生成价格缓存，耗时和请求量都较高。",
    duration: "可能需要较长时间。",
    risk: "高",
  },
};

const templateDescriptions: Record<string, string> = {
  稳健质量股: "默认稳健模板，质量和风险控制权重更高，并限制高估值暴露。",
  趋势质量股: "进攻型策略，适合强势行情，偏向动量与盈利质量。",
  低估值修复股: "适合估值修复或防守切换，偏向低 PE/PB 和盈利稳定性。",
  高成长强势股: "高波动高估值风险更明显，偏向高营收增长和价格强势。",
};

const factorNames = ["动量", "质量", "估值", "成长", "风险控制", "资金情绪"];

function numberText(value: unknown, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function percentText(value: unknown, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "-";
}

function metricPercent(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "-";
}

function boolTag(ok: boolean, okText = "可用", badText = "需处理") {
  return <Tag color={ok ? "green" : "orange"}>{ok ? okText : badText}</Tag>;
}

function scoreColor(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "default";
  if (value >= 75) return "green";
  if (value >= 55) return "blue";
  return "orange";
}

function riskColor(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "default";
  if (value >= 75) return "red";
  if (value >= 55) return "orange";
  return "green";
}

function riskText(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未知";
  if (value >= 75) return "高";
  if (value >= 55) return "中";
  return "低";
}

function getStyleTags(row: ScreenRow) {
  return Array.isArray(row.风格标签) && row.风格标签.length ? row.风格标签 : splitReasonAndRisk(row.入选原因).reasons.slice(0, 3);
}

function riskSummaryTags(row: ScreenRow) {
  const items = [
    ["估值压力", row.估值压力],
    ["波动风险", row.波动风险],
    ["回撤风险", row.回撤风险],
    ["流动性风险", row.流动性风险],
  ] as const;
  return items.filter(([, value]) => typeof value === "number" && Number.isFinite(value)).sort((a, b) => Number(b[1]) - Number(a[1]));
}

function splitReasonAndRisk(value?: string) {
  const [reasonPart = "", riskPart = ""] = String(value ?? "").split(" | 风险：");
  const reasons = reasonPart.split("；").map((item) => item.trim()).filter(Boolean);
  const risks = riskPart.split("；").map((item) => item.trim()).filter(Boolean).map((item) => item === "未发现主要量化风险" ? "暂未触发当前规则下的主要风险项" : item);
  return { reasons, risks };
}

export default function Home() {
  const [activeSection, setActiveSection] = useState<SectionKey>("dashboard");
  const [summary, setSummary] = useState<CacheSummary | null>(null);
  const [templates, setTemplates] = useState<Record<string, FactorTemplate>>({});
  const [selectedTemplate, setSelectedTemplate] = useState("稳健质量股");
  const [topN, setTopN] = useState(30);
  const [industryOptions, setIndustryOptions] = useState<IndustryOption[]>([]);
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [industryNeutral, setIndustryNeutral] = useState(true);
  const [allowIncomplete, setAllowIncomplete] = useState(false);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [filters, setFilters] = useState<Record<string, number | boolean>>({});
  const [rows, setRows] = useState<ScreenRow[]>([]);
  const [removed, setRemoved] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [updateToken, setUpdateToken] = useState("");
  const [updateHttpUrl, setUpdateHttpUrl] = useState("http://teajoin.com");
  const [updateStartDate, setUpdateStartDate] = useState("2025-06-01");
  const [downloadWorkers, setDownloadWorkers] = useState(2);
  const [includeStaleTickers, setIncludeStaleTickers] = useState(true);
  const [updateTask, setUpdateTask] = useState<UpdateTask | null>(null);
  const [taskHistory, setTaskHistory] = useState<UpdateTask[]>([]);
  const [updateTaskLoading, setUpdateTaskLoading] = useState(false);
  const [tickerModal, setTickerModal] = useState<{ title: string; tickers: string[] } | null>(null);
  const [selectedStock, setSelectedStock] = useState<ScreenRow | null>(null);
  const [watchlist, setWatchlist] = useState<ScreenRow[]>([]);
  const [watchlistLoading, setWatchlistLoading] = useState(false);
  const [backtestMode, setBacktestMode] = useState<"fixed" | "rolling">("fixed");
  const [backtestSource, setBacktestSource] = useState<"screen" | "watchlist">("screen");
  const [backtestStartDate, setBacktestStartDate] = useState("2025-06-01");
  const [backtestEndDate, setBacktestEndDate] = useState("2025-12-01");
  const [backtestInitCash, setBacktestInitCash] = useState(100000);
  const [backtestFees, setBacktestFees] = useState(0.001);
  const [backtestSlippage, setBacktestSlippage] = useState(0.001);
  const [fastWindow, setFastWindow] = useState(10);
  const [slowWindow, setSlowWindow] = useState(50);
  const [trailStop, setTrailStop] = useState(0.08);
  const [momWindow, setMomWindow] = useState(20);
  const [topPct, setTopPct] = useState(0.2);
  const [rsiWindow, setRsiWindow] = useState(14);
  const [rsiBuy, setRsiBuy] = useState(30);
  const [rsiSell, setRsiSell] = useState(55);
  const [holdingCount, setHoldingCount] = useState(30);
  const [allowIncompleteBacktest, setAllowIncompleteBacktest] = useState(false);
  const [allowFallbackUniverse, setAllowFallbackUniverse] = useState(false);
  const [benchmarkName, setBenchmarkName] = useState("无");
  const [availableStrategies, setAvailableStrategies] = useState<Record<string, BacktestStrategyMeta>>({});
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(["双均线趋势"]);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);

  const templateOptions = useMemo(() => Object.keys(templates), [templates]);
  const industrySelectOptions = useMemo(
    () => industryOptions.map((item) => ({ value: item.name, label: `${item.name} (${item.count})` })),
    [industryOptions],
  );
  const strategyOptions = useMemo(
    () => Object.entries(availableStrategies).map(([value, meta]) => ({ value, label: `${value} · ${meta.category}` })),
    [availableStrategies],
  );

  const loadDashboard = useCallback(async () => {
    setError("");
    try {
      const [summaryRes, templateRes, historyRes, watchlistRes, industriesRes, strategiesRes] = await Promise.all([
        fetch(`${API_BASE}/api/cache/summary`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/factor/templates`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/tasks/history?limit=8`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/watchlist`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/pool/industries`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/backtest/strategies`, { cache: "no-store" }),
      ]);
      if (!summaryRes.ok || !templateRes.ok || !historyRes.ok || !watchlistRes.ok || !industriesRes.ok || !strategiesRes.ok) {
        throw new Error("无法连接 MyQuant API");
      }
      const summaryJson = (await summaryRes.json()) as CacheSummary;
      const templateJson = (await templateRes.json()) as { templates: Record<string, FactorTemplate> };
      const historyJson = (await historyRes.json()) as { tasks: UpdateTask[] };
      const watchlistJson = (await watchlistRes.json()) as { rows: ScreenRow[] };
      const industriesJson = (await industriesRes.json()) as { industries: IndustryOption[] };
      const strategiesJson = (await strategiesRes.json()) as { strategies: Record<string, BacktestStrategyMeta> };
      setSummary(summaryJson);
      setTemplates(templateJson.templates);
      setTaskHistory(historyJson.tasks ?? []);
      setWatchlist(watchlistJson.rows ?? []);
      setIndustryOptions(industriesJson.industries ?? []);
      setAvailableStrategies(strategiesJson.strategies ?? {});
      const firstTemplate = templateJson.templates[selectedTemplate] ? selectedTemplate : Object.keys(templateJson.templates)[0];
      if (firstTemplate) {
        setSelectedTemplate(firstTemplate);
        setWeights(templateJson.templates[firstTemplate].weights);
        setFilters(templateJson.templates[firstTemplate].filters);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    }
  }, [selectedTemplate]);

  useEffect(() => {
    let cancelled = false;

    async function initDashboard() {
      try {
        const [summaryRes, templateRes, historyRes, watchlistRes, industriesRes, strategiesRes] = await Promise.all([
          fetch(`${API_BASE}/api/cache/summary`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/factor/templates`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/tasks/history?limit=8`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/watchlist`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/pool/industries`, { cache: "no-store" }),
          fetch(`${API_BASE}/api/backtest/strategies`, { cache: "no-store" }),
        ]);
        if (!summaryRes.ok || !templateRes.ok || !historyRes.ok || !watchlistRes.ok || !industriesRes.ok || !strategiesRes.ok) {
          throw new Error("无法连接 MyQuant API");
        }
        const summaryJson = (await summaryRes.json()) as CacheSummary;
        const templateJson = (await templateRes.json()) as { templates: Record<string, FactorTemplate> };
        const historyJson = (await historyRes.json()) as { tasks: UpdateTask[] };
        const watchlistJson = (await watchlistRes.json()) as { rows: ScreenRow[] };
        const industriesJson = (await industriesRes.json()) as { industries: IndustryOption[] };
        const strategiesJson = (await strategiesRes.json()) as { strategies: Record<string, BacktestStrategyMeta> };
        if (cancelled) {
          return;
        }
        setSummary(summaryJson);
        setTemplates(templateJson.templates);
        setTaskHistory(historyJson.tasks ?? []);
        setWatchlist(watchlistJson.rows ?? []);
        setIndustryOptions(industriesJson.industries ?? []);
        setAvailableStrategies(strategiesJson.strategies ?? {});
        const firstTemplate = templateJson.templates["稳健质量股"] ? "稳健质量股" : templateJson.templates["趋势质量股"] ? "趋势质量股" : Object.keys(templateJson.templates)[0];
        if (firstTemplate) {
          setSelectedTemplate(firstTemplate);
          setWeights(templateJson.templates[firstTemplate].weights);
          setFilters(templateJson.templates[firstTemplate].filters);
        }
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : "加载失败");
        }
      }
    }

    void initDashboard();
    return () => {
      cancelled = true;
    };
  }, []);

  function applyTemplate(name: string) {
    setSelectedTemplate(name);
    const template = templates[name];
    if (template) {
      setWeights(template.weights);
      setFilters(template.filters);
    }
  }

  async function runScreen() {
    if (diagnostic && !diagnostic.can_screen) {
      setError("当前数据不适合筛选，请先到数据更新页处理。 ");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/screen`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_name: selectedTemplate,
          top_n: topN,
          industries: selectedIndustries,
          weights,
          filters,
          industry_neutral: industryNeutral,
          allow_incomplete_factors: allowIncomplete,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        const detail = payload?.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message ?? "筛选失败");
      }
      setRows(payload.rows ?? []);
      setRemoved(payload.removed ?? {});
      await loadDashboard();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "筛选失败");
    } finally {
      setLoading(false);
    }
  }

  async function addToWatchlist(row: ScreenRow) {
    setWatchlistLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/watchlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(row),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(typeof payload?.detail === "string" ? payload.detail : "加入观察池失败");
      }
      setWatchlist(payload.rows ?? []);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加入观察池失败");
    } finally {
      setWatchlistLoading(false);
    }
  }

  async function removeFromWatchlist(ticker: string) {
    setWatchlistLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(typeof payload?.detail === "string" ? payload.detail : "移出观察池失败");
      }
      setWatchlist(payload.rows ?? []);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "移出观察池失败");
    } finally {
      setWatchlistLoading(false);
    }
  }

  function handleRowsForBacktest(source: "screen" | "watchlist" = "screen") {
    setBacktestSource(source);
    setActiveSection("backtest");
  }

  async function runBacktest() {
    if (backtestMode === "rolling") {
      setError("滚动选股回测需要逐期历史因子快照，当前已预留模式说明，暂不生成可能误导的结果。");
      return;
    }
    if (rsiBuy > 50 || rsiSell < 50) {
      setError("RSI 参数不符合后端校验：买入阈值需小于等于 50，卖出阈值通常应大于等于 50。");
      return;
    }
    if (!selectedStrategies.length) {
      setError("请至少选择一个回测策略。");
      return;
    }
    const sourceRows = backtestSource === "watchlist" ? watchlist : rows;
    const tickers = sourceRows.slice(0, holdingCount).map((row) => row.ticker);
    if (!tickers.length) {
      setError("请先在筛选择股页执行筛选，或将股票加入观察池。 ");
      return;
    }
    setBacktestLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tickers,
          strategy_names: selectedStrategies,
          start_date: backtestStartDate,
          end_date: backtestEndDate,
          init_cash: backtestInitCash,
          fees: backtestFees,
          slippage: backtestSlippage,
          fast_window: fastWindow,
          slow_window: slowWindow,
          trail_stop: trailStop,
          mom_window: momWindow,
          top_pct: topPct,
          rsi_window: rsiWindow,
          rsi_buy: rsiBuy,
          rsi_sell: rsiSell,
          holding_count: holdingCount,
          allow_incomplete_data: allowIncompleteBacktest,
          allow_fallback_universe: allowFallbackUniverse,
          benchmark_name: benchmarkName,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        const detail = payload?.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message ?? "回测失败");
      }
      setBacktestResult(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "回测失败");
    } finally {
      setBacktestLoading(false);
    }
  }

  async function startUpdateTask(action: UpdateAction) {
    setUpdateTaskLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          token: updateToken || undefined,
          http_url: updateHttpUrl,
          start_date: updateStartDate,
          download_workers: downloadWorkers,
          include_stale_tickers: includeStaleTickers,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(typeof payload?.detail === "string" ? payload.detail : "启动任务失败");
      }
      setUpdateTask(payload);
      setActiveSection("update");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动任务失败");
    } finally {
      setUpdateTaskLoading(false);
    }
  }

  useEffect(() => {
    if (!updateTask?.id || !["queued", "running"].includes(updateTask.status)) {
      return;
    }

    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/tasks/${updateTask.id}`, { cache: "no-store" });
        if (response.status === 404) {
          if (!cancelled) {
            setUpdateTask((current) => current ? {
              ...current,
              status: "failed",
              message: "任务状态已丢失",
              error: "后端开发服务发生热重载，内存中的任务状态已清空。请重新启动任务。",
            } : current);
          }
          return;
        }
        if (!response.ok) {
          throw new Error("查询任务状态失败");
        }
        const payload = (await response.json()) as UpdateTask;
        if (!cancelled) {
          setUpdateTask(payload);
          if (["succeeded", "failed"].includes(payload.status)) {
            void loadDashboard();
          }
        }
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : "查询任务状态失败");
        }
      }
    }, 1200);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadDashboard, updateTask?.id, updateTask?.status]);

  const columns: ColumnsType<ScreenRow> = [
    { title: "代码", dataIndex: "ticker", width: 110 },
    { title: "名称", dataIndex: "名称", width: 110 },
    { title: "行业", dataIndex: "行业", width: 130 },
    {
      title: "综合评分",
      dataIndex: "综合评分",
      width: 110,
      sorter: (a, b) => (a.综合评分 ?? 0) - (b.综合评分 ?? 0),
      render: (value) => <Text strong>{numberText(value)}</Text>,
    },
    {
      title: "风格标签",
      dataIndex: "风格标签",
      width: 220,
      render: (_, row) => (
        <Space wrap size={4}>
          {getStyleTags(row).slice(0, 3).map((item) => <Tag color="blue" key={item}>{item}</Tag>)}
        </Space>
      ),
    },
    {
      title: "风险分层",
      width: 300,
      render: (_, row) => {
        const riskLayers = riskSummaryTags(row).slice(0, 3);
        const risks = splitReasonAndRisk(row.入选原因).risks;
        return (
          <Space wrap size={4}>
            {riskLayers.length ? riskLayers.map(([label, value]) => <Tag color={riskColor(value)} key={label}>{label}{riskText(value)}</Tag>) : null}
            {riskLayers.length ? null : (risks.length ? risks : ["暂未触发当前规则下的主要风险项"]).slice(0, 2).map((item) => (
              <Tag color={item.includes("暂未") ? "green" : "orange"} key={item}>{item}</Tag>
            ))}
          </Space>
        );
      },
    },
    {
      title: "攻防",
      width: 150,
      render: (_, row) => (
        <Space wrap size={4}>
          <Tag color={scoreColor(row.进攻分)}>攻 {numberText(row.进攻分)}</Tag>
          <Tag color={scoreColor(row.防守分)}>守 {numberText(row.防守分)}</Tag>
        </Space>
      ),
    },
    {
      title: "操作",
      width: 180,
      render: (_, row) => (
        <Space>
          <Button size="small" onClick={() => setSelectedStock(row)}>查看详情</Button>
          <Button size="small" icon={<PlusOutlined />} loading={watchlistLoading} onClick={() => void addToWatchlist(row)} disabled={watchlist.some((item) => item.ticker === row.ticker)}>加入观察池</Button>
        </Space>
      ),
    },
  ];

  const factorStatus = summary?.readiness.factor_status ?? {};
  const cache = summary?.cache;
  const readiness = summary?.readiness;
  const diagnostic = summary?.diagnostic;
  const anomalies = diagnostic?.anomalies;
  const recommendedAction = diagnostic?.recommended_action ?? null;
  const statusColor = diagnostic?.usage_status === "live" ? "green" : diagnostic?.usage_status === "research" ? "gold" : "red";
  const canScreenText = diagnostic?.usage_label ?? (diagnostic?.can_screen ? "可用于选股" : "选股前建议处理");
  const pageTitle = activeSection === "dashboard" ? "数据概览" : activeSection === "update" ? "数据更新" : activeSection === "screen" ? "多因子选股" : "策略回测";
  const pageSubtitle = activeSection === "dashboard"
    ? "诊断当前数据是否可信，并给出下一步推荐操作。"
    : activeSection === "update"
      ? "根据概览诊断执行对应修复动作。"
      : activeSection === "screen"
        ? "调整风险过滤和因子权重，调用 FastAPI 执行真实筛选。"
        : "使用筛选结果或观察池，基于本地价格缓存验证策略表现。";
  const templateDescription = templateDescriptions[selectedTemplate] ?? "当前模板会按风险过滤和多因子权重生成候选观察名单。";
  const removedTotal = Object.values(removed).reduce((total, value) => total + Number(value || 0), 0);
  const afterFilterCount = Math.max(0, (summary?.pool_count ?? 0) - removedTotal);
  const topRemoved = Object.entries(removed).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 3);
  const strongestFilter = topRemoved[0];
  const industryScopeText = selectedIndustries.length ? `行业范围：${selectedIndustries.join("、")}。` : "行业范围：全市场。";
  const filterSummary = rows.length
    ? `${industryScopeText}本次从 ${(summary?.pool_count ?? 0).toLocaleString()} 只股票中筛选，硬过滤后约保留 ${afterFilterCount.toLocaleString()} 只，最终展示 ${rows.length} 只。${topRemoved.length ? `主要过滤项：${topRemoved.map(([key, value]) => `${key} ${value} 只`).join("、")}。` : "未触发明显硬过滤项。"}${strongestFilter ? `本次结果受 ${strongestFilter[0]} 条件影响较大。` : ""}`
    : "执行筛选后会在这里显示过滤过程摘要。";
  const screenStatusTitle = diagnostic?.can_screen
    ? diagnostic.price_current
      ? "当前数据可用于选股，且已覆盖最新交易日。"
      : `当前结果仅适合研究，不建议直接实盘使用。本地行情缓存至 ${cache?.cache_end ?? "-"}，最新交易日为 ${diagnostic.latest_trade_date ?? "待确认"}。若要基于最新行情筛选，建议先更新到最新交易日。`
    : "当前数据不适合筛选，请先到数据更新页处理。";
  const backtestRows = backtestSource === "watchlist" ? watchlist : rows;
  const equityPoints = backtestResult?.equity_curve ?? [];
  const benchmarkPoints = backtestResult?.benchmark_curve ?? [];
  const chartValues = [...equityPoints.map((point) => point.equity), ...benchmarkPoints.map((point) => point.equity)];
  const equityMin = chartValues.length ? Math.min(...chartValues) : 0;
  const equityMax = chartValues.length ? Math.max(...chartValues) : 1;
  function buildPolyline(points: Array<{ date: string; equity: number }>) {
    return points.map((point, index) => {
      const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 100;
      const y = equityMax === equityMin ? 50 : 100 - ((point.equity - equityMin) / (equityMax - equityMin)) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
  }
  const equityPolyline = buildPolyline(equityPoints);
  const benchmarkPolyline = buildPolyline(benchmarkPoints);

  const strategyColumns: ColumnsType<Record<string, string | number | null>> = [
    { title: "策略", dataIndex: "策略" },
    { title: "类型", dataIndex: "类型", render: (value) => value ?? "-" },
    { title: "总收益率", dataIndex: "总收益率", render: (value) => metricPercent(value) },
    { title: "最大回撤", dataIndex: "最大回撤", render: (value) => metricPercent(value) },
    { title: "夏普比率", dataIndex: "夏普比率", render: (value) => numberText(value, 4) },
    { title: "买入信号", dataIndex: "买入信号数", render: (value) => numberText(value, 0) },
    { title: "卖出信号", dataIndex: "卖出信号数", render: (value) => numberText(value, 0) },
  ];
  const adviceColumns: ColumnsType<TradeAdvice> = [
    { title: "代码", dataIndex: "ticker", width: 110 },
    { title: "策略", dataIndex: "strategy", width: 150 },
    { title: "状态", dataIndex: "status", width: 110, render: (value, row) => <Tag color={row.risk_level === "高" ? "red" : row.risk_level === "中" ? "gold" : "green"}>{value}</Tag> },
    { title: "现价", dataIndex: "last_price", width: 100, render: (value) => numberText(value, 2) },
    { title: "止损复核价", dataIndex: "reference_stop", width: 120, render: (value) => numberText(value, 2) },
    { title: "最近买入", dataIndex: "last_entry_date", width: 110, render: (value) => value ?? "-" },
    { title: "最近卖出", dataIndex: "last_exit_date", width: 110, render: (value) => value ?? "-" },
    { title: "辅助建议", dataIndex: "suggestion", width: 420 },
  ];
  const signalColumns: ColumnsType<TradeSignal> = [
    { title: "日期", dataIndex: "date", width: 110 },
    { title: "代码", dataIndex: "ticker", width: 110 },
    { title: "策略", dataIndex: "strategy", width: 150 },
    { title: "动作", dataIndex: "action_text", width: 90, render: (value, row) => <Tag color={row.action === "buy" ? "green" : "red"}>{value}</Tag> },
    { title: "价格", dataIndex: "price", width: 100, render: (value) => numberText(value, 2) },
    { title: "触发原因", dataIndex: "reason", width: 360 },
  ];
  const backtestPoolColumns: ColumnsType<ScreenRow> = [
    { title: "代码", dataIndex: "ticker" },
    { title: "名称", dataIndex: "名称" },
    { title: "行业", dataIndex: "行业" },
    { title: "综合评分", dataIndex: "综合评分", render: (value) => numberText(value) },
  ];
  const watchlistColumns: ColumnsType<ScreenRow> = [
    { title: "代码", dataIndex: "ticker", width: 120 },
    { title: "名称", dataIndex: "名称", width: 120, render: (value, row) => value ?? row.ticker },
    { title: "行业", dataIndex: "行业", width: 120, render: (value) => value ?? "-" },
    { title: "加入时评分", dataIndex: "综合评分", width: 110, render: (value) => numberText(value) },
    {
      title: "当前评分变化",
      width: 130,
      render: (_, row) => {
        const current = rows.find((item) => item.ticker === row.ticker);
        if (!current || typeof current.综合评分 !== "number" || typeof row.综合评分 !== "number") return "待复筛";
        const diff = current.综合评分 - row.综合评分;
        return <Tag color={diff >= 0 ? "green" : "orange"}>{diff >= 0 ? "+" : ""}{diff.toFixed(1)}</Tag>;
      },
    },
    { title: "最新数据日期", width: 120, render: () => cache?.cache_end ?? "-" },
    {
      title: "买入理由是否仍成立",
      width: 190,
      render: (_, row) => {
        const current = rows.find((item) => item.ticker === row.ticker);
        const ok = !current || typeof current.综合评分 !== "number" || typeof row.综合评分 !== "number" || current.综合评分 >= row.综合评分 - 8;
        return <Tag color={ok ? "green" : "orange"}>{ok ? "需结合盘面复核" : "因子明显走弱"}</Tag>;
      },
    },
    {
      title: "当前触发风险项",
      width: 240,
      render: (_, row) => (
        <Space wrap size={4}>
          {riskSummaryTags(row).slice(0, 3).map(([label, value]) => <Tag color={riskColor(value)} key={label}>{label}{riskText(value)}</Tag>)}
        </Space>
      ),
    },
    {
      title: "交易前约束",
      width: 260,
      render: () => <Text type="secondary">止损/止盈、财报日期、涨跌停可交易性需在下单前结合实时行情确认</Text>,
    },
    { title: "加入时间", dataIndex: "added_at", width: 180, render: (value) => value ?? "-" },
    {
      title: "操作",
      width: 150,
      render: (_, row) => (
        <Space>
          <Button size="small" onClick={() => setSelectedStock(row)}>查看详情</Button>
          <Button size="small" danger icon={<DeleteOutlined />} loading={watchlistLoading} onClick={() => void removeFromWatchlist(row.ticker)}>移出</Button>
        </Space>
      ),
    },
  ];

  const historyColumns: ColumnsType<UpdateTask> = [
    { title: "更新时间", dataIndex: "finished_at", width: 180, render: (_, row) => row.finished_at ?? row.updated_at ?? row.created_at ?? "-" },
    { title: "类型", dataIndex: "action", width: 170, render: (value: UpdateAction) => updateActionLabels[value] ?? value },
    { title: "状态", dataIndex: "status", width: 100, render: (value: UpdateTask["status"]) => <Tag color={value === "succeeded" ? "green" : value === "failed" ? "red" : "blue"}>{value}</Tag> },
    { title: "耗时", dataIndex: "duration_seconds", width: 90, render: (value?: number | null) => typeof value === "number" ? `${Math.round(value)} 秒` : "-" },
    { title: "结果", dataIndex: "result", render: (_, row) => row.error || row.message || "-" },
  ];

  function goRecommendedAction() {
    if (!recommendedAction) {
      return;
    }
    setActiveSection("update");
  }

  function confirmStartUpdate(action: UpdateAction) {
    if (action !== "rebuild_price") {
      void startUpdateTask(action);
      return;
    }
    Modal.confirm({
      title: "确认重新下载全部历史行情？",
      content: "这会重新生成价格缓存，耗时和请求量较高。仅建议在普通修复无法解决缓存异常时执行。",
      okText: "确认重建",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => startUpdateTask(action),
    });
  }

  return (
    <ConfigProvider
      theme={{
        algorithm: [theme.defaultAlgorithm, theme.compactAlgorithm],
        token: {
          colorPrimary: "#2563eb",
          colorInfo: "#1677ff",
          colorSuccess: "#16a34a",
          colorWarning: "#d97706",
          colorError: "#dc2626",
          colorBgLayout: "#f3f6fb",
          colorBgContainer: "#ffffff",
          colorBgElevated: "#ffffff",
          colorBorder: "#d8dee8",
          colorText: "#172033",
          colorTextSecondary: "#667085",
          borderRadius: 6,
          fontFamily: "Arial, Helvetica, sans-serif",
        },
      }}
    >
      <Layout className="mq-shell">
        <Sider width={236} className="mq-sider" breakpoint="lg" collapsedWidth="0">
          <div className="mq-logo">
            <span className="mq-logo-mark"><FundProjectionScreenOutlined /></span>
            <span>MyQuant</span>
          </div>
          <Menu
            mode="inline"
            selectedKeys={[activeSection]}
            onClick={({ key }) => setActiveSection(key as SectionKey)}
            items={[
              { key: "dashboard", icon: <DashboardOutlined />, label: "数据概览" },
              { key: "update", icon: <DatabaseOutlined />, label: "数据更新" },
              { key: "screen", icon: <ExperimentOutlined />, label: "筛选择股" },
              { key: "backtest", icon: <StockOutlined />, label: "策略回测" },
            ]}
          />
        </Sider>
        <Layout>
          <Header className="mq-header">
            <div className="mq-title-row">
              <div>
                <h1 className="mq-page-title">{pageTitle}</h1>
                <p className="mq-page-subtitle">{pageSubtitle}</p>
              </div>
              <Button icon={<ReloadOutlined />} onClick={loadDashboard}>刷新</Button>
            </div>
          </Header>
          <Content className="mq-content">
            {error ? <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} /> : null}

            {activeSection === "dashboard" ? (
              <>
                <Card className="mq-card mq-health-card">
                  <div className="mq-health-main">
                    <div>
                      <Space wrap size={8}>
                        <Tag color={statusColor}>{diagnostic?.status_text ?? "加载中"}</Tag>
                        <Tag color={diagnostic?.can_screen ? "green" : "orange"}>{canScreenText}</Tag>
                        {typeof diagnostic?.lag_trading_days === "number" ? <Tag>落后 {diagnostic.lag_trading_days} 个交易日</Tag> : null}
                      </Space>
                      <h2 className="mq-health-title">{diagnostic?.conclusion ?? "正在读取本地缓存诊断。"}</h2>
                      <p className="mq-health-conclusion">{diagnostic?.full_conclusion ?? "正在汇总行情、基础面、因子和最新交易日状态。"}</p>
                      {diagnostic?.usage_status === "research" ? (
                        <Alert type="warning" showIcon style={{ margin: "10px 0" }} title="当前结果仅适合研究，不建议直接实盘使用。" />
                      ) : null}
                      {diagnostic?.usage_status === "blocked" ? (
                        <Alert type="error" showIcon style={{ margin: "10px 0" }} title="禁止选股" description={diagnostic.usage_advice} />
                      ) : null}
                      <Text type="secondary">最新交易日 {diagnostic?.latest_trade_date ?? "待获取"}；本地行情缓存至 {cache?.cache_end ?? "-"}</Text>
                    </div>
                    {recommendedAction ? (
                      <Button type="primary" size="large" onClick={goRecommendedAction}>{diagnostic?.recommended_label}</Button>
                    ) : (
                      <Button size="large" disabled>无需更新</Button>
                    )}
                  </div>
                  <Row gutter={[12, 12]} style={{ marginTop: 18 }}>
                    <Col xs={24} md={6}>{boolTag(Boolean(diagnostic?.price_complete), "行情完整", "行情需修复")}</Col>
                    <Col xs={24} md={6}>{boolTag(Boolean(diagnostic?.price_current), "已到最新交易日", "建议追到最新")}</Col>
                    <Col xs={24} md={6}>{boolTag(Boolean(diagnostic?.fundamental_ok), "基础面可用", "基础面需更新")}</Col>
                    <Col xs={24} md={6}>{boolTag(Boolean(diagnostic?.factor_ok), "因子可用", "因子不可用")}</Col>
                  </Row>
                </Card>

                <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                  <Col xs={24} md={8}>
                    <Card className="mq-card mq-status-card">
                      <Space orientation="vertical" size={6}>
                        <Tag color="green">可实盘使用</Tag>
                        <Text strong>数据已覆盖最新交易日</Text>
                        <Text type="secondary">行情完整，基础面和因子可用，可作为交易前研究输入。</Text>
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card className="mq-card mq-status-card">
                      <Space orientation="vertical" size={6}>
                        <Tag color="gold">可研究使用</Tag>
                        <Text strong>数据落后 1-2 个交易日</Text>
                        <Text type="secondary">因子仍可分析，但结果不建议直接用于实盘下单。</Text>
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card className="mq-card mq-status-card">
                      <Space orientation="vertical" size={6}>
                        <Tag color="red">禁止选股</Tag>
                        <Text strong>行情、基础面或因子不可用</Text>
                        <Text type="secondary">请先更新或修复缓存，再生成候选名单。</Text>
                      </Space>
                    </Card>
                  </Col>
                </Row>

                <Row gutter={[16, 16]}>
                  <Col xs={24} sm={12} lg={6}>
                    <Card className="mq-card mq-metric-card">
                      <Statistic title="行情数据" value={cache?.coverage_pct ?? 0} precision={1} suffix="%" />
                      <Progress percent={Number(cache?.coverage_pct ?? 0)} showInfo={false} size="small" />
                      <Text type="secondary">缺失 {cache?.missing_count ?? 0}，落后 {cache?.stale_count ?? 0}</Text>
                    </Card>
                  </Col>
                  <Col xs={24} sm={12} lg={6}>
                    <Card className="mq-card mq-metric-card">
                      <Statistic title="基础面数据" value={anomalies?.fundamental_missing_total ?? 0} suffix="缺失" />
                      <Text type="secondary">ROE {readiness?.fundamental_missing?.ROE ?? 0}，GROWTH {readiness?.fundamental_missing?.GROWTH ?? 0}</Text>
                      <div className="mq-card-note">{diagnostic?.fundamental_explanation ?? "基础面完整度正在评估。"}</div>
                    </Card>
                  </Col>
                  <Col xs={24} sm={12} lg={6}>
                    <Card className="mq-card mq-metric-card">
                      <Statistic title="因子数据" value={Object.values(factorStatus).filter(Boolean).length} suffix={`/${Object.keys(factorStatus).length}`} />
                      <Text type="secondary">不可用 {anomalies?.unavailable_factors?.join("、") || "无"}</Text>
                    </Card>
                  </Col>
                  <Col xs={24} sm={12} lg={6}>
                    <Card className="mq-card mq-metric-card">
                      <Statistic title="股票池" value={summary?.pool_count ?? 0} suffix="只" />
                      <Text type="secondary">价格列 {summary?.price_symbol_count ?? 0}，行数 {summary?.price_row_count ?? 0}</Text>
                    </Card>
                  </Col>
                </Row>

                <Card className="mq-card" title="异常明细" style={{ marginTop: 16 }}>
                  <Row gutter={[12, 12]}>
                    <Col xs={24} md={6}>
                      <Statistic title="缺失价格股票" value={anomalies?.missing_price_count ?? 0} suffix="只" />
                      <Button type="link" disabled={!anomalies?.missing_tickers?.length} onClick={() => setTickerModal({ title: "缺失价格股票", tickers: anomalies?.missing_tickers ?? [] })}>查看股票列表</Button>
                    </Col>
                    <Col xs={24} md={6}>
                      <Statistic title="日期落后股票" value={anomalies?.stale_price_count ?? 0} suffix="只" />
                      <Button type="link" disabled={!anomalies?.stale_tickers?.length} onClick={() => setTickerModal({ title: "日期落后股票", tickers: anomalies?.stale_tickers ?? [] })}>查看股票列表</Button>
                    </Col>
                    <Col xs={24} md={6}>
                      <Statistic title="基础面字段缺失" value={anomalies?.fundamental_missing_total ?? 0} />
                      <Text type="secondary">{Object.entries(anomalies?.fundamental_missing ?? {}).map(([key, value]) => `${key} ${value}`).join("，") || "无"}</Text>
                    </Col>
                    <Col xs={24} md={6}>
                      <Statistic title="因子不可用" value={anomalies?.unavailable_factors?.length ?? 0} />
                      <Text type="secondary">{anomalies?.issues?.join(" ") || "无"}</Text>
                    </Col>
                  </Row>
                </Card>

                <h2 className="mq-section-title">因子可用性</h2>
                <Space wrap>
                  {Object.entries(factorStatus).map(([name, ok]) => boolTag(ok, `${name}可用`, `${name}不足`))}
                </Space>

                <h2 className="mq-section-title">更新历史</h2>
                <Table
                  className="mq-card"
                  rowKey="id"
                  columns={historyColumns}
                  dataSource={taskHistory}
                  pagination={false}
                  size="small"
                />
              </>
            ) : activeSection === "update" ? (
              <>
                <Alert
                  type={diagnostic?.status === "normal" ? "success" : diagnostic?.status === "suggest_update" ? "warning" : "error"}
                  showIcon
                  style={{ marginBottom: 16 }}
                  title={diagnostic?.conclusion ?? "正在读取诊断结果"}
                  description={recommendedAction ? `当前推荐执行：${diagnostic?.recommended_label}` : "当前无需更新，可以直接进入筛选择股。"}
                  action={recommendedAction ? <Button size="small" type="primary" onClick={() => confirmStartUpdate(recommendedAction)}>执行推荐操作</Button> : undefined}
                />

                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={10}>
                    <Card className="mq-card" title="连接与下载参数">
                      <Space orientation="vertical" size={14} style={{ width: "100%" }}>
                        <div>
                          <span className="mq-label">Tushare Token</span>
                          <Input.Password
                            value={updateToken}
                            onChange={(event) => setUpdateToken(event.target.value)}
                            placeholder="可留空使用已缓存 token"
                          />
                        </div>
                        <div>
                          <span className="mq-label">HTTP URL</span>
                          <Input value={updateHttpUrl} onChange={(event) => setUpdateHttpUrl(event.target.value)} />
                        </div>
                        <div className="mq-filter-grid">
                          <div>
                            <span className="mq-label">价格缓存起始日期</span>
                            <Input value={updateStartDate} onChange={(event) => setUpdateStartDate(event.target.value)} />
                          </div>
                          <div>
                            <span className="mq-label">下载并发数</span>
                            <InputNumber min={1} max={16} value={downloadWorkers} onChange={(value) => setDownloadWorkers(Number(value ?? 2))} style={{ width: "100%" }} />
                          </div>
                        </div>
                        <Space>
                          <Switch checked={includeStaleTickers} onChange={setIncludeStaleTickers} />
                          <Text>修复行情时同时补齐日期落后标的</Text>
                        </Space>
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} lg={14}>
                    <Card className="mq-card" title="按问题推荐操作">
                      <Row gutter={[12, 12]}>
                        {(["sync_latest", "repair_price", "refresh_fundamentals"] as UpdateAction[]).map((action) => {
                          const meta = actionMeta[action];
                          const recommended = recommendedAction === action;
                          return (
                            <Col xs={24} md={8} key={action}>
                              <Card className={`mq-action-card ${recommended ? "mq-action-card-recommended" : ""}`} size="small">
                                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                                  {recommended ? <div className="mq-recommended-ribbon">当前推荐</div> : null}
                                  <Space wrap>
                                    <Text strong>{updateActionLabels[action]}</Text>
                                    {recommended ? <Tag color="blue">推荐当前执行</Tag> : <Tag>按需</Tag>}
                                    <Tag color={meta.risk === "低" ? "green" : meta.risk === "中" ? "gold" : "red"}>{meta.risk}风险</Tag>
                                  </Space>
                                  <Text type="secondary">需要时机：{meta.when}</Text>
                                  <Text type="secondary">更新内容：{meta.updates}</Text>
                                  <Text type="secondary">缓存影响：{meta.overwrite}</Text>
                                  <Text type="secondary">预计耗时：{meta.duration}</Text>
                                  {recommended ? <Alert type="info" showIcon title="建议优先执行此操作" description={diagnostic?.full_conclusion} /> : null}
                                  <Button type={recommended ? "primary" : "default"} block loading={updateTaskLoading} onClick={() => confirmStartUpdate(action)}>{updateActionLabels[action]}</Button>
                                </Space>
                              </Card>
                            </Col>
                          );
                        })}
                      </Row>

                      <Collapse
                        ghost
                        style={{ marginTop: 12 }}
                        items={[
                          {
                            key: "advanced",
                            label: "高级操作",
                            children: (
                              <Card className="mq-action-card" size="small">
                                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                                  <Space wrap>
                                    <Text strong>{updateActionLabels.rebuild_price}</Text>
                                    <Tag color="red">高风险</Tag>
                                    <Tag>严重异常时使用</Tag>
                                  </Space>
                                  <Text type="secondary">需要时机：{actionMeta.rebuild_price.when}</Text>
                                  <Text type="secondary">更新内容：{actionMeta.rebuild_price.updates}</Text>
                                  <Text type="secondary">缓存影响：{actionMeta.rebuild_price.overwrite}</Text>
                                  <Text type="secondary">预计耗时：{actionMeta.rebuild_price.duration}</Text>
                                  <Button danger loading={updateTaskLoading} onClick={() => confirmStartUpdate("rebuild_price")}>{updateActionLabels.rebuild_price}</Button>
                                </Space>
                              </Card>
                            ),
                          },
                        ]}
                      />
                    </Card>
                  </Col>
                </Row>

                {updateTask ? (
                  <Card className="mq-card" title="任务状态" style={{ marginTop: 16 }}>
                    <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                      <Space wrap>
                        <Tag color={updateTask.status === "succeeded" ? "green" : updateTask.status === "failed" ? "red" : "blue"}>{updateTask.status}</Tag>
                        <Text strong>{updateActionLabels[updateTask.action]}</Text>
                        <Text type="secondary">{updateTask.message}</Text>
                      </Space>
                      <div>
                        <span className="mq-label">股票级进度</span>
                        <Progress percent={Math.round((updateTask.progress ?? 0) * 100)} />
                      </div>
                      <div>
                        <span className="mq-label">分段下载进度</span>
                        <Progress percent={Math.round((updateTask.chunk_progress ?? 0) * 100)} />
                      </div>
                      {updateTask.error ? <Alert type="error" title={updateTask.error} showIcon /> : null}
                      {updateTask.result?.stats ? (
                        <Alert
                          type={updateTask.status === "failed" ? "error" : "success"}
                          showIcon
                          title={updateTask.status === "succeeded" ? "更新完成" : "更新结果"}
                          description={`更新股票 ${updateTask.result.stats.tickers_updated ?? 0} 只，新增行情 ${updateTask.result.stats.rows_appended ?? 0} 条，修复请求 ${updateTask.result.stats.repair_requested ?? 0} 个；当前数据${summary?.diagnostic?.can_screen ? "可用于选股" : "仍建议检查异常明细"}${updateTask.result.cache_range ? `；缓存范围 ${updateTask.result.cache_range.join(" ~ ")}` : ""}`}
                        />
                      ) : null}
                    </Space>
                  </Card>
                ) : null}
              </>
            ) : activeSection === "screen" ? (
              <>
                <Alert
                  type={diagnostic?.can_screen ? (diagnostic.price_current ? "success" : "warning") : "error"}
                  showIcon
                  style={{ marginBottom: 16 }}
                  title={screenStatusTitle}
                  action={!diagnostic?.can_screen || !diagnostic?.price_current ? <Button size="small" type="primary" onClick={() => setActiveSection("update")}>去数据更新页</Button> : undefined}
                />

                {readiness?.issues?.length ? (
                  <Alert
                    type={readiness.factor_ok ? "warning" : "error"}
                    showIcon
                    style={{ marginBottom: 16 }}
                    title={readiness.issues.join(" ")}
                    description={readiness.repair_actions?.length ? `建议：${Array.from(new Set(readiness.repair_actions)).join(" ")}` : undefined}
                  />
                ) : null}

                <h2 className="mq-section-title">筛选参数</h2>
                <Card className="mq-card">
              <div className="mq-industry-filter">
                <span className="mq-label">按板块/行业筛选</span>
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  maxTagCount="responsive"
                  placeholder="不选择则在全市场股票池中筛选"
                  value={selectedIndustries}
                  options={industrySelectOptions}
                  onChange={setSelectedIndustries}
                  optionFilterProp="label"
                  style={{ width: "100%" }}
                />
                <div className="mq-card-note">
                  {selectedIndustries.length
                    ? `将先限定在 ${selectedIndustries.length} 个板块/行业内，再执行风险过滤和多因子打分。`
                    : `当前共有 ${industryOptions.length} 个行业可选；留空表示全市场筛选。`}
                </div>
              </div>
              <div className="mq-toolbar">
                <div className="mq-control-cell mq-control-wide">
                  <span className="mq-label">筛选模板</span>
                  <Select value={selectedTemplate} options={templateOptions.map((value) => ({ value, label: value }))} onChange={applyTemplate} style={{ width: "100%" }} />
                  <div className="mq-card-note">{templateDescription}</div>
                </div>
                <div className="mq-control-cell">
                  <span className="mq-label">最终数量</span>
                  <InputNumber min={1} max={500} value={topN} onChange={(value) => setTopN(Number(value ?? 30))} style={{ width: "100%" }} />
                </div>
                {factorNames.map((name) => (
                  <div className="mq-control-cell mq-slider-cell" key={name}>
                    <span className="mq-label">{name} {Math.round((weights[name] ?? 0) * 100)}%</span>
                    <Slider
                      min={0}
                      max={100}
                      step={5}
                      value={Math.round((weights[name] ?? 0) * 100)}
                      onChange={(value) => setWeights((current) => ({ ...current, [name]: value / 100 }))}
                    />
                  </div>
                ))}
              </div>

              <div className="mq-filter-grid">
                {[
                  ["min_turnover", "最低换手率", 0, 20, 0.1],
                  ["list_age_floor", "上市天数下限", 0, 2000, 30],
                  ["roe_floor", "ROE 下限", -100, 100, 1],
                  ["growth_floor", "营收同比下限", -100, 200, 1],
                  ["pe_cap", "PE 上限", 0, 300, 5],
                  ["pb_cap", "PB 上限", 0, 50, 0.5],
                ].map(([key, label, min, max, step]) => (
                  <div className="mq-control-cell" key={String(key)}>
                    <span className="mq-label">{String(label)}</span>
                    <InputNumber
                      min={Number(min)}
                      max={Number(max)}
                      step={Number(step)}
                      value={Number(filters[String(key)] ?? 0)}
                      onChange={(value) => setFilters((current) => ({ ...current, [String(key)]: Number(value ?? 0) }))}
                      style={{ width: "100%" }}
                    />
                  </div>
                ))}
                <div className="mq-control-cell mq-switch-cell">
                  <span className="mq-label">行业内归一化</span>
                  <Switch checked={industryNeutral} onChange={setIndustryNeutral} />
                </div>
                <div className="mq-control-cell mq-switch-cell">
                  <span className="mq-label">允许不完整因子</span>
                  <Switch checked={allowIncomplete} onChange={setAllowIncomplete} />
                </div>
              </div>

              <Space className="mq-action-row" wrap>
                <Button type="primary" icon={<ExperimentOutlined />} loading={loading} disabled={diagnostic ? !diagnostic.can_screen : true} onClick={runScreen}>执行筛选</Button>
                <Button onClick={() => applyTemplate(selectedTemplate)}>恢复模板默认权重</Button>
                <Button disabled={!rows.length} onClick={() => handleRowsForBacktest("screen")}>用筛选结果回测</Button>
                <Button disabled={!watchlist.length} onClick={() => handleRowsForBacktest("watchlist")}>用观察池回测</Button>
                <Text type="secondary">观察池 {watchlist.length} 只</Text>
              </Space>
                </Card>

                <h2 className="mq-section-title">筛选结果</h2>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  title="筛选结果用于生成观察名单，不构成买入建议。请结合趋势、估值、仓位和风险控制进一步确认。"
                  description={filterSummary}
                />
                <Table
                  className="mq-card"
                  rowKey="ticker"
                  dataSource={rows}
                  columns={columns}
                  loading={loading}
                  scroll={{ x: 1100 }}
                  onRow={(row) => ({ onDoubleClick: () => setSelectedStock(row) })}
                  pagination={{ pageSize: 20, showSizeChanger: true }}
                  size="middle"
                />

                <h2 className="mq-section-title">观察池</h2>
                <Alert
                  type="success"
                  showIcon
                  style={{ marginBottom: 12 }}
                  title="观察池已保存到本地缓存，刷新页面后仍会保留。"
                  description="可将观察池作为策略回测输入，也可以从这里移出不再关注的股票。"
                />
                <Table
                  className="mq-card"
                  rowKey="ticker"
                  dataSource={watchlist}
                  columns={watchlistColumns}
                  loading={watchlistLoading}
                  scroll={{ x: 1500 }}
                  pagination={{ pageSize: 10 }}
                  size="small"
                />
              </>
            ) : (
              <>
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  title="当前回测是固定股票池回测，不代表历史上当时能选出这些股票。"
                  description="若要验证因子有效性，请使用逐期滚动选股回测。固定股票池回测容易产生幸存者偏差和未来信息偏差，只适合观察这组股票在历史区间内的价格表现。"
                />
                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={9}>
                    <Card className="mq-card" title="回测输入">
                      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                        <div>
                          <span className="mq-label">回测模式</span>
                          <Select
                            value={backtestMode}
                            onChange={setBacktestMode}
                            style={{ width: "100%" }}
                            options={[
                              { value: "fixed", label: "固定股票池回测" },
                              { value: "rolling", label: "滚动选股回测（预留）" },
                            ]}
                          />
                        </div>
                        {backtestMode === "rolling" ? (
                          <Alert
                            type="info"
                            showIcon
                            title="滚动选股回测模式已预留"
                            description="目标流程：每周或每月重新计算因子，只使用当时可获得的数据，按当前模板和权重选出前 N 只，下一期调仓，并输出累计收益、年化收益、最大回撤、夏普比率、胜率、换手率和超额收益。当前缓存缺少逐期历史基础面/估值快照，因此暂不生成可能误导的结果。"
                          />
                        ) : null}
                        <div>
                          <span className="mq-label">股票来源</span>
                          <Select
                            value={backtestSource}
                            onChange={setBacktestSource}
                            style={{ width: "100%" }}
                            options={[
                              { value: "screen", label: `筛选结果 ${rows.length} 只` },
                              { value: "watchlist", label: `观察池 ${watchlist.length} 只` },
                            ]}
                          />
                        </div>
                        <div className="mq-filter-grid">
                          <div><span className="mq-label">开始日期</span><Input value={backtestStartDate} onChange={(event) => setBacktestStartDate(event.target.value)} /></div>
                          <div><span className="mq-label">结束日期</span><Input value={backtestEndDate} onChange={(event) => setBacktestEndDate(event.target.value)} /></div>
                          <div><span className="mq-label">持仓数量</span><InputNumber min={1} max={500} value={holdingCount} onChange={(value) => setHoldingCount(Number(value ?? 30))} style={{ width: "100%" }} /></div>
                          <div><span className="mq-label">初始资金</span><InputNumber min={10000} step={10000} value={backtestInitCash} onChange={(value) => setBacktestInitCash(Number(value ?? 100000))} style={{ width: "100%" }} /></div>
                          <div><span className="mq-label">手续费</span><InputNumber min={0} max={0.1} step={0.0005} value={backtestFees} onChange={(value) => setBacktestFees(Number(value ?? 0.001))} style={{ width: "100%" }} /></div>
                          <div><span className="mq-label">滑点</span><InputNumber min={0} max={0.1} step={0.0005} value={backtestSlippage} onChange={(value) => setBacktestSlippage(Number(value ?? 0.001))} style={{ width: "100%" }} /></div>
                          <div><span className="mq-label">基准</span><Select value={benchmarkName} onChange={setBenchmarkName} style={{ width: "100%" }} options={["无", "沪深300", "中证500", "中证1000", "创业板指"].map((value) => ({ value, label: value }))} /></div>
                        </div>
                        <Space wrap>
                          <Switch checked={allowIncompleteBacktest} onChange={setAllowIncompleteBacktest} />
                          <Text>允许不完整数据继续回测</Text>
                        </Space>
                        <Space wrap>
                          <Switch checked={allowFallbackUniverse} onChange={setAllowFallbackUniverse} />
                          <Text>无交集时回退到缓存内标的</Text>
                        </Space>
                        <Button type="primary" icon={<StockOutlined />} loading={backtestLoading} disabled={!backtestRows.length || backtestMode === "rolling"} onClick={runBacktest}>运行回测</Button>
                        <Text type="secondary">当前来源可用 {backtestRows.length} 只，实际使用前 {holdingCount} 只。</Text>
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} lg={15}>
                    <Card className="mq-card" title="策略参数">
                      <Space orientation="vertical" size={12} style={{ width: "100%", marginBottom: 14 }}>
                        <div>
                          <span className="mq-label">回测策略</span>
                          <Select
                            mode="multiple"
                            allowClear
                            maxTagCount="responsive"
                            value={selectedStrategies}
                            options={strategyOptions}
                            onChange={setSelectedStrategies}
                            placeholder="选择一个或多个策略"
                            style={{ width: "100%" }}
                          />
                        </div>
                        <Space wrap>
                          {selectedStrategies.map((name) => (
                            <Tag color="blue" key={name}>{availableStrategies[name]?.category ?? "策略"} · {name}</Tag>
                          ))}
                        </Space>
                      </Space>
                      <div className="mq-filter-grid">
                        <div><span className="mq-label">快均线</span><InputNumber min={2} max={120} value={fastWindow} onChange={(value) => setFastWindow(Number(value ?? 10))} style={{ width: "100%" }} /></div>
                        <div><span className="mq-label">慢均线</span><InputNumber min={5} max={240} value={slowWindow} onChange={(value) => setSlowWindow(Number(value ?? 50))} style={{ width: "100%" }} /></div>
                        <div><span className="mq-label">止损比例</span><InputNumber min={0.01} max={0.5} step={0.01} value={trailStop} onChange={(value) => setTrailStop(Number(value ?? 0.08))} style={{ width: "100%" }} /></div>
                        <div><span className="mq-label">动量窗口</span><InputNumber min={5} max={120} value={momWindow} onChange={(value) => setMomWindow(Number(value ?? 20))} style={{ width: "100%" }} /></div>
                        <div><span className="mq-label">动量持仓比例</span><InputNumber min={0.05} max={0.8} step={0.05} value={topPct} onChange={(value) => setTopPct(Number(value ?? 0.2))} style={{ width: "100%" }} /></div>
                        <div><span className="mq-label">RSI窗口</span><InputNumber min={5} max={60} value={rsiWindow} onChange={(value) => setRsiWindow(Number(value ?? 14))} style={{ width: "100%" }} /></div>
                        <div><span className="mq-label">RSI买入阈值</span><InputNumber min={5} max={50} value={rsiBuy} onChange={(value) => setRsiBuy(Math.min(50, Number(value ?? 30)))} style={{ width: "100%" }} /><div className="mq-card-note">买入阈值通常小于 50。</div></div>
                        <div><span className="mq-label">RSI卖出阈值</span><InputNumber min={50} max={95} value={rsiSell} onChange={(value) => setRsiSell(Math.max(50, Number(value ?? 55)))} style={{ width: "100%" }} /><div className="mq-card-note">卖出阈值通常大于 50。</div></div>
                      </div>
                    </Card>
                  </Col>
                </Row>

                {backtestResult ? (
                  <>
                    <h2 className="mq-section-title">回测结果</h2>
                    <Row gutter={[16, 16]}>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="策略收益" value={metricPercent(backtestResult.metrics["累计收益"])} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="年化收益" value={metricPercent(backtestResult.metrics["年化收益"])} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="最大回撤" value={metricPercent(backtestResult.metrics["最大回撤"])} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="夏普比率" value={numberText(backtestResult.metrics["夏普比率"], 4)} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="胜率" value={metricPercent(backtestResult.metrics["胜率"])} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="基准收益" value={metricPercent(backtestResult.metrics["基准收益"])} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="超额收益" value={metricPercent(backtestResult.metrics["超额收益"])} /></Card></Col>
                      <Col xs={12} md={3}><Card className="mq-card"><Statistic title="相对最大回撤" value={metricPercent(backtestResult.metrics["相对最大回撤"])} /></Card></Col>
                    </Row>
                    <Alert
                      type={backtestResult.benchmark_available || benchmarkName === "无" ? "success" : "warning"}
                      showIcon
                      style={{ marginTop: 16 }}
                      title={`缓存命中 ${backtestResult.stats.tickers_in_cache}/${backtestResult.stats.tickers_requested} 只，缓存范围 ${backtestResult.cache_range.join(" ~ ")}`}
                      description={backtestResult.benchmark_available || benchmarkName === "无" ? "回测完成。" : "基准不可用，本次回测不能判断超额收益。"}
                    />
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginTop: 16 }}
                      title="交易辅助建议基于规则信号生成，只用于复核仓位、止损和等待条件。"
                      description="买卖点来自历史收盘价和策略条件，不包含实时盘口、涨跌停、公告、财报和成交量冲击，请在下单前另行确认。"
                    />
                    <Card className="mq-card" title="策略/基准净值曲线对比" style={{ marginTop: 16 }}>
                      <Space wrap style={{ marginBottom: 8 }}>
                        <Tag color="blue">策略</Tag>
                        {benchmarkPolyline ? <Tag color="orange">基准</Tag> : <Tag>基准不可用</Tag>}
                      </Space>
                      {equityPolyline ? (
                        <svg className="mq-equity-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
                          <polyline points={equityPolyline} fill="none" stroke="#1677ff" strokeWidth="2" vectorEffect="non-scaling-stroke" />
                          {benchmarkPolyline ? <polyline points={benchmarkPolyline} fill="none" stroke="#fa8c16" strokeWidth="2" vectorEffect="non-scaling-stroke" /> : null}
                        </svg>
                      ) : <Text type="secondary">暂无权益曲线。</Text>}
                    </Card>
                    <h2 className="mq-section-title">当前交易辅助建议</h2>
                    <Table
                      className="mq-card"
                      rowKey={(row) => `${row.strategy}-${row.ticker}`}
                      columns={adviceColumns}
                      dataSource={(backtestResult.advice ?? []).slice(0, 80)}
                      pagination={{ pageSize: 12 }}
                      scroll={{ x: 1300 }}
                      size="small"
                    />
                    <h2 className="mq-section-title">买卖点明细</h2>
                    <Table
                      className="mq-card"
                      rowKey={(row) => `${row.strategy}-${row.ticker}-${row.date}-${row.action}`}
                      columns={signalColumns}
                      dataSource={backtestResult.signals ?? []}
                      pagination={{ pageSize: 15 }}
                      scroll={{ x: 920 }}
                      size="small"
                    />
                    <h2 className="mq-section-title">策略对比</h2>
                    <Table className="mq-card" rowKey="策略" columns={strategyColumns} dataSource={backtestResult.strategies} pagination={false} size="middle" />
                    <h2 className="mq-section-title">本次回测股票池</h2>
                    <Table className="mq-card" rowKey="ticker" columns={backtestPoolColumns} dataSource={backtestResult.pool} pagination={{ pageSize: 10 }} size="small" />
                  </>
                ) : null}
              </>
            )}
          </Content>
        </Layout>
      </Layout>
      <Drawer
        title={selectedStock ? `${selectedStock.ticker} ${selectedStock.名称 ?? ""}` : "股票详情"}
        open={Boolean(selectedStock)}
        onClose={() => setSelectedStock(null)}
        size="large"
      >
        {selectedStock ? (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Card className="mq-card" size="small">
              <Row gutter={[12, 12]}>
                <Col span={12}><Statistic title="综合评分" value={selectedStock.综合评分 ?? 0} precision={1} /></Col>
                <Col span={12}><Statistic title="行业" value={selectedStock.行业 ?? "-"} /></Col>
              </Row>
            </Card>
            <Card className="mq-card" size="small" title="投资决策解释">
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                <Text>{selectedStock.决策解释 ?? "综合评分靠前，请结合估值、波动、回撤和流动性进一步复核。"}</Text>
                <Space wrap>{getStyleTags(selectedStock).map((item) => <Tag color="blue" key={item}>{item}</Tag>)}</Space>
              </Space>
            </Card>
            <Card className="mq-card" size="small" title="因子得分">
              <Row gutter={[12, 12]}>
                {[
                  ["动量", selectedStock.动量分],
                  ["质量", selectedStock.质量分],
                  ["估值", selectedStock.估值分],
                  ["成长", selectedStock.成长分],
                  ["风险控制", selectedStock.风险控制分],
                  ["资金情绪", selectedStock.资金情绪分],
                ].map(([label, value]) => (
                  <Col span={8} key={String(label)}><Statistic title={String(label)} value={typeof value === "number" ? value : 0} precision={1} /></Col>
                ))}
              </Row>
            </Card>
            <Card className="mq-card" size="small" title="综合评分旁的风险分层">
              <Row gutter={[12, 12]}>
                <Col span={8}><Statistic title="进攻分" value={numberText(selectedStock.进攻分)} /></Col>
                <Col span={8}><Statistic title="防守分" value={numberText(selectedStock.防守分)} /></Col>
                <Col span={8}><Statistic title="估值压力" value={`${riskText(selectedStock.估值压力)} ${numberText(selectedStock.估值压力)}`} /></Col>
                <Col span={8}><Statistic title="波动风险" value={`${riskText(selectedStock.波动风险)} ${numberText(selectedStock.波动风险)}`} /></Col>
                <Col span={8}><Statistic title="回撤风险" value={`${riskText(selectedStock.回撤风险)} ${numberText(selectedStock.回撤风险)}`} /></Col>
                <Col span={8}><Statistic title="流动性风险" value={`${riskText(selectedStock.流动性风险)} ${numberText(selectedStock.流动性风险)}`} /></Col>
              </Row>
            </Card>
            <Card className="mq-card" size="small" title="核心财务与估值指标">
              <Row gutter={[12, 12]}>
                <Col span={8}><Statistic title="ROE" value={numberText(selectedStock.ROE)} /></Col>
                <Col span={8}><Statistic title="GROWTH" value={numberText(selectedStock.GROWTH)} /></Col>
                <Col span={8}><Statistic title="PE" value={numberText(selectedStock.PE)} /></Col>
                <Col span={8}><Statistic title="PB" value={numberText(selectedStock.PB)} /></Col>
              </Row>
            </Card>
            <Card className="mq-card" size="small" title="动量、波动和回撤指标">
              <Row gutter={[12, 12]}>
                <Col span={8}><Statistic title="20日收益" value={percentText(selectedStock.ret_20d)} /></Col>
                <Col span={8}><Statistic title="60日收益" value={percentText(selectedStock.ret_60d)} /></Col>
                <Col span={8}><Statistic title="120日收益" value={percentText(selectedStock.ret_120d)} /></Col>
                <Col span={8}><Statistic title="60日波动率" value={percentText(selectedStock.vol_60d)} /></Col>
                <Col span={8}><Statistic title="120日最大回撤" value={percentText(selectedStock.max_drawdown_120d)} /></Col>
              </Row>
            </Card>
            <Card className="mq-card" size="small" title="行业内排名或分位数">
              <Row gutter={[12, 12]}>
                <Col span={8}><Statistic title="动量分位" value={numberText(selectedStock.行业内动量分位)} suffix="/100" /></Col>
                <Col span={8}><Statistic title="质量分位" value={numberText(selectedStock.行业内质量分位)} suffix="/100" /></Col>
                <Col span={8}><Statistic title="估值分位" value={numberText(selectedStock.行业内估值分位)} suffix="/100" /></Col>
              </Row>
            </Card>
            <Card className="mq-card" size="small" title="入选原因">
              <Space wrap>{splitReasonAndRisk(selectedStock.入选原因).reasons.map((item) => <Tag color="blue" key={item}>{item}</Tag>)}</Space>
            </Card>
            <Card className="mq-card" size="small" title="风险提示">
              <Space wrap>{splitReasonAndRisk(selectedStock.入选原因).risks.map((item) => <Tag color={item.includes("暂未") ? "green" : "orange"} key={item}>{item}</Tag>)}</Space>
            </Card>
            <Button type="primary" icon={<PlusOutlined />} loading={watchlistLoading} onClick={() => void addToWatchlist(selectedStock)} disabled={watchlist.some((item) => item.ticker === selectedStock.ticker)}>加入观察池</Button>
          </Space>
        ) : null}
      </Drawer>
      <Modal
        title={tickerModal?.title}
        open={Boolean(tickerModal)}
        footer={null}
        onCancel={() => setTickerModal(null)}
        width={520}
      >
        <Table
          rowKey="ticker"
          dataSource={(tickerModal?.tickers ?? []).map((ticker) => ({ ticker }))}
          columns={[{ title: "股票代码", dataIndex: "ticker" }]}
          size="small"
          pagination={{ pageSize: 12 }}
        />
      </Modal>
    </ConfigProvider>
  );
}
