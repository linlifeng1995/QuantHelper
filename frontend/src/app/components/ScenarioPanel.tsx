"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  InputNumber,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ExperimentOutlined, ReloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { TickerCell, registerTickerNames } from "./TickerCell";

const { Text } = Typography;

type ByTicker = {
  plan_id: number;
  ticker: string;
  name: string | null;
  position_pct: number;
  current_price: number | null;
  stop_loss: number | null;
  new_price: number | null;
  shock_pct: number;
  stopped: boolean;
  stock_return: number;
  account_contribution_pct: number;
};

type ScenarioResult = {
  name: string;
  shock_pct: number;
  overrides: Record<string, number>;
  portfolio_pnl_pct: number;
  stops_triggered: number;
  worst_ticker: string | null;
  worst_contribution_pct: number | null;
  best_ticker: string | null;
  best_contribution_pct: number | null;
  by_ticker: ByTicker[];
};

type PlanMeta = {
  plan_id: number;
  ticker: string;
  name: string | null;
  status: string;
  action: string;
  position_pct: number;
  current_price: number | null;
  price_source: string;
  stop_loss: number | null;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
};

type SimResp = {
  as_of: string | null;
  plans_count: number;
  total_position_pct: number;
  apply_stop_loss: boolean;
  include_drafts: boolean;
  plans: PlanMeta[];
  scenarios: ScenarioResult[];
};

type ScenarioInputRow = {
  key: string;
  name: string;
  shock_pct: number;
};

interface Props {
  apiBase: string;
}

const DEFAULT_INPUT_ROWS: ScenarioInputRow[] = [
  { key: "1", name: "大涨 +10%", shock_pct: 10 },
  { key: "2", name: "上涨 +5%", shock_pct: 5 },
  { key: "3", name: "震荡 0%", shock_pct: 0 },
  { key: "4", name: "回调 -5%", shock_pct: -5 },
  { key: "5", name: "下跌 -10%", shock_pct: -10 },
  { key: "6", name: "暴跌 -15%", shock_pct: -15 },
];

function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}
function pctFromRatio(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export default function ScenarioPanel({ apiBase }: Props) {
  const [includeDrafts, setIncludeDrafts] = useState(true);
  const [applyStopLoss, setApplyStopLoss] = useState(true);
  const [rows, setRows] = useState<ScenarioInputRow[]>(DEFAULT_INPUT_ROWS);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimResp | null>(null);
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);

  const runSimulate = useCallback(async () => {
    if (!rows.length) {
      message.warning("请至少保留一个情景");
      return;
    }
    setLoading(true);
    try {
      const body = {
        include_drafts: includeDrafts,
        apply_stop_loss: applyStopLoss,
        scenarios: rows.map((r) => ({ name: r.name, shock_pct: r.shock_pct / 100 })),
      };
      const resp = await fetch(`${apiBase}/api/scenario/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(typeof data?.detail === "string" ? data.detail : JSON.stringify(data));
      }
      setResult(data);
      const tickerRows = (data?.scenarios ?? []).flatMap((s: ScenarioResult) => s.by_ticker ?? []);
      registerTickerNames(tickerRows);
      setSelectedScenario(data.scenarios?.[0]?.name ?? null);
      if (data.plans_count === 0) {
        message.info("当前没有可纳入模拟的活跃计划");
      }
    } catch (err) {
      message.error(`模拟失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [apiBase, rows, includeDrafts, applyStopLoss]);

  useEffect(() => {
    runSimulate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const summaryChart = useMemo(() => {
    if (!result || !result.scenarios.length) return null;
    const names = result.scenarios.map((s) => s.name);
    const pnls = result.scenarios.map((s) => s.portfolio_pnl_pct);
    return {
      tooltip: { trigger: "axis", formatter: (params: { name: string; value: number }[]) => {
        const p = params[0];
        return `${p.name}<br/>组合 P&L: <b>${p.value.toFixed(2)}%</b>`;
      } },
      grid: { left: 50, right: 24, top: 30, bottom: 60 },
      xAxis: { type: "category", data: names, axisLabel: { rotate: 30 } },
      yAxis: { type: "value", axisLabel: { formatter: "{value}%" } },
      series: [{
        name: "组合 P&L",
        type: "bar",
        data: pnls.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? "#52c41a" : "#cf1322" } })),
        label: { show: true, position: "top", formatter: (p: { value: number }) => `${p.value.toFixed(2)}%` },
      }],
    };
  }, [result]);

  const inputColumns: ColumnsType<ScenarioInputRow> = [
    {
      title: "情景名",
      dataIndex: "name",
      render: (v: string, r: ScenarioInputRow) => (
        <input
          value={v}
          onChange={(e) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, name: e.target.value } : x)))}
          className="ant-input"
          style={{ width: "100%" }}
        />
      ),
    },
    {
      title: "冲击 %",
      dataIndex: "shock_pct",
      width: 140,
      render: (v: number, r: ScenarioInputRow) => (
        <InputNumber
          value={v}
          min={-50}
          max={50}
          step={1}
          onChange={(val) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, shock_pct: Number(val ?? 0) } : x)))}
          style={{ width: "100%" }}
          formatter={(val) => `${val}%`}
          parser={(val) => Number((val ?? "0").toString().replace(/%/g, ""))}
        />
      ),
    },
    {
      title: " ",
      width: 70,
      render: (_: unknown, r: ScenarioInputRow) => (
        <Button size="small" danger onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} disabled={rows.length <= 1}>删除</Button>
      ),
    },
  ];

  const tickerColumns: ColumnsType<ByTicker> = [
    { title: "股票", dataIndex: "ticker", width: 190, render: (v: string, r: ByTicker) => <TickerCell ticker={v} name={r.name} layout="stack" /> },
    { title: "仓位%", dataIndex: "position_pct", width: 90, render: (v) => pct(v) },
    { title: "现价", dataIndex: "current_price", width: 90, render: (v) => v === null ? "—" : v.toFixed(2) },
    { title: "止损", dataIndex: "stop_loss", width: 90, render: (v) => v === null ? "—" : v.toFixed(2) },
    { title: "冲击", dataIndex: "shock_pct", width: 90, render: (v) => pctFromRatio(v) },
    { title: "新价", dataIndex: "new_price", width: 90, render: (v) => v === null ? "—" : v.toFixed(2) },
    {
      title: "止损触发",
      dataIndex: "stopped",
      width: 90,
      render: (v: boolean) => v ? <Tag color="red">触发</Tag> : <Tag>未触发</Tag>,
    },
    {
      title: "个股收益",
      dataIndex: "stock_return",
      width: 100,
      render: (v: number) => <span style={{ color: v >= 0 ? "#52c41a" : "#cf1322" }}>{pctFromRatio(v)}</span>,
    },
    {
      title: "对账户贡献",
      dataIndex: "account_contribution_pct",
      width: 110,
      render: (v: number) => <Tag color={v >= 0 ? "green" : "red"}>{pct(v, 3)}</Tag>,
    },
  ];

  const scenarioColumns: ColumnsType<ScenarioResult> = [
    {
      title: "情景",
      dataIndex: "name",
      render: (v: string) => (
        <a onClick={() => setSelectedScenario(v)} style={{ fontWeight: selectedScenario === v ? 600 : undefined }}>{v}</a>
      ),
    },
    { title: "冲击%", dataIndex: "shock_pct", render: (v) => pctFromRatio(v) },
    {
      title: "组合 P&L",
      dataIndex: "portfolio_pnl_pct",
      render: (v: number) => <Tag color={v >= 0 ? "green" : "red"}>{pct(v, 3)}</Tag>,
    },
    {
      title: "止损触发",
      dataIndex: "stops_triggered",
      render: (v: number) => v > 0 ? <Tag color="red">{v}</Tag> : <Tag>0</Tag>,
    },
    {
      title: "最差",
      key: "worst",
      render: (_: unknown, r) => {
        if (!r.worst_ticker) return "—";
        const worstRow = (r.by_ticker ?? []).find((x) => x.ticker === r.worst_ticker);
        const label = worstRow?.name ? `${worstRow.name} (${r.worst_ticker})` : r.worst_ticker;
        return `${label} (${pct(r.worst_contribution_pct, 3)})`;
      },
    },
    {
      title: "最佳",
      key: "best",
      render: (_: unknown, r) => {
        if (!r.best_ticker) return "—";
        const bestRow = (r.by_ticker ?? []).find((x) => x.ticker === r.best_ticker);
        const label = bestRow?.name ? `${bestRow.name} (${r.best_ticker})` : r.best_ticker;
        return `${label} (${pct(r.best_contribution_pct, 3)})`;
      },
    },
  ];

  const detail = result?.scenarios.find((s) => s.name === selectedScenario) ?? result?.scenarios[0];

  return (
    <Card
      className="mq-card"
      title={<Space><ExperimentOutlined /> 组合情景模拟（C3）</Space>}
      extra={
        <Button icon={<ReloadOutlined />} onClick={runSimulate} loading={loading} type="primary">运行模拟</Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="基于活跃 / 草稿交易计划的价格冲击模拟"
        description="对每只持仓施加统一或自定义的价格冲击百分比，若价格在跌幅区间内触及止损则按止损价结清损失；最终按仓位百分比加总为组合 P&L。不依赖财务快照。"
      />

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={10}>
          <Card size="small" title="情景列表">
            <Space style={{ marginBottom: 8 }}>
              <Switch checked={includeDrafts} onChange={setIncludeDrafts} />
              <Text>包含 draft 计划</Text>
              <Switch checked={applyStopLoss} onChange={setApplyStopLoss} />
              <Tooltip title="跌破止损时按 stop_loss 价结清持仓损失">
                <Text>启用止损</Text>
              </Tooltip>
            </Space>
            <Table<ScenarioInputRow>
              size="small"
              rowKey="key"
              columns={inputColumns}
              dataSource={rows}
              pagination={false}
            />
            <Button
              size="small"
              style={{ marginTop: 8 }}
              onClick={() => setRows((rs) => [...rs, { key: String(Date.now()), name: `自定义 ${rs.length + 1}`, shock_pct: 0 }])}
            >
              + 添加情景
            </Button>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card size="small" title="组合 P&L 对比">
            {summaryChart ? (
              <ReactECharts option={summaryChart} style={{ height: 280 }} />
            ) : (
              <Empty description="尚未运行" />
            )}
          </Card>
        </Col>
      </Row>

      {result ? (
        <>
          <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
            <Col xs={12} md={6}><Card size="small"><Statistic title="纳入计划数" value={result.plans_count} /></Card></Col>
            <Col xs={12} md={6}><Card size="small"><Statistic title="总仓位" value={pct(result.total_position_pct)} /></Card></Col>
            <Col xs={12} md={6}><Card size="small"><Statistic title="行情基准日" value={result.as_of ?? "—"} /></Card></Col>
            <Col xs={12} md={6}><Card size="small"><Statistic title="止损规则" value={result.apply_stop_loss ? "启用" : "禁用"} /></Card></Col>
          </Row>

          <Card size="small" title="情景汇总" style={{ marginTop: 12 }}>
            <Table<ScenarioResult>
              size="small"
              rowKey="name"
              columns={scenarioColumns}
              dataSource={result.scenarios}
              pagination={false}
            />
          </Card>

          {detail ? (
            <Card size="small" title={`明细 · ${detail.name}（点击上方情景切换）`} style={{ marginTop: 12 }}>
              <Table<ByTicker>
                size="small"
                rowKey={(r) => `${r.plan_id}-${r.ticker}`}
                columns={tickerColumns}
                dataSource={detail.by_ticker}
                pagination={{ pageSize: 10 }}
                scroll={{ x: 1000 }}
              />
            </Card>
          ) : null}
        </>
      ) : null}
    </Card>
  );
}
