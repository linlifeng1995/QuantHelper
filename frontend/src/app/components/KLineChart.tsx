"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import { Alert, Skeleton, Space, Tag, Typography } from "antd";
import { TickerCell, registerTickerNames } from "./TickerCell";

const { Text } = Typography;

type KlineItem = {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

type KlineResponse = {
  ticker: string;
  ts_code: string;
  adjust: string;
  source: "cache" | "tushare" | "synth" | "empty";
  start: string;
  end: string;
  items: KlineItem[];
  ma: {
    ma20: (number | null)[];
    ma60: (number | null)[];
    ma120: (number | null)[];
  };
};

type Props = {
  apiBase: string;
  ticker: string;
  height?: number;
  adjust?: "qfq" | "raw";
};

const SOURCE_LABEL: Record<KlineResponse["source"], { label: string; color: string }> = {
  cache: { label: "本地缓存", color: "blue" },
  tushare: { label: "tushare", color: "green" },
  synth: { label: "close 合成", color: "orange" },
  empty: { label: "空", color: "default" },
};

export default function KLineChart({ apiBase, ticker, height = 480, adjust = "qfq" }: Props) {
  const [data, setData] = useState<KlineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!ticker) return;
    abortRef.current?.abort();
    const ctl = new AbortController();
    abortRef.current = ctl;
    setLoading(true);
    setError(null);
    fetch(`${apiBase}/api/stock/${encodeURIComponent(ticker)}/kline?adjust=${adjust}`, {
      signal: ctl.signal,
    })
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (!r.ok) throw new Error(j?.detail ?? `K 线加载失败 (${r.status})`);
        return j as KlineResponse;
      })
      .then((j) => {
        setData(j);
        registerTickerNames([j]);
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === "AbortError") return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
    return () => ctl.abort();
  }, [apiBase, ticker, adjust]);

  const option = useMemo<EChartsOption | null>(() => {
    if (!data || data.items.length === 0) return null;
    const dates = data.items.map((it) => it.date);
    const candles = data.items.map((it) => [it.open, it.close, it.low, it.high]);
    const volumes = data.items.map((it, idx) => {
      const open = it.open ?? 0;
      const close = it.close ?? 0;
      return {
        value: it.volume ?? 0,
        itemStyle: { color: close >= open ? "#ef4444" : "#10b981" },
        // 仅用于 hover tooltip
        _idx: idx,
      };
    });

    const ma = (arr: (number | null)[]) => arr.map((v) => (v == null ? "-" : v));

    return {
      animation: false,
      legend: {
        data: ["K 线", "MA20", "MA60", "MA120"],
        top: 4,
        textStyle: { fontSize: 11 },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: "rgba(20,20,20,0.85)",
        textStyle: { color: "#fff", fontSize: 12 },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: 56, right: 24, top: 36, height: "62%" },
        { left: 56, right: 24, top: "76%", height: "16%" },
      ],
      xAxis: [
        {
          type: "category",
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: "#888" } },
          splitLine: { show: false },
          axisLabel: { fontSize: 10 },
        },
        {
          type: "category",
          gridIndex: 1,
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: "#888" } },
          axisLabel: { show: false },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          splitArea: { show: false },
          splitLine: { lineStyle: { color: "rgba(120,120,120,0.15)" } },
          axisLabel: { fontSize: 10 },
        },
        {
          scale: true,
          gridIndex: 1,
          axisLabel: { show: false },
          axisTick: { show: false },
          axisLine: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start: 60, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], height: 18, bottom: 4, start: 60, end: 100 },
      ],
      series: [
        {
          name: "K 线",
          type: "candlestick",
          data: candles,
          itemStyle: {
            color: "#ef4444",
            color0: "#10b981",
            borderColor: "#ef4444",
            borderColor0: "#10b981",
          },
        },
        {
          name: "MA20",
          type: "line",
          data: ma(data.ma.ma20),
          smooth: true,
          symbol: "none",
          lineStyle: { width: 1, color: "#f59e0b" },
        },
        {
          name: "MA60",
          type: "line",
          data: ma(data.ma.ma60),
          smooth: true,
          symbol: "none",
          lineStyle: { width: 1, color: "#3b82f6" },
        },
        {
          name: "MA120",
          type: "line",
          data: ma(data.ma.ma120),
          smooth: true,
          symbol: "none",
          lineStyle: { width: 1, color: "#a855f7" },
        },
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
        },
      ],
    };
  }, [data]);

  if (loading && !data) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }
  if (error) {
    return <Alert type="error" showIcon title={error} />;
  }
  if (!data || !option) {
    return <Alert type="info" showIcon title="暂无 K 线数据" />;
  }

  const src = SOURCE_LABEL[data.source];

  return (
    <Space orientation="vertical" size={6} style={{ width: "100%" }}>
      <Space size={8} wrap>
        <Text strong><TickerCell ticker={data.ticker} layout="inline" emphasize /></Text>
        <Tag color={src.color}>{src.label}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {data.adjust.toUpperCase()} · {data.start} ~ {data.end} · {data.items.length} 根
        </Text>
        {data.source === "synth" ? (
          <Text type="warning" style={{ fontSize: 12 }}>
            未拉取真实 OHLCV，由 close 合成（影线不准）
          </Text>
        ) : null}
      </Space>
      <ReactECharts
        option={option}
        style={{ height, width: "100%" }}
        notMerge
        lazyUpdate
        opts={{ renderer: "canvas" }}
      />
    </Space>
  );
}
