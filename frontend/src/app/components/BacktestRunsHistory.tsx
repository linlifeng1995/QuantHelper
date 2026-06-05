"use client";

import { Button, Card, Empty, Modal, Popconfirm, Space, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, EyeOutlined, ReloadOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import { useCallback, useEffect, useState } from "react";
import { TickerCell } from "./TickerCell";

type RunSummary = {
  id: number;
  label: string | null;
  strategy: string;
  rebalance: string;
  start_date: string;
  end_date: string;
  top_n: number;
  universe_size: number;
  pool_id: number | null;
  total_return: number | null;
  annualized_return: number | null;
  max_drawdown: number | null;
  sharpe_ratio: number | null;
  win_rate: number | null;
  bench_total_return: number | null;
  bench_annualized_return: number | null;
  created_at: string | null;
  warnings?: string[];
};

type Trade = {
  id: number;
  period_index: number;
  period_start: string;
  period_end: string | null;
  action: "enter" | "hold" | "exit";
  ticker: string;
  weight: number | null;
  score: number | null;
};

type PeriodRecord = {
  start: string;
  end: string;
  portfolio_return: number;
  benchmark_return: number;
  excess: number;
  n_holdings: number;
  n_valid: number;
};

type EquityPoint = { date: string; portfolio: number; benchmark: number };

type RunDetail = RunSummary & {
  equity_curve: EquityPoint[];
  period_returns: PeriodRecord[];
  trades: Trade[];
  params: Record<string, unknown> | null;
};

interface Props {
  apiBase: string;
  refreshKey?: number;
}

const pct = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

const ACTION_COLORS: Record<string, string> = { enter: "green", hold: "blue", exit: "red" };
const ACTION_LABELS: Record<string, string> = { enter: "建仓", hold: "持有", exit: "退出" };

export default function BacktestRunsHistory({ apiBase, refreshKey }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/backtest/runs?limit=50`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `加载失败 (${r.status})`);
      setRuns(j.runs ?? []);
    } catch (err) {
      message.error(`加载历史失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => { void fetchRuns(); }, [fetchRuns, refreshKey]);

  const openDetail = async (id: number) => {
    setDetailLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/backtest/runs/${id}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `加载失败 (${r.status})`);
      setDetail(j as RunDetail);
    } catch (err) {
      message.error(`加载详情失败：${(err as Error).message}`);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const r = await fetch(`${apiBase}/api/backtest/runs/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`删除失败 (${r.status})`);
      message.success("已删除");
      await fetchRuns();
    } catch (err) {
      message.error((err as Error).message);
    }
  };

  const columns: ColumnsType<RunSummary> = [
    { title: "ID", dataIndex: "id", width: 60 },
    { title: "标签", dataIndex: "label", ellipsis: true, render: (v) => v ?? <span style={{ color: "#aaa" }}>—</span> },
    { title: "策略", dataIndex: "strategy", width: 140 },
    { title: "频率", dataIndex: "rebalance", width: 70 },
    { title: "区间", width: 200, render: (_: unknown, r) => `${r.start_date} ~ ${r.end_date}` },
    { title: "Top", dataIndex: "top_n", width: 60 },
    {
      title: "累计",
      dataIndex: "total_return",
      width: 90,
      render: (v: number | null) => (
        <span style={{ color: v != null && v >= 0 ? "#cf1322" : "#52c41a" }}>{pct(v)}</span>
      ),
    },
    { title: "年化", dataIndex: "annualized_return", width: 90, render: (v: number | null) => pct(v) },
    { title: "回撤", dataIndex: "max_drawdown", width: 90, render: (v: number | null) => pct(v) },
    { title: "夏普", dataIndex: "sharpe_ratio", width: 70, render: (v: number | null) => v == null ? "—" : v.toFixed(2) },
    { title: "基准", dataIndex: "bench_total_return", width: 90, render: (v: number | null) => pct(v) },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 150,
      render: (v: string | null) => v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "—",
    },
    {
      title: "操作",
      width: 110,
      render: (_: unknown, r: RunSummary) => (
        <Space>
          <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => void openDetail(r.id)}>查看</Button>
          <Popconfirm title="删除该回测记录？" onConfirm={() => handleDelete(r.id)} okText="删除" cancelText="取消">
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const equityOption = detail
    ? {
        tooltip: { trigger: "axis" },
        legend: { data: ["组合", "基准"], top: 0 },
        grid: { left: 50, right: 24, top: 30, bottom: 30 },
        xAxis: { type: "category", data: detail.equity_curve.map((p) => p.date) },
        yAxis: { type: "value" },
        series: [
          { name: "组合", type: "line", smooth: true, symbol: "none", data: detail.equity_curve.map((p) => +p.portfolio.toFixed(4)) },
          { name: "基准", type: "line", smooth: true, symbol: "none", lineStyle: { type: "dashed" }, data: detail.equity_curve.map((p) => +p.benchmark.toFixed(4)) },
        ],
      }
    : null;

  const tradesColumns: ColumnsType<Trade> = [
    { title: "期", dataIndex: "period_index", width: 50 },
    { title: "起", dataIndex: "period_start", width: 110 },
    {
      title: "动作",
      dataIndex: "action",
      width: 70,
      render: (v: string) => <Tag color={ACTION_COLORS[v]}>{ACTION_LABELS[v] ?? v}</Tag>,
    },
    { title: "股票", dataIndex: "ticker", width: 180, render: (value: string) => <TickerCell ticker={value} layout="stack" /> },
    { title: "权重", dataIndex: "weight", width: 80, render: (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%` },
    { title: "评分", dataIndex: "score", width: 90, render: (v: number | null) => v == null ? "—" : v.toFixed(4) },
  ];

  return (
    <Card
      size="small"
      title="历史回测"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchRuns} loading={loading}>刷新</Button>}
      style={{ marginTop: 16 }}
    >
      {runs.length === 0 ? (
        <Empty description="尚无保存的回测记录。运行回测时勾选「保存到历史」即可记录。" />
      ) : (
        <Table<RunSummary>
          size="small"
          rowKey="id"
          columns={columns}
          dataSource={runs}
          pagination={{ pageSize: 10 }}
          loading={loading}
          scroll={{ x: 1200 }}
        />
      )}

      <Modal
        title={detail ? `回测 #${detail.id} · ${detail.strategy} · ${detail.rebalance}` : "回测详情"}
        open={Boolean(detail)}
        onCancel={() => setDetail(null)}
        footer={null}
        width={1000}
        destroyOnHidden
        loading={detailLoading}
      >
        {detail ? (
          <>
            <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
              <Tag color="blue">{detail.start_date} ~ {detail.end_date}</Tag>
              <Tag>Top {detail.top_n}</Tag>
              <Tag>池规模 {detail.universe_size}</Tag>
              <Tag color={(detail.total_return ?? 0) >= 0 ? "red" : "green"}>累计 {pct(detail.total_return)}</Tag>
              <Tag>年化 {pct(detail.annualized_return)}</Tag>
              <Tag>回撤 {pct(detail.max_drawdown)}</Tag>
              <Tag>夏普 {detail.sharpe_ratio != null ? detail.sharpe_ratio.toFixed(2) : "—"}</Tag>
              <Tag color="default">基准累计 {pct(detail.bench_total_return)}</Tag>
            </Space>
            {equityOption ? (
              <ReactECharts option={equityOption} style={{ height: 280 }} notMerge lazyUpdate />
            ) : null}
            <Card size="small" title="分段表现" style={{ marginTop: 12 }}>
              <Table<PeriodRecord>
                size="small"
                rowKey={(r) => `${r.start}-${r.end}`}
                dataSource={detail.period_returns}
                pagination={{ pageSize: 6 }}
                columns={[
                  { title: "开始", dataIndex: "start", width: 110 },
                  { title: "结束", dataIndex: "end", width: 110 },
                  { title: "组合", dataIndex: "portfolio_return", width: 90, render: (v: number) => pct(v) },
                  { title: "基准", dataIndex: "benchmark_return", width: 90, render: (v: number) => pct(v) },
                  { title: "超额", dataIndex: "excess", width: 90, render: (v: number) => <span style={{ color: v >= 0 ? "#cf1322" : "#52c41a" }}>{pct(v)}</span> },
                  { title: "持仓数", dataIndex: "n_holdings", width: 80 },
                ]}
              />
            </Card>
            <Card size="small" title={`成交明细 (${detail.trades.length})`} style={{ marginTop: 12 }}>
              <Table<Trade>
                size="small"
                rowKey="id"
                dataSource={detail.trades}
                columns={tradesColumns}
                pagination={{ pageSize: 10 }}
              />
            </Card>
          </>
        ) : null}
      </Modal>
    </Card>
  );
}
