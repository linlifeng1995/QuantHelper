"use client";

import { Alert, Button, Card, Space, Table, Tabs, Tag, Tooltip, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckCircleTwoTone, CloseCircleTwoTone, ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";

const { Text } = Typography;

type FactorDef = {
  factor_name: string;
  bucket: string;
  bucket_label: string;
  display_name: string;
  description?: string | null;
  tushare_api?: string | null;
  required_fields: string[];
  refresh_frequency: string;
  permission_required: string;
  higher_is_better: boolean;
  is_available: boolean;
  missing_reason?: string | null;
  fallback_behavior: string;
  participates_in_score: boolean;
};

type BucketGroup = {
  bucket: string;
  label: string;
  factors: FactorDef[];
  available: number;
};

type FactorsPayload = { factors: FactorDef[]; buckets: BucketGroup[] };

type Props = { apiBase: string };

export default function FactorsPanel({ apiBase }: Props) {
  const [data, setData] = useState<FactorsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true); else setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${apiBase}/api/factors${refresh ? "?refresh=true" : ""}`);
      if (!r.ok) throw new Error(`因子注册表加载失败 (${r.status})`);
      const payload = (await r.json()) as FactorsPayload;
      setData(payload);
      if (refresh) message.success("已根据本地缓存重新探测因子可用性");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiBase]);

  useEffect(() => { void fetchData(false); }, [fetchData]);

  const columns: ColumnsType<FactorDef> = [
    {
      title: "状态",
      key: "status",
      width: 80,
      render: (_, row) => row.is_available
        ? <Tooltip title="可参与评分"><CheckCircleTwoTone twoToneColor="#52c41a" /></Tooltip>
        : <Tooltip title={row.missing_reason ?? "数据不可用"}><CloseCircleTwoTone twoToneColor="#ff4d4f" /></Tooltip>,
    },
    { title: "因子", dataIndex: "display_name", key: "display_name" },
    { title: "代号", dataIndex: "factor_name", key: "factor_name" },
    {
      title: "方向",
      key: "direction",
      width: 80,
      render: (_, row) => row.higher_is_better ? <Tag color="green">越大越好</Tag> : <Tag color="orange">越小越好</Tag>,
    },
    {
      title: "参与评分",
      key: "participates",
      width: 100,
      render: (_, row) => row.participates_in_score ? <Tag color="blue">参与</Tag> : <Tag>仅展示</Tag>,
    },
    { title: "权限", dataIndex: "permission_required", key: "permission_required", width: 90 },
    { title: "刷新频率", dataIndex: "refresh_frequency", key: "refresh_frequency", width: 100 },
    { title: "数据来源", dataIndex: "tushare_api", key: "tushare_api" },
    {
      title: "缺失处理",
      dataIndex: "fallback_behavior",
      key: "fallback_behavior",
      width: 110,
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
    {
      title: "说明 / 不可用原因",
      key: "desc",
      render: (_, row) => (
        <Space orientation="vertical" size={2}>
          {row.description ? <Text>{row.description}</Text> : null}
          {!row.is_available && row.missing_reason ? <Text type="warning">{row.missing_reason}</Text> : null}
        </Space>
      ),
    },
  ];

  return (
    <>
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} /> : null}
      <Card
        className="mq-card"
        title="多因子注册表"
        extra={
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => fetchData(false)} loading={loading}>刷新视图</Button>
            <Button size="small" type="primary" icon={<ThunderboltOutlined />} onClick={() => fetchData(true)} loading={refreshing}>
              基于本地缓存重新探测可用性
            </Button>
          </Space>
        }
      >
        <Alert
          showIcon
          type="info"
          style={{ marginBottom: 12 }}
          title="按桶展示选股因子；仅“参与”且“可用”的因子会进入综合评分。事件类因子默认仅展示。"
          description="点击“重新探测可用性”会根据当前价格 / 池缓存动态判断每个因子能否参与本次评分。"
        />
        <Tabs
          items={(data?.buckets ?? []).map((b) => {
            const availableCount = b.factors.filter((f) => f.is_available).length;
            return {
            key: b.bucket,
            label: (
              <Space>
                <Text>{b.label}</Text>
                <Tag color={availableCount > 0 ? "green" : "default"}>可用 {availableCount}/{b.factors.length}</Tag>
              </Space>
            ),
            children: (
              <Table
                size="small"
                rowKey="factor_name"
                columns={columns}
                dataSource={b.factors}
                pagination={false}
                loading={loading}
              />
            ),
          };
          })}
        />
      </Card>
    </>
  );
}
