"use client";

import { Alert, Button, Card, Checkbox, Col, DatePicker, Descriptions, Empty, Input, InputNumber, Row, Select, Space, Statistic, Table, Tag, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { LineChartOutlined, SaveOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import dayjs, { Dayjs } from "dayjs";
import ReactECharts from "echarts-for-react";
import BacktestRunsHistory from "./BacktestRunsHistory";

const { Text } = Typography;

type StrategyOpt = { value: string; label: string };
type RebalanceOpt = { value: string; label: string };
type PoolOpt = { id: number; name: string; item_count: number };

type EquityPoint = { date: string; portfolio: number; benchmark: number };
type Holding = { date: string; tickers: string[]; scores: Record<string, number> };
type PeriodRecord = {
  start: string;
  end: string;
  portfolio_return: number;
  benchmark_return: number;
  excess: number;
  n_holdings: number;
  n_valid: number;
};
type Metrics = {
  total_return: number;
  annualized_return: number;
  max_drawdown: number;
  sharpe: number;
  days: number;
  win_rate?: number;
  num_periods?: number;
  avg_period_return?: number;
};
type BacktestResp = {
  start_date: string;
  end_date: string;
  strategy: string;
  strategy_label: string;
  rebalance: string;
  top_n: number;
  universe_size: number;
  rebalance_dates: string[];
  equity_curve: EquityPoint[];
  holdings: Holding[];
  period_returns: PeriodRecord[];
  metrics: Metrics;
  benchmark_metrics: Metrics;
  warnings: string[];
  run_id?: number;
};

interface Props {
  apiBase: string;
}

function pct(v: number | undefined | null, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export default function RollingBacktestPanel({ apiBase }: Props) {
  const [strategies, setStrategies] = useState<StrategyOpt[]>([]);
  const [rebalanceOptions, setRebalanceOptions] = useState<RebalanceOpt[]>([]);
  const [pools, setPools] = useState<PoolOpt[]>([]);

  const [poolId, setPoolId] = useState<number | undefined>(undefined);
  const [strategy, setStrategy] = useState<string>("momentum_60d");
  const [rebalance, setRebalance] = useState<string>("month");
  const [topN, setTopN] = useState<number>(10);
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null]>([
    dayjs().subtract(1, "year"),
    dayjs(),
  ]);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResp | null>(null);
  const [savePersist, setSavePersist] = useState(false);
  const [saveLabel, setSaveLabel] = useState("");
  const [historyKey, setHistoryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [stratResp, poolResp] = await Promise.all([
          fetch(`${apiBase}/api/backtest/rolling/strategies`).then((r) => r.json()),
          fetch(`${apiBase}/api/pools`).then((r) => r.json()),
        ]);
        if (cancelled) return;
        setStrategies(stratResp.strategies || []);
        setRebalanceOptions(stratResp.rebalance_options || []);
        setPools(poolResp.pools || []);
        if (!poolId && Array.isArray(poolResp.pools) && poolResp.pools.length > 0) {
          setPoolId(poolResp.pools[0].id);
        }
      } catch (e) {
        message.error(`加载回测元数据失败：${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBase, poolId]);

  const runBacktest = useCallback(async () => {
    if (!poolId) {
      message.warning("请选择股票池");
      return;
    }
    const [s, e] = dateRange;
    if (!s || !e) {
      message.warning("请选择回测区间");
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch(`${apiBase}/api/backtest/rolling/price`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pool_id: poolId,
          start_date: s.format("YYYY-MM-DD"),
          end_date: e.format("YYYY-MM-DD"),
          strategy,
          rebalance,
          top_n: topN,
          save: savePersist,
          label: savePersist && saveLabel.trim() ? saveLabel.trim() : null,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(typeof data?.detail === "string" ? data.detail : JSON.stringify(data));
      }
      setResult(data);
      if (data?.run_id) {
        message.success(`已保存为回测 #${data.run_id}`);
        setHistoryKey((k) => k + 1);
      }
      if (Array.isArray(data.warnings) && data.warnings.length) {
        data.warnings.forEach((w: string) => message.warning(w));
      }
    } catch (err) {
      message.error(`回测失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [apiBase, poolId, dateRange, strategy, rebalance, topN, savePersist, saveLabel]);

  const chartOption = useMemo(() => {
    if (!result) return null;
    const dates = result.equity_curve.map((p) => p.date);
    const port = result.equity_curve.map((p) => p.portfolio);
    const bench = result.equity_curve.map((p) => p.benchmark);
    return {
      tooltip: { trigger: "axis" },
      legend: { data: ["组合权益", "基准（等权全集）"], top: 0 },
      grid: { left: 50, right: 24, top: 36, bottom: 48 },
      xAxis: { type: "category", data: dates, boundaryGap: false, axisLabel: { rotate: 0 } },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => v.toFixed(2) } },
      series: [
        { name: "组合权益", type: "line", data: port, smooth: true, lineStyle: { width: 2, color: "#1677ff" }, showSymbol: false },
        { name: "基准（等权全集）", type: "line", data: bench, smooth: true, lineStyle: { width: 2, color: "#fa8c16", type: "dashed" }, showSymbol: false },
      ],
    };
  }, [result]);

  const holdingColumns: ColumnsType<Holding> = [
    { title: "调仓日", dataIndex: "date", width: 110 },
    {
      title: "持仓",
      dataIndex: "tickers",
      render: (tickers: string[]) => (
        <Space wrap size={[4, 4]}>
          {tickers.map((t) => (
            <Tag key={t} color="blue">{t}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: "因子得分（前 3）",
      dataIndex: "scores",
      render: (scores: Record<string, number>) => {
        const top = Object.entries(scores).slice(0, 3);
        return (
          <Space wrap size={[4, 4]}>
            {top.map(([t, s]) => (
              <Tag key={t}>{t}: {s.toFixed(4)}</Tag>
            ))}
          </Space>
        );
      },
    },
  ];

  const periodColumns: ColumnsType<PeriodRecord> = [
    { title: "段开始", dataIndex: "start", width: 110 },
    { title: "段结束", dataIndex: "end", width: 110 },
    { title: "组合收益", dataIndex: "portfolio_return", render: (v) => pct(v) },
    { title: "基准收益", dataIndex: "benchmark_return", render: (v) => pct(v) },
    {
      title: "超额",
      dataIndex: "excess",
      render: (v: number) => <Tag color={v >= 0 ? "green" : "red"}>{pct(v)}</Tag>,
    },
    { title: "持仓数", dataIndex: "n_holdings", width: 80 },
    { title: "有效价格", dataIndex: "n_valid", width: 80 },
  ];

  return (
    <Card className="mq-card" title={<Space><LineChartOutlined /> 滚动价格回测（C2）</Space>}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="基于行情缓存的滚动选股回测"
        description="按调仓频率重新计算价格因子（动量/趋势/低波），每期等权持有前 N 只；基准为同股票池的等权全集。仅依赖价格数据，不需要财务快照。"
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Text className="mq-label">股票池</Text>
          <Select
            value={poolId}
            onChange={setPoolId}
            style={{ width: "100%" }}
            placeholder="选择股票池"
            options={pools.map((p) => ({ value: p.id, label: `${p.name}（${p.item_count} 只）` }))}
          />
        </Col>
        <Col xs={24} md={8}>
          <Text className="mq-label">策略</Text>
          <Select
            value={strategy}
            onChange={setStrategy}
            style={{ width: "100%" }}
            options={strategies}
          />
        </Col>
        <Col xs={24} md={4}>
          <Text className="mq-label">调仓频率</Text>
          <Select
            value={rebalance}
            onChange={setRebalance}
            style={{ width: "100%" }}
            options={rebalanceOptions}
          />
        </Col>
        <Col xs={24} md={4}>
          <Text className="mq-label">持仓数</Text>
          <InputNumber min={1} max={200} value={topN} onChange={(v) => setTopN(Number(v ?? 10))} style={{ width: "100%" }} />
        </Col>
        <Col xs={24} md={16}>
          <Text className="mq-label">回测区间</Text>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(vals) => setDateRange((vals as [Dayjs | null, Dayjs | null]) ?? [null, null])}
            style={{ width: "100%" }}
          />
        </Col>
        <Col xs={24} md={8} style={{ display: "flex", alignItems: "flex-end" }}>
          <Button type="primary" loading={loading} onClick={runBacktest} icon={<LineChartOutlined />} block>
            运行回测
          </Button>
        </Col>
      </Row>

      <Row gutter={[12, 8]} style={{ marginTop: 8 }} align="middle">
        <Col xs={24} md={6}>
          <Checkbox checked={savePersist} onChange={(e) => setSavePersist(e.target.checked)}>
            <SaveOutlined /> 保存到历史
          </Checkbox>
        </Col>
        <Col xs={24} md={10}>
          <Input
            placeholder="保存标签（可选）"
            value={saveLabel}
            onChange={(e) => setSaveLabel(e.target.value)}
            disabled={!savePersist}
            maxLength={64}
          />
        </Col>
      </Row>

      {result ? (
        <div style={{ marginTop: 20 }}>
          <Row gutter={[12, 12]}>
            <Col xs={12} md={6}><Card size="small"><Statistic title="累计收益" value={pct(result.metrics.total_return)} styles={{ content: { color: result.metrics.total_return >= 0 ? "#3f8600" : "#cf1322" } }} /></Card></Col>
            <Col xs={12} md={6}><Card size="small"><Statistic title="年化收益" value={pct(result.metrics.annualized_return)} styles={{ content: { color: result.metrics.annualized_return >= 0 ? "#3f8600" : "#cf1322" } }} /></Card></Col>
            <Col xs={12} md={6}><Card size="small"><Statistic title="最大回撤" value={pct(result.metrics.max_drawdown)} styles={{ content: { color: "#cf1322" } }} /></Card></Col>
            <Col xs={12} md={6}><Card size="small"><Statistic title="夏普比率" value={result.metrics.sharpe.toFixed(2)} /></Card></Col>
          </Row>

          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} style={{ marginTop: 12 }}>
            <Descriptions.Item label="策略">{result.strategy_label}</Descriptions.Item>
            <Descriptions.Item label="调仓频率">{result.rebalance}</Descriptions.Item>
            <Descriptions.Item label="股票池规模">{result.universe_size}</Descriptions.Item>
            <Descriptions.Item label="调仓次数">{result.rebalance_dates.length}</Descriptions.Item>
            <Descriptions.Item label="胜率">{pct(result.metrics.win_rate)}</Descriptions.Item>
            <Descriptions.Item label="平均期收益">{pct(result.metrics.avg_period_return)}</Descriptions.Item>
            <Descriptions.Item label="基准累计">{pct(result.benchmark_metrics.total_return)}</Descriptions.Item>
            <Descriptions.Item label="超额累计">
              <Tag color={(result.metrics.total_return - result.benchmark_metrics.total_return) >= 0 ? "green" : "red"}>
                {pct(result.metrics.total_return - result.benchmark_metrics.total_return)}
              </Tag>
            </Descriptions.Item>
          </Descriptions>

          {chartOption ? (
            <div style={{ marginTop: 12 }}>
              <ReactECharts option={chartOption} style={{ height: 320 }} />
            </div>
          ) : null}

          <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={12}>
              <Card size="small" title="分段表现">
                <Table<PeriodRecord>
                  size="small"
                  rowKey={(r) => `${r.start}-${r.end}`}
                  columns={periodColumns}
                  dataSource={result.period_returns}
                  pagination={{ pageSize: 8 }}
                />
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card size="small" title="历次持仓">
                <Table<Holding>
                  size="small"
                  rowKey="date"
                  columns={holdingColumns}
                  dataSource={result.holdings}
                  pagination={{ pageSize: 8 }}
                />
              </Card>
            </Col>
          </Row>
        </div>
      ) : (
        <Empty style={{ marginTop: 24 }} description="尚未运行回测" />
      )}

      <BacktestRunsHistory apiBase={apiBase} refreshKey={historyKey} />
    </Card>
  );
}
