"use client";

import {
  Alert,
  Button,
  Card,
  Select,
  Switch,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { MessageOutlined, ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import type { AgentDraft } from "./AgentAssistantDrawer";
import StockDetailDrawer from "./StockDetailDrawer";
import { TickerCell, registerTickerNames } from "./TickerCell";

const { Text } = Typography;

type RecommendItem = {
  ticker: string;
  name?: string | null;
  industry?: string | null;
  pool_ids: number[];
  pool_names: string[];
  state: string;
  state_label: string;
  state_color: string;
  reasons: string[];
  risks: string[];
  score: number;
  close?: number | null;
  ret_20d?: number | null;
  max_drawdown_120d?: number | null;
  ma_alignment?: number | null;
  trend_slope_60d?: number | null;
};

type RecommendGroup = {
  key: string;
  label: string;
  color: string;
  count: number;
  items: RecommendItem[];
};

type RecommendResponse = {
  end_date: string | null;
  total_evaluated: number;
  groups: RecommendGroup[];
};

type Props = {
  apiBase: string;
  onOpenAgent?: (draft: AgentDraft) => void;
};

const fmtPct = (v: number | null | undefined) =>
  v == null ? "-" : `${(v * 100).toFixed(1)}%`;

export default function RecommendPanel({ apiBase, onOpenAgent }: Props) {
  const [data, setData] = useState<RecommendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailTicker, setDetailTicker] = useState<string | null>(null);
  const [marketWide, setMarketWide] = useState(false);
  const [allIndustries, setAllIndustries] = useState<string[]>([]);
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [planLoadingTicker, setPlanLoadingTicker] = useState<string | null>(null);

  // 拉取可用行业列表
  useEffect(() => {
    void fetch(`${apiBase}/api/recommend/industries`)
      .then((r) => r.json())
      .then((j: { industries?: string[] }) => setAllIndustries(j.industries ?? []))
      .catch(() => {/* 行业列表失败不阻断主流程 */});
  }, [apiBase]);

  const fetchData = useCallback(async (mw = marketWide, inds = selectedIndustries) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", mw ? "10" : "20");
      if (mw) params.set("market_wide", "true");
      inds.forEach((ind) => params.append("industries", ind));
      const r = await fetch(`${apiBase}/api/recommend?${params.toString()}`);
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `推荐加载失败 (${r.status})`);
      }
      const json = (await r.json()) as RecommendResponse;
      setData(json);
      registerTickerNames(json.groups.flatMap((g) => g.items));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [apiBase, marketWide, selectedIndustries]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchData();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [fetchData]);

  const handleGeneratePlan = async (ticker: string) => {
    setPlanLoadingTicker(ticker);
    try {
      const r = await fetch(`${apiBase}/api/plans/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `生成失败 (${r.status})`);
      const save = await fetch(`${apiBase}/api/plans?force=true`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(j.plan),
      });
      const sj = await save.json();
      if (!save.ok) throw new Error(sj?.detail ?? `保存失败 (${save.status})`);
      message.success(`已为 ${ticker} 生成草稿计划 #${sj.plan.id}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setPlanLoadingTicker(null);
    }
  };

  return (
    <>
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} /> : null}

      <div className="mq-recommend-header">
        <Text type="secondary" style={{ fontSize: 12 }}>
          {data
            ? `基准日 ${data.end_date ?? "-"} · 共评估 ${data.total_evaluated} 只${marketWide ? "（全市场·结果缓存5min）" : ""}`
            : "加载中…"}
        </Text>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Select
            mode="multiple"
            allowClear
            placeholder="筛选行业"
            size="small"
            style={{ minWidth: 160, maxWidth: 320 }}
            options={allIndustries.map((ind) => ({ label: ind, value: ind }))}
            value={selectedIndustries}
            onChange={(vals) => setSelectedIndustries(vals)}
            maxTagCount="responsive"
          />
          <Tooltip title={marketWide ? "当前：全市场扫描（5499只）" : "当前：仅股票池+观察池"}>
            <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
              <ThunderboltOutlined style={{ color: marketWide ? "#f5a623" : "#bbb" }} />
              <Switch
                size="small"
                checked={marketWide}
                onChange={(v) => {
                  setMarketWide(v);
                  void fetchData(v, selectedIndustries);
                }}
              />
              <span style={{ color: marketWide ? "#f5a623" : "#999" }}>全市场</span>
            </span>
          </Tooltip>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void fetchData()} loading={loading}>刷新</Button>
        </div>
      </div>

      {(data?.groups ?? []).map((g) => (
        <section key={g.key} className="mq-recommend-group">
          <div className="mq-recommend-group-header">
            <Tag color={g.color}>{g.label}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>{g.count} 只</Text>
          </div>
          {g.items.length === 0 ? (
            <div className="mq-empty-group">暂无标的</div>
          ) : (
            <div className="mq-stock-grid">
              {g.items.map((it) => (
                <Card key={it.ticker} size="small" className="mq-card mq-stock-card">
                  <div className="mq-stock-head">
                    <button type="button" className="mq-stock-ticker" onClick={() => setDetailTicker(it.ticker)}>
                      <TickerCell ticker={it.ticker} name={it.name} layout="inline" />
                    </button>
                    <Tag color={it.state_color}>{it.state_label}</Tag>
                  </div>
                  <div className="mq-stock-name">
                    {it.industry ?? "-"}
                  </div>
                  <Tooltip title={it.pool_names.join("、")}>
                    <div className="mq-stock-pool">{it.pool_names[0] ?? "-"}</div>
                  </Tooltip>
                  <div className="mq-stock-metrics">
                    <div><span>收盘</span><b>{it.close?.toFixed(2) ?? "-"}</b></div>
                    <div><span>20D</span><b>{fmtPct(it.ret_20d)}</b></div>
                    <div><span>120D回撤</span><b>{fmtPct(it.max_drawdown_120d)}</b></div>
                    <div><span>综合分</span><b>{it.score.toFixed(2)}</b></div>
                  </div>
                  {it.reasons.length > 0 ? (
                    <div className="mq-stock-reason">{it.reasons.slice(0, 2).join("；")}</div>
                  ) : null}
                  <Button
                    size="small"
                    icon={<MessageOutlined />}
                    block
                    style={{ marginBottom: 8 }}
                    onClick={() => onOpenAgent?.({
                      scene: "stock_diagnosis",
                        userInput: `请基于推荐状态解读 ${it.name ?? it.ticker}（${it.ticker}），并给出三条跟踪动作。`,
                      payload: {
                        ticker: it.ticker,
                          name: it.name,
                        recommend_item: it,
                        recommend_group: { key: g.key, label: g.label, color: g.color },
                      },
                    })}
                  >
                    Agent解读
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    block
                    loading={planLoadingTicker === it.ticker}
                    onClick={() => handleGeneratePlan(it.ticker)}
                  >
                    生成计划
                  </Button>
                </Card>
              ))}
            </div>
          )}
        </section>
      ))}

      <StockDetailDrawer
        apiBase={apiBase}
        ticker={detailTicker}
        open={detailTicker != null}
        onClose={() => setDetailTicker(null)}
        onOpenAgent={onOpenAgent}
      />
    </>
  );
}
