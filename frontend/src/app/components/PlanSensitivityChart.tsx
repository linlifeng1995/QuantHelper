"use client";

import { Alert, Card, Col, Row, Statistic, Switch, Tag, message } from "antd";
import ReactECharts from "echarts-for-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TickerCell, registerTickerNames } from "./TickerCell";

type Point = {
  shock_pct: number;
  new_price: number | null;
  stopped: boolean;
  stock_return: number;
  account_contribution_pct: number;
};

type TakeProfit = {
  level: number | null;
  price: number;
  ratio: number | null;
  shock_pct: number;
};

type Sensitivity = {
  plan_id: number;
  ticker: string;
  name: string | null;
  position_pct: number | null;
  current_price: number | null;
  price_source: string;
  stop_loss: number | null;
  apply_stop_loss: boolean;
  shock_start: number;
  shock_end: number;
  shock_step: number;
  stop_trigger_shock: number | null;
  break_even_shock: number | null;
  take_profits: TakeProfit[];
  points: Point[];
};

interface Props {
  apiBase: string;
  planId: number;
}

const pct = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export default function PlanSensitivityChart({ apiBase, planId }: Props) {
  const [data, setData] = useState<Sensitivity | null>(null);
  const [loading, setLoading] = useState(false);
  const [applyStop, setApplyStop] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        shock_start: "-0.20",
        shock_end: "0.20",
        shock_step: "0.01",
        apply_stop_loss: applyStop ? "true" : "false",
      });
      const r = await fetch(`${apiBase}/api/scenario/plan/${planId}/sensitivity?${params}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `加载失败 (${r.status})`);
      registerTickerNames([j as Sensitivity]);
      setData(j as Sensitivity);
    } catch (err) {
      message.error(`灵敏度加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [apiBase, planId, applyStop]);

  useEffect(() => { void fetchData(); }, [fetchData]);

  const option = useMemo(() => {
    if (!data) return {};
    const xs = data.points.map((p) => +(p.shock_pct * 100).toFixed(2));
    const stockReturn = data.points.map((p) => +(p.stock_return * 100).toFixed(3));
    const contrib = data.points.map((p) => +(p.account_contribution_pct).toFixed(3));

    const markLines: Array<Record<string, unknown>> = [];
    if (data.stop_trigger_shock != null) {
      markLines.push({
        xAxis: +(data.stop_trigger_shock * 100).toFixed(2),
        lineStyle: { color: "#ff4d4f", type: "dashed" },
        label: { formatter: `止损 ${pct(data.stop_trigger_shock)}`, color: "#ff4d4f" },
      });
    }
    if (data.break_even_shock != null) {
      markLines.push({
        xAxis: +(data.break_even_shock * 100).toFixed(2),
        lineStyle: { color: "#8c8c8c", type: "dotted" },
        label: { formatter: `盈亏平衡`, color: "#8c8c8c" },
      });
    }
    for (const tp of data.take_profits ?? []) {
      markLines.push({
        xAxis: +(tp.shock_pct * 100).toFixed(2),
        lineStyle: { color: "#52c41a", type: "dashed" },
        label: { formatter: `TP${tp.level ?? ""} ${pct(tp.shock_pct)}`, color: "#52c41a" },
      });
    }

    return {
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const arr = params as Array<{ axisValue: number; seriesName: string; data: number; color: string }>;
          if (!arr.length) return "";
          const xv = arr[0].axisValue;
          const lines = arr.map(
            (s) => `<span style="color:${s.color}">●</span> ${s.seriesName}: ${s.data.toFixed(3)}%`,
          );
          return `冲击 ${xv}%<br/>${lines.join("<br/>")}`;
        },
      },
      legend: { data: ["个股收益 %", "账户贡献 %（含仓位）"], top: 0 },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: {
        type: "category",
        data: xs,
        name: "价格冲击 %",
        nameLocation: "middle",
        nameGap: 24,
        axisLabel: { formatter: (v: string) => `${v}%` },
      },
      yAxis: {
        type: "value",
        name: "%",
        axisLabel: { formatter: (v: number) => `${v.toFixed(1)}%` },
      },
      series: [
        {
          name: "个股收益 %",
          type: "line",
          data: stockReturn,
          smooth: false,
          symbol: "none",
          lineStyle: { color: "#1677ff" },
          markLine: markLines.length ? { silent: true, symbol: "none", data: markLines } : undefined,
        },
        {
          name: "账户贡献 %（含仓位）",
          type: "line",
          data: contrib,
          smooth: false,
          symbol: "none",
          lineStyle: { color: "#fa8c16", width: 2 },
        },
      ],
    };
  }, [data]);

  return (
    <Card
      size="small"
      title={
        <span>
          单标的灵敏度
          {data?.ticker ? <span style={{ marginLeft: 8 }}><TickerCell ticker={data.ticker} name={data.name} layout="inline" /></span> : null}
          {data?.price_source ? (
            <Tag color={data.price_source === "cache" ? "green" : "orange"}>
              价格源：{data.price_source}
            </Tag>
          ) : null}
        </span>
      }
      extra={
        <span style={{ fontSize: 12 }}>
          应用止损 <Switch size="small" checked={applyStop} onChange={(v) => setApplyStop(v)} loading={loading} />
        </span>
      }
      style={{ marginTop: 12 }}
      loading={loading && !data}
    >
      {data ? (
        <>
          <Row gutter={[8, 8]} style={{ marginBottom: 8 }}>
            <Col xs={12} md={6}>
              <Statistic title="当前价" value={data.current_price != null ? data.current_price.toFixed(3) : "—"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="止损价" value={data.stop_loss != null ? data.stop_loss.toFixed(3) : "—"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="止损触发冲击"
                value={data.stop_trigger_shock != null ? pct(data.stop_trigger_shock) : "—"}
                styles={{ content: { color: "#ff4d4f" } }}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="盈亏平衡冲击"
                value={data.break_even_shock != null ? pct(data.break_even_shock) : "—"}
              />
            </Col>
          </Row>
          {data.current_price == null ? (
            <Alert
              type="warning"
              showIcon
              title="当前价不可用，曲线基于估算值；建议先同步价格缓存。"
              style={{ marginBottom: 8 }}
            />
          ) : null}
          <ReactECharts option={option} style={{ height: 320 }} notMerge lazyUpdate />
        </>
      ) : null}
    </Card>
  );
}
