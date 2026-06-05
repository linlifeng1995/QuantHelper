"use client";

import { useEffect, useState } from "react";
import { Alert, Card, Col, Descriptions, Drawer, Empty, Row, Skeleton, Space, Tag, Typography } from "antd";
import KLineChart from "./KLineChart";
import { TickerCell } from "./TickerCell";
import StockNewsCard from "./StockNewsCard";
import type { AgentDraft } from "./AgentAssistantDrawer";

const { Text, Title } = Typography;

type TimingResult = {
  state: string;
  label: string;
  color: string;
  description?: string;
  reasons: string[];
  risks: string[];
};

type PoolInfo = {
  pool_id: number;
  pool_name: string;
  pool_type: string;
  is_default: boolean;
  name?: string | null;
  industry?: string | null;
  added_score?: number | null;
  current_score?: number | null;
  status?: string;
  tags?: string[];
};

type PlanInfo = {
  id: number;
  ticker: string;
  action?: string;
  status?: string;
  entry_zone_low?: number | null;
  entry_zone_high?: number | null;
  stop_loss?: number | null;
  position_pct?: number | null;
  position_shares?: number | null;
  created_at?: string;
  trading_state?: string;
  confidence?: string | null;
};

type StockSummary = {
  ticker: string;
  ts_code: string;
  name?: string | null;
  industry?: string | null;
  end_date: string;
  price_factors: Record<string, number | null>;
  timing: TimingResult;
  pools: PoolInfo[];
  plans: PlanInfo[];
  plan_count: number;
  pool_count: number;
};

type Props = {
  apiBase: string;
  ticker: string | null;
  open: boolean;
  onClose: () => void;
  onOpenAgent?: (draft: AgentDraft) => void;
};

const fmtPct = (v: number | null | undefined, digits = 1) =>
  v == null ? "-" : `${(v * 100).toFixed(digits)}%`;
const fmtNum = (v: number | null | undefined, digits = 2) =>
  v == null || !Number.isFinite(v) ? "-" : v.toFixed(digits);

export default function StockDetailDrawer({ apiBase, ticker, open, onClose, onOpenAgent }: Props) {
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !ticker) {
      setSummary(null);
      setError(null);
      return;
    }
    let aborted = false;
    setLoading(true);
    setError(null);
    fetch(`${apiBase}/api/stock/${encodeURIComponent(ticker)}/summary`)
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (!r.ok) throw new Error(j?.detail ?? `摘要加载失败 (${r.status})`);
        return j as StockSummary;
      })
      .then((j) => {
        if (!aborted) setSummary(j);
      })
      .catch((err: unknown) => {
        if (!aborted) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!aborted) setLoading(false);
      });
    return () => {
      aborted = true;
    };
  }, [apiBase, ticker, open]);

  return (
    <Drawer
      width={"min(1180px, 96vw)"}
      open={open}
      onClose={onClose}
      destroyOnHidden
      title={
        <Space size={10}>
          <Title level={4} style={{ margin: 0 }}>
            {summary?.name ?? ticker ?? "-"}
          </Title>
          {ticker ? <TickerCell ticker={ticker} layout="inline" emphasize /> : null}
          {summary?.industry ? <Tag>{summary.industry}</Tag> : null}
          {summary?.timing ? (
            <Tag color={summary.timing.color}>{summary.timing.label}</Tag>
          ) : null}
        </Space>
      }
    >
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 12 }} /> : null}

      {ticker ? (
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={16}>
            <Card className="mq-card" size="small" title="K 线 (qfq)">
              <KLineChart apiBase={apiBase} ticker={ticker} height={460} />
            </Card>
          </Col>

          <Col xs={24} xl={8}>
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              <Card className="mq-card" size="small" title="择时状态" loading={loading && !summary}>
                {summary?.timing ? (
                  <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                    <Space size={6} wrap>
                      <Tag color={summary.timing.color}>{summary.timing.label}</Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {summary.end_date}
                      </Text>
                    </Space>
                    {summary.timing.description ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {summary.timing.description}
                      </Text>
                    ) : null}
                    {summary.timing.reasons.length > 0 ? (
                      <div>
                        <Text strong style={{ fontSize: 12 }}>
                          理由：
                        </Text>
                        <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                          {summary.timing.reasons.map((r, i) => (
                            <li key={i} style={{ fontSize: 12 }}>
                              {r}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {summary.timing.risks.length > 0 ? (
                      <div>
                        <Text strong style={{ fontSize: 12 }}>
                          风险：
                        </Text>
                        <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                          {summary.timing.risks.map((r, i) => (
                            <li key={i} style={{ fontSize: 12, color: "#dc2626" }}>
                              {r}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </Space>
                ) : (
                  <Skeleton active paragraph={{ rows: 3 }} />
                )}
              </Card>

              <Card className="mq-card" size="small" title="价格因子" loading={loading && !summary}>
                {summary ? (
                  <Descriptions size="small" column={1} colon>
                    <Descriptions.Item label="收盘">
                      {fmtNum(summary.price_factors.close)}
                    </Descriptions.Item>
                    <Descriptions.Item label="20D 收益">
                      {fmtPct(summary.price_factors.ret_20d)}
                    </Descriptions.Item>
                    <Descriptions.Item label="60D 收益">
                      {fmtPct(summary.price_factors.ret_60d)}
                    </Descriptions.Item>
                    <Descriptions.Item label="120D 收益">
                      {fmtPct(summary.price_factors.ret_120d)}
                    </Descriptions.Item>
                    <Descriptions.Item label="多头排列">
                      {summary.price_factors.ma_alignment === 1 ? "是" : "否"}
                    </Descriptions.Item>
                    <Descriptions.Item label="距 52W 高">
                      {fmtPct(summary.price_factors.dist_52w_high)}
                    </Descriptions.Item>
                    <Descriptions.Item label="60D 斜率">
                      {fmtPct(summary.price_factors.trend_slope_60d, 3)}
                    </Descriptions.Item>
                    <Descriptions.Item label="60D 年化波动">
                      {fmtPct(summary.price_factors.vol_60d)}
                    </Descriptions.Item>
                    <Descriptions.Item label="120D 最大回撤">
                      {fmtPct(summary.price_factors.max_drawdown_120d)}
                    </Descriptions.Item>
                  </Descriptions>
                ) : null}
              </Card>

              <Card
                className="mq-card"
                size="small"
                title={`所属池 (${summary?.pool_count ?? 0})`}
                loading={loading && !summary}
              >
                {summary && summary.pools.length > 0 ? (
                  <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                    {summary.pools.map((p) => (
                      <div key={p.pool_id}>
                        <Space size={6} wrap>
                          <Tag color={p.is_default ? "blue" : "default"}>{p.pool_name}</Tag>
                          {p.status ? <Tag>{p.status}</Tag> : null}
                          {p.current_score != null ? (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              当前分 {fmtNum(p.current_score)}
                            </Text>
                          ) : null}
                        </Space>
                      </div>
                    ))}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未在任何池中" />
                )}
              </Card>

              <Card
                className="mq-card"
                size="small"
                title={`交易计划 (${summary?.plan_count ?? 0})`}
                loading={loading && !summary}
              >
                {summary && summary.plans.length > 0 ? (
                  <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                    {summary.plans.map((p) => (
                      <Card key={p.id} size="small" className="mq-card">
                        <Space size={6} wrap>
                          <Text strong>#{p.id}</Text>
                          {p.action ? <Tag>{p.action}</Tag> : null}
                          {p.status ? <Tag color={p.status === "active" ? "green" : "default"}>{p.status}</Tag> : null}
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            入场{" "}
                            {p.entry_zone_low != null && p.entry_zone_high != null
                              ? `${fmtNum(p.entry_zone_low)}~${fmtNum(p.entry_zone_high)}`
                              : fmtNum(p.entry_zone_low ?? p.entry_zone_high)}{" "}
                            · 止损 {fmtNum(p.stop_loss)} · 仓位{" "}
                            {p.position_pct == null ? "-" : `${p.position_pct.toFixed(1)}%`}
                            {p.position_shares != null ? `（${p.position_shares} 股）` : ""}
                          </Text>
                        </Space>
                      </Card>
                    ))}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无计划" />
                )}
              </Card>

              <StockNewsCard apiBase={apiBase} ticker={ticker} name={summary?.name} onOpenAgent={onOpenAgent} />
            </Space>
          </Col>
        </Row>
      ) : null}
    </Drawer>
  );
}
