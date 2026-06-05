"use client";

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import PlanFillsSection from "./PlanFillsSection";
import PlanSensitivityChart from "./PlanSensitivityChart";
import { TickerCell, registerTickerNames } from "./TickerCell";

const { Text } = Typography;

type TakeProfit = { level: number; price: number; ratio: number; label?: string };
type Plan = {
  id?: number;
  ticker: string;
  name?: string | null;
  pool_id?: number | null;
  action: string;
  trading_state?: string | null;
  confidence: string;
  entry_zone_low?: number | null;
  entry_zone_high?: number | null;
  stop_loss?: number | null;
  stop_loss_method?: string | null;
  take_profits?: TakeProfit[];
  risk_reward?: number | null;
  position_pct?: number | null;
  position_shares?: number | null;
  risk_per_trade_pct?: number | null;
  account_capital?: number | null;
  reasons?: string[];
  risks?: string[];
  note?: string | null;
  valid_until?: string | null;
  status: string;
  created_at?: string;
  updated_at?: string;
};

type PoolSummary = { id: number; name: string };

const ACTION_COLORS: Record<string, string> = {
  buy: "green",
  add: "geekblue",
  hold: "blue",
  reduce: "orange",
  exit: "volcano",
  avoid: "default",
};
const ACTION_LABELS: Record<string, string> = {
  buy: "买入",
  add: "加仓",
  hold: "持有",
  reduce: "减仓",
  exit: "离场",
  avoid: "回避",
};
const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  active: "green",
  executed: "blue",
  cancelled: "red",
  expired: "orange",
};
const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  active: "执行中",
  executed: "已成交",
  cancelled: "已撤销",
  expired: "已过期",
};
const CONFIDENCE_COLORS: Record<string, string> = { high: "green", medium: "blue", low: "default" };

type Props = { apiBase: string };

export default function PlansPanel({ apiBase }: Props) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [pools, setPools] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string | undefined>(undefined);
  const [filterTicker, setFilterTicker] = useState<string>("");
  const [genOpen, setGenOpen] = useState(false);
  const [genForm] = Form.useForm();
  const [previewPlan, setPreviewPlan] = useState<Plan | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [detailPlan, setDetailPlan] = useState<Plan | null>(null);

  const fetchPlans = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set("status", filterStatus);
      if (filterTicker.trim()) params.set("ticker", filterTicker.trim());
      const r = await fetch(`${apiBase}/api/plans?${params.toString()}`);
      if (!r.ok) throw new Error(`加载失败 (${r.status})`);
      const j = (await r.json()) as { plans: Plan[] };
      const rows = j.plans ?? [];
      setPlans(rows);
      registerTickerNames(rows);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiBase, filterStatus, filterTicker]);

  const fetchPools = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/api/pools`);
      if (!r.ok) return;
      const j = (await r.json()) as { pools?: PoolSummary[] } | PoolSummary[];
      setPools(Array.isArray(j) ? j : j.pools ?? []);
    } catch {
      // ignore
    }
  }, [apiBase]);

  useEffect(() => { void fetchPlans(); }, [fetchPlans]);
  useEffect(() => { void fetchPools(); }, [fetchPools]);

  const handleGenerate = async (values: { ticker: string; pool_id?: number; valid_days?: number }) => {
    setPreviewLoading(true);
    try {
      const body: Record<string, unknown> = { ticker: values.ticker.trim() };
      if (values.pool_id) body.pool_id = values.pool_id;
      if (values.valid_days) body.valid_days = values.valid_days;
      const r = await fetch(`${apiBase}/api/plans/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `生成失败 (${r.status})`);
      registerTickerNames([j.plan as Plan]);
      setPreviewPlan(j.plan as Plan);
      setPreviewOpen(true);
      setGenOpen(false);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSavePreview = async () => {
    if (!previewPlan) return;
    try {
      const r = await fetch(`${apiBase}/api/plans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(previewPlan),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `保存失败 (${r.status})`);
      message.success(`已保存计划 #${j.plan.id}`);
      setPreviewOpen(false);
      setPreviewPlan(null);
      await fetchPlans();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handlePatch = async (id: number, patch: Partial<Plan>) => {
    try {
      const r = await fetch(`${apiBase}/api/plans/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `更新失败 (${r.status})`);
      }
      await fetchPlans();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const r = await fetch(`${apiBase}/api/plans/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`删除失败 (${r.status})`);
      message.success("已删除");
      await fetchPlans();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const columns: ColumnsType<Plan> = useMemo(() => [
    { title: "ID", dataIndex: "id", key: "id", width: 70 },
    {
      title: "代码",
      dataIndex: "ticker",
      key: "ticker",
      width: 170,
      render: (v: string, row) => (
        <a onClick={() => setDetailPlan(row)}><TickerCell ticker={v} name={row.name} layout="stack" /></a>
      ),
    },
    {
      title: "操作建议",
      dataIndex: "action",
      key: "action",
      width: 110,
      render: (v: string) => <Tag color={ACTION_COLORS[v] ?? "default"}>{ACTION_LABELS[v] ?? v}</Tag>,
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      key: "confidence",
      width: 80,
      render: (v: string) => <Tag color={CONFIDENCE_COLORS[v] ?? "default"}>{v}</Tag>,
    },
    {
      title: "进场区间",
      key: "entry",
      width: 150,
      render: (_, row) =>
        row.entry_zone_low != null && row.entry_zone_high != null
          ? `${row.entry_zone_low.toFixed(2)} ~ ${row.entry_zone_high.toFixed(2)}`
          : "-",
    },
    {
      title: "止损",
      dataIndex: "stop_loss",
      key: "stop_loss",
      width: 100,
      render: (v: number | null) => (v == null ? "-" : v.toFixed(2)),
    },
    {
      title: "盈亏比",
      dataIndex: "risk_reward",
      key: "risk_reward",
      width: 80,
      render: (v: number | null) => (v == null ? "-" : `${v.toFixed(1)} : 1`),
    },
    {
      title: "仓位",
      key: "pos",
      width: 130,
      render: (_, row) =>
        row.position_pct == null
          ? "-"
          : `${row.position_pct.toFixed(1)}%（${row.position_shares ?? 0} 股）`,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (v: string, row) => (
        <Select
          size="small"
          value={v}
          style={{ width: 100 }}
          options={Object.keys(STATUS_LABELS).map((k) => ({ value: k, label: STATUS_LABELS[k] }))}
          onChange={(val) => row.id && handlePatch(row.id, { status: val })}
        />
      ),
    },
    {
      title: "有效期",
      dataIndex: "valid_until",
      key: "valid_until",
      width: 140,
      render: (v: string | null) => v?.slice(0, 16).replace("T", " ") ?? "-",
    },
    {
      title: "操作",
      key: "ops",
      width: 90,
      render: (_, row) =>
        row.id ? (
          <Popconfirm title="确认删除该计划？" onConfirm={() => handleDelete(row.id!)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        ) : null,
    },
  ], []);  // eslint-disable-line react-hooks/exhaustive-deps

  const renderPlanDetail = (p: Plan) => (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label="股票" span={2}><TickerCell ticker={p.ticker} name={p.name} layout="inline" emphasize /></Descriptions.Item>
        <Descriptions.Item label="操作建议">
          <Tag color={ACTION_COLORS[p.action] ?? "default"}>{ACTION_LABELS[p.action] ?? p.action}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="择时状态">{p.trading_state ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="置信度">
          <Tag color={CONFIDENCE_COLORS[p.confidence] ?? "default"}>{p.confidence}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={STATUS_COLORS[p.status] ?? "default"}>{STATUS_LABELS[p.status] ?? p.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="进场区间">
          {p.entry_zone_low != null && p.entry_zone_high != null
            ? `${p.entry_zone_low.toFixed(2)} ~ ${p.entry_zone_high.toFixed(2)}`
            : "-"}
        </Descriptions.Item>
        <Descriptions.Item label="止损">
          {p.stop_loss != null ? `${p.stop_loss.toFixed(2)}（${p.stop_loss_method ?? "-"}）` : "-"}
        </Descriptions.Item>
        <Descriptions.Item label="盈亏比">{p.risk_reward != null ? `${p.risk_reward.toFixed(1)} : 1` : "-"}</Descriptions.Item>
        <Descriptions.Item label="仓位">
          {p.position_pct != null ? `${p.position_pct.toFixed(2)}%（${p.position_shares ?? 0} 股）` : "-"}
        </Descriptions.Item>
        <Descriptions.Item label="单笔风险预算">
          {p.risk_per_trade_pct != null ? `${p.risk_per_trade_pct.toFixed(1)}% / 总资金 ${p.account_capital?.toLocaleString() ?? "-"}` : "-"}
        </Descriptions.Item>
        <Descriptions.Item label="有效期">{p.valid_until?.slice(0, 16).replace("T", " ") ?? "-"}</Descriptions.Item>
      </Descriptions>

      {(p.take_profits ?? []).length > 0 ? (
        <Card size="small" title="止盈目标" className="mq-card">
          <Table
            size="small"
            rowKey="level"
            pagination={false}
            dataSource={p.take_profits ?? []}
            columns={[
              { title: "档位", dataIndex: "level", width: 60 },
              { title: "目标价", dataIndex: "price", render: (v: number) => v.toFixed(2) },
              { title: "减持比例", dataIndex: "ratio", render: (v: number) => `${(v * 100).toFixed(0)}%` },
              { title: "说明", dataIndex: "label" },
            ]}
          />
        </Card>
      ) : null}

      {(p.reasons ?? []).length > 0 ? (
        <Card size="small" title="判定依据" className="mq-card">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {p.reasons!.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </Card>
      ) : null}
      {(p.risks ?? []).length > 0 ? (
        <Card size="small" title="风险提示" className="mq-card">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {p.risks!.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </Card>
      ) : null}
    </Space>
  );

  return (
    <>
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} /> : null}
      <Card
        className="mq-card"
        title="交易计划"
        extra={
          <Space wrap>
            <Input
              size="small"
              placeholder="按代码过滤"
              value={filterTicker}
              onChange={(e) => setFilterTicker(e.target.value)}
              style={{ width: 140 }}
              allowClear
            />
            <Select
              size="small"
              placeholder="状态"
              allowClear
              value={filterStatus}
              style={{ width: 110 }}
              options={Object.keys(STATUS_LABELS).map((k) => ({ value: k, label: STATUS_LABELS[k] }))}
              onChange={(v) => setFilterStatus(v)}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={fetchPlans}>刷新</Button>
            <Button
              size="small"
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={() => { genForm.resetFields(); setGenOpen(true); }}
            >
              生成计划
            </Button>
          </Space>
        }
      >
        <Table
          size="small"
          rowKey={(r) => `${r.id}`}
          loading={loading}
          dataSource={plans}
          columns={columns}
          pagination={{ pageSize: 15 }}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Modal
        title="生成交易计划"
        open={genOpen}
        onCancel={() => setGenOpen(false)}
        onOk={() => genForm.submit()}
        confirmLoading={previewLoading}
        destroyOnHidden
      >
        <Form form={genForm} layout="vertical" onFinish={handleGenerate} initialValues={{ valid_days: 5 }}>
          <Form.Item label="标的代码" name="ticker" rules={[{ required: true, message: "请输入代码" }]}>
            <Input placeholder="例如：600000.SH" />
          </Form.Item>
          <Form.Item label="关联股票池" name="pool_id">
            <Select allowClear placeholder="可选" options={pools.map((p) => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item label="有效天数" name="valid_days">
            <InputNumber min={1} max={60} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={previewPlan ? `计划预览 · ${previewPlan.name ? `${previewPlan.name} (${previewPlan.ticker})` : previewPlan.ticker}` : "计划预览"}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        onOk={handleSavePreview}
        okText="保存为草稿"
        width={760}
        destroyOnHidden
      >
        {previewPlan ? renderPlanDetail(previewPlan) : null}
      </Modal>

      <Modal
        title={detailPlan ? `计划详情 #${detailPlan.id} · ${detailPlan.name ? `${detailPlan.name} (${detailPlan.ticker})` : detailPlan.ticker}` : "计划详情"}
        open={Boolean(detailPlan)}
        onCancel={() => setDetailPlan(null)}
        footer={null}
        width={900}
        destroyOnHidden
      >
        {detailPlan ? (
          <>
            {renderPlanDetail(detailPlan)}
            {detailPlan.id ? <PlanSensitivityChart apiBase={apiBase} planId={detailPlan.id} /> : null}
            {detailPlan.id ? <PlanFillsSection apiBase={apiBase} planId={detailPlan.id} /> : null}
          </>
        ) : null}
      </Modal>
    </>
  );
}
