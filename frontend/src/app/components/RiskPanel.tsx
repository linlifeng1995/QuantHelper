"use client";

import { Alert, Button, Card, Col, Descriptions, Form, InputNumber, Progress, Row, Space, Table, Tag, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined, SaveOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import { TickerCell, registerTickerNames } from "./TickerCell";

const { Text } = Typography;

type RiskSettings = {
  account_capital: number;
  max_loss_per_trade_pct: number;
  max_single_position_pct: number;
  max_industry_exposure_pct: number;
  cap_strong_market_pct: number;
  cap_neutral_market_pct: number;
  cap_weak_market_pct: number;
  updated_at: string;
};

type PortfolioByTicker = {
  ticker: string;
  name?: string | null;
  position_pct: number;
  position_shares: number;
  plan_ids: number[];
  status_list: string[];
};

type PortfolioGuard = {
  regime: { regime: string; label: string; color: string; breadth_pct: number; sample_size: number; end_date: string | null };
  exposure: { total_position_pct: number; plan_count: number; by_ticker: PortfolioByTicker[] };
  caps: { single_position_pct: number; industry_pct: number; regime_total_pct: number };
  remaining_pct: number;
  warnings: { level: "warn" | "error"; code: string; message: string }[];
};

type Props = { apiBase: string };

export default function RiskPanel({ apiBase }: Props) {
  const [data, setData] = useState<RiskSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm<RiskSettings>();
  const [guard, setGuard] = useState<PortfolioGuard | null>(null);
  const [guardLoading, setGuardLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${apiBase}/api/risk/settings`);
      if (!r.ok) throw new Error(`风控设置加载失败 (${r.status})`);
      const payload = (await r.json()) as RiskSettings;
      setData(payload);
      form.setFieldsValue(payload);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiBase, form]);

  const fetchGuard = useCallback(async () => {
    setGuardLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/risk/portfolio`);
      if (!r.ok) throw new Error(`组合暴露加载失败 (${r.status})`);
      const payload = (await r.json()) as PortfolioGuard;
      registerTickerNames(payload?.exposure?.by_ticker ?? []);
      setGuard(payload);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setGuardLoading(false);
    }
  }, [apiBase]);

  useEffect(() => { void fetchData(); }, [fetchData]);
  useEffect(() => { void fetchGuard(); }, [fetchGuard]);

  const handleSave = async (values: Partial<RiskSettings>) => {
    setSaving(true);
    try {
      const r = await fetch(`${apiBase}/api/risk/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `保存失败 (${r.status})`);
      }
      const payload = (await r.json()) as RiskSettings;
      setData(payload);
      form.setFieldsValue(payload);
      message.success("风控设置已保存");
      void fetchGuard();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} /> : null}
      <Alert
        showIcon
        type="warning"
        style={{ marginBottom: 16 }}
        title="风控设置只影响未来生成的交易计划与仓位建议；不会触发任何自动交易。"
        description="所有比例为百分数（0–100）。修改后请点击保存，否则不会落库。"
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            className="mq-card"
            title="风控参数"
            extra={
              <Space>
                <Button size="small" icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>重新加载</Button>
                <Button size="small" type="primary" icon={<SaveOutlined />} onClick={() => form.submit()} loading={saving}>保存</Button>
              </Space>
            }
          >
            <Form form={form} layout="vertical" onFinish={handleSave} disabled={loading}>
              <Row gutter={[12, 0]}>
                <Col xs={24} md={12}>
                  <Form.Item
                    label="账户资金（元）"
                    name="account_capital"
                    rules={[{ required: true, message: "请输入账户资金" }]}
                    tooltip="用于计算每笔最大可承受亏损与单笔仓位上限的基准。"
                  >
                    <InputNumber min={0} step={1000} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item
                    label="单笔最大亏损 (%)"
                    name="max_loss_per_trade_pct"
                    rules={[{ required: true }]}
                    tooltip="ATR 止损与仓位倒推的基础；通常 0.5–2%。"
                  >
                    <InputNumber min={0} max={100} step={0.1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item
                    label="单只仓位上限 (%)"
                    name="max_single_position_pct"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} max={100} step={1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item
                    label="单一行业暴露上限 (%)"
                    name="max_industry_exposure_pct"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} max={100} step={1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item
                    label="强势市仓位上限 (%)"
                    name="cap_strong_market_pct"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} max={100} step={1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item
                    label="中性市仓位上限 (%)"
                    name="cap_neutral_market_pct"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} max={100} step={1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item
                    label="弱势市仓位上限 (%)"
                    name="cap_weak_market_pct"
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} max={100} step={1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card className="mq-card" title="当前生效配置">
            {data ? (
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="账户资金">{data.account_capital.toLocaleString()} 元</Descriptions.Item>
                <Descriptions.Item label="单笔最大亏损"><Tag color="red">{data.max_loss_per_trade_pct}%</Tag></Descriptions.Item>
                <Descriptions.Item label="单只仓位上限"><Tag color="blue">{data.max_single_position_pct}%</Tag></Descriptions.Item>
                <Descriptions.Item label="行业暴露上限"><Tag color="purple">{data.max_industry_exposure_pct}%</Tag></Descriptions.Item>
                <Descriptions.Item label="强势 / 中性 / 弱势仓位上限">
                  <Space>
                    <Tag color="green">{data.cap_strong_market_pct}%</Tag>
                    <Tag color="gold">{data.cap_neutral_market_pct}%</Tag>
                    <Tag color="red">{data.cap_weak_market_pct}%</Tag>
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="最近更新">{data.updated_at?.slice(0, 19).replace("T", " ")}</Descriptions.Item>
              </Descriptions>
            ) : <Text type="secondary">加载中…</Text>}
          </Card>
        </Col>
      </Row>

      <Card
        className="mq-card"
        style={{ marginTop: 16 }}
        title="当前组合暴露与市场状态"
        extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchGuard} loading={guardLoading}>刷新</Button>}
      >
        {guard ? (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Row gutter={[16, 12]}>
              <Col xs={24} md={8}>
                <Card size="small" className="mq-card">
                  <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                    <Text type="secondary">市场状态</Text>
                    <Space wrap>
                      <Tag color={guard.regime.color}>{guard.regime.label}</Tag>
                      <Text>宽度 {guard.regime.breadth_pct.toFixed(1)}%（{guard.regime.sample_size} 只）</Text>
                    </Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>基准日：{guard.regime.end_date ?? "-"}</Text>
                  </Space>
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card size="small" className="mq-card">
                  <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                    <Text type="secondary">总仓位 / 当前市况上限</Text>
                    <Progress
                      percent={Math.min(100, Math.round((guard.exposure.total_position_pct / Math.max(guard.caps.regime_total_pct, 1)) * 100))}
                      status={guard.exposure.total_position_pct > guard.caps.regime_total_pct ? "exception" : "active"}
                      format={() => `${guard.exposure.total_position_pct.toFixed(1)}% / ${guard.caps.regime_total_pct.toFixed(0)}%`}
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>剩余可建仓 {guard.remaining_pct.toFixed(1)}%（{guard.exposure.plan_count} 条计划）</Text>
                  </Space>
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card size="small" className="mq-card">
                  <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                    <Text type="secondary">风控上限</Text>
                    <Space wrap>
                      <Tag color="blue">单只 {guard.caps.single_position_pct.toFixed(0)}%</Tag>
                      <Tag color="purple">行业 {guard.caps.industry_pct.toFixed(0)}%</Tag>
                      <Tag color={guard.regime.color}>{guard.regime.label} {guard.caps.regime_total_pct.toFixed(0)}%</Tag>
                    </Space>
                  </Space>
                </Card>
              </Col>
            </Row>

            {guard.warnings.length > 0 ? (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                {guard.warnings.map((w, i) => (
                  <Alert key={i} type={w.level === "error" ? "error" : "warning"} showIcon title={w.message} />
                ))}
              </Space>
            ) : <Text type="secondary">暂无突破上限的告警。</Text>}

            <Table<PortfolioByTicker>
              size="small"
              rowKey="ticker"
              pagination={false}
              dataSource={guard.exposure.by_ticker}
              columns={[
                { title: "股票", dataIndex: "ticker", width: 180, render: (v: string, row: PortfolioByTicker) => <TickerCell ticker={v} name={row.name} layout="stack" /> },
                { title: "仓位 %", dataIndex: "position_pct", width: 100, render: (v: number) => `${v.toFixed(2)}%` },
                { title: "股数", dataIndex: "position_shares", width: 100 },
                { title: "关联计划", dataIndex: "plan_ids", render: (v: number[]) => v.join(", ") },
                { title: "状态", dataIndex: "status_list", render: (v: string[]) => v.join(", ") },
              ] as ColumnsType<PortfolioByTicker>}
            />
          </Space>
        ) : <Text type="secondary">加载中…</Text>}
      </Card>
    </>
  );
}
