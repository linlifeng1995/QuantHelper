"use client";

import {
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  InputNumber,
  Input,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";

type Fill = {
  id: number;
  plan_id: number;
  side: "buy" | "sell";
  trade_date: string;
  price: number;
  quantity: number;
  fee: number;
  note: string | null;
};

type Summary = {
  plan_id: number;
  fills_count: number;
  total_buy_qty: number;
  total_sell_qty: number;
  open_quantity: number;
  avg_cost: number | null;
  open_cost: number;
  realized_pnl: number;
  total_fee: number;
  realized_pnl_net: number;
  total_buy_cost: number;
  total_sell_value: number;
};

type FormValues = {
  side: "buy" | "sell";
  price: number;
  quantity: number;
  fee: number;
  trade_date?: string;
  note?: string;
};

interface Props {
  apiBase: string;
  planId: number;
}

export default function PlanFillsSection({ apiBase, planId }: Props) {
  const [fills, setFills] = useState<Fill[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/plans/${planId}/fills`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `加载失败 (${r.status})`);
      setFills(j.fills ?? []);
      setSummary(j.summary ?? null);
    } catch (err) {
      message.error(`加载成交记录失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [apiBase, planId]);

  useEffect(() => { void fetchData(); }, [fetchData]);

  const handleAdd = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        side: values.side,
        price: values.price,
        quantity: values.quantity,
        fee: values.fee ?? 0,
      };
      if (values.trade_date) body.trade_date = values.trade_date;
      if (values.note) body.note = values.note;
      const r = await fetch(`${apiBase}/api/plans/${planId}/fills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail ?? `提交失败 (${r.status})`);
      message.success(`已记录 ${values.side === "buy" ? "买入" : "卖出"} ${values.quantity} 股`);
      form.resetFields();
      await fetchData();
    } catch (err) {
      message.error(`录入失败：${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (fillId: number) => {
    try {
      const r = await fetch(`${apiBase}/api/plans/${planId}/fills/${fillId}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`删除失败 (${r.status})`);
      message.success("已删除");
      await fetchData();
    } catch (err) {
      message.error((err as Error).message);
    }
  };

  const columns: ColumnsType<Fill> = [
    {
      title: "方向",
      dataIndex: "side",
      width: 70,
      render: (v: string) => v === "buy" ? <Tag color="green">买入</Tag> : <Tag color="red">卖出</Tag>,
    },
    {
      title: "成交日",
      dataIndex: "trade_date",
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "—",
    },
    { title: "价格", dataIndex: "price", width: 80, render: (v: number) => v.toFixed(2) },
    { title: "股数", dataIndex: "quantity", width: 80 },
    { title: "手续费", dataIndex: "fee", width: 80, render: (v: number) => (v ?? 0).toFixed(2) },
    { title: "备注", dataIndex: "note", ellipsis: true, render: (v) => v ?? "—" },
    {
      title: "操作",
      width: 70,
      render: (_: unknown, row: Fill) => (
        <Popconfirm title="删除该成交记录？" onConfirm={() => handleDelete(row.id)} okText="删除" cancelText="取消">
          <Button size="small" type="link" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  const pnlColor = (v: number) => (v > 0 ? "#cf1322" : v < 0 ? "#52c41a" : undefined);

  return (
    <Card
      size="small"
      title={<span>成交记录</span>}
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>}
      style={{ marginTop: 12 }}
    >
      {summary ? (
        <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
          <Col xs={12} md={6}><Statistic title="持仓股数" value={summary.open_quantity} /></Col>
          <Col xs={12} md={6}><Statistic title="平均成本" value={summary.avg_cost != null ? summary.avg_cost.toFixed(3) : "—"} /></Col>
          <Col xs={12} md={6}>
            <Statistic title="已实现 (含费)" value={summary.realized_pnl_net.toFixed(2)} styles={{ content: { color: pnlColor(summary.realized_pnl_net) } }} />
          </Col>
          <Col xs={12} md={6}><Statistic title="手续费合计" value={summary.total_fee.toFixed(2)} /></Col>
        </Row>
      ) : null}

      <Form<FormValues>
        layout="inline"
        form={form}
        onFinish={handleAdd}
        initialValues={{ side: "buy", fee: 0 }}
        style={{ marginBottom: 12, rowGap: 8 }}
      >
        <Form.Item name="side" rules={[{ required: true }]}>
          <Select style={{ width: 90 }} options={[{ value: "buy", label: "买入" }, { value: "sell", label: "卖出" }]} />
        </Form.Item>
        <Form.Item name="price" rules={[{ required: true, message: "价格必填" }]}>
          <InputNumber min={0.001} step={0.01} placeholder="价格" style={{ width: 110 }} />
        </Form.Item>
        <Form.Item name="quantity" rules={[{ required: true, message: "股数必填" }]}>
          <InputNumber min={1} step={100} placeholder="股数" style={{ width: 110 }} />
        </Form.Item>
        <Form.Item name="fee">
          <InputNumber min={0} step={0.5} placeholder="手续费" style={{ width: 100 }} />
        </Form.Item>
        <Form.Item name="trade_date" tooltip="留空使用当前时间">
          <Input placeholder="2026-05-20T10:00:00" style={{ width: 180 }} />
        </Form.Item>
        <Form.Item name="note">
          <Input placeholder="备注（可选）" style={{ width: 160 }} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={submitting}>记录</Button>
        </Form.Item>
      </Form>

      {fills.length === 0 ? (
        <Empty description="暂无成交记录" />
      ) : (
        <Table<Fill>
          size="small"
          rowKey="id"
          columns={columns}
          dataSource={fills}
          pagination={false}
          loading={loading}
        />
      )}

      {summary && (summary.fills_count > 0) ? (
        <Descriptions size="small" column={2} style={{ marginTop: 12 }} bordered>
          <Descriptions.Item label="累计买入">{summary.total_buy_qty} 股 / ¥{summary.total_buy_cost.toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="累计卖出">{summary.total_sell_qty} 股 / ¥{summary.total_sell_value.toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="已实现盈亏 (含费前)" span={2}>
            <span style={{ color: pnlColor(summary.realized_pnl) }}>¥{summary.realized_pnl.toFixed(2)}</span>
          </Descriptions.Item>
          <Descriptions.Item label="持仓成本">¥{summary.open_cost.toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="净盈亏 (扣费后)">
            <span style={{ color: pnlColor(summary.realized_pnl_net) }}>¥{summary.realized_pnl_net.toFixed(2)}</span>
          </Descriptions.Item>
        </Descriptions>
      ) : null}
    </Card>
  );
}
