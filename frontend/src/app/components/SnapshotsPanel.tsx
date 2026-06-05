"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  InputNumber,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import dayjs, { Dayjs } from "dayjs";

const { Text, Paragraph } = Typography;

type SnapshotLog = {
  id: number;
  kind: string;
  status: string;
  requested: number;
  inserted: number;
  skipped: number;
  failed: number;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
};

type SnapshotStatus = {
  daily_basic: { rows: number; tickers: number; latest_trade_date: string | null };
  fina: { rows: number; tickers: number; latest_ann_date: string | null; latest_end_date: string | null };
  recent_logs: SnapshotLog[];
};

type SyncResult = {
  kind: string;
  requested: number;
  inserted: number;
  skipped: number;
  failed: number;
  errors: string[];
  log_id: number | null;
};

type PoolOption = { id: number; name: string; item_count: number };

type Props = { apiBase: string };

const STATUS_COLOR: Record<string, string> = {
  succeeded: "green",
  running: "blue",
  partial: "orange",
  failed: "red",
};

export default function SnapshotsPanel({ apiBase }: Props) {
  const [status, setStatus] = useState<SnapshotStatus | null>(null);
  const [pools, setPools] = useState<PoolOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // daily_basic form
  const [dbStart, setDbStart] = useState<Dayjs | null>(dayjs().subtract(6, "day"));
  const [dbEnd, setDbEnd] = useState<Dayjs | null>(dayjs());
  const [dbPoolId, setDbPoolId] = useState<number | undefined>(undefined);
  const [dbSyncing, setDbSyncing] = useState(false);

  // fina form
  const [finaPoolId, setFinaPoolId] = useState<number | undefined>(undefined);
  const [finaLimit, setFinaLimit] = useState<number>(50);
  const [finaStart, setFinaStart] = useState<Dayjs | null>(dayjs().subtract(2, "year"));
  const [finaSyncing, setFinaSyncing] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/snapshots/status`);
      if (!res.ok) throw new Error(await res.text());
      setStatus(await res.json());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchPools = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/pools`);
      if (!res.ok) return;
      const json = await res.json();
      setPools(
        (json.pools ?? []).map((p: { id: number; name: string; item_count?: number }) => ({
          id: p.id,
          name: p.name,
          item_count: p.item_count ?? 0,
        })),
      );
    } catch {
      // 静默处理
    }
  }, [apiBase]);

  useEffect(() => {
    fetchStatus();
    fetchPools();
  }, [fetchStatus, fetchPools]);

  const tradeDatesPreview = useMemo(() => {
    if (!dbStart || !dbEnd) return [] as string[];
    const out: string[] = [];
    let cur = dbStart;
    while (cur.isBefore(dbEnd) || cur.isSame(dbEnd, "day")) {
      const day = cur.day();
      if (day !== 0 && day !== 6) out.push(cur.format("YYYY-MM-DD"));
      cur = cur.add(1, "day");
      if (out.length > 90) break;
    }
    return out;
  }, [dbStart, dbEnd]);

  const handleSyncResult = (label: string, result: SyncResult) => {
    if (result.failed > 0 && result.inserted === 0) {
      message.error(`${label}全部失败 (${result.failed})：${result.errors[0] ?? "未知错误"}`);
    } else if (result.failed > 0) {
      message.warning(`${label}部分成功：新增 ${result.inserted}、跳过 ${result.skipped}、失败 ${result.failed}`);
    } else {
      message.success(`${label}完成：新增 ${result.inserted}、跳过 ${result.skipped}`);
    }
  };

  const syncDailyBasic = async () => {
    if (tradeDatesPreview.length === 0) {
      message.warning("请选择有效日期区间");
      return;
    }
    if (tradeDatesPreview.length > 60) {
      message.error(`单次最多 60 个交易日，当前 ${tradeDatesPreview.length}`);
      return;
    }
    setDbSyncing(true);
    try {
      const res = await fetch(`${apiBase}/api/snapshots/sync/daily_basic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trade_dates: tradeDatesPreview, pool_id: dbPoolId ?? null }),
      });
      const json = await res.json();
      if (!res.ok) {
        throw new Error(json.detail ?? "请求失败");
      }
      handleSyncResult("估值切片同步", json.result);
      setStatus(json.status);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setDbSyncing(false);
    }
  };

  const syncFina = async () => {
    if (finaPoolId === undefined) {
      message.warning("请选择股票池");
      return;
    }
    setFinaSyncing(true);
    try {
      const res = await fetch(`${apiBase}/api/snapshots/sync/fina`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pool_id: finaPoolId,
          limit: finaLimit,
          start_date: finaStart ? finaStart.format("YYYY-MM-DD") : null,
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        throw new Error(json.detail ?? "请求失败");
      }
      handleSyncResult("财务指标同步", json.result);
      setStatus(json.status);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setFinaSyncing(false);
    }
  };

  const logColumns: ColumnsType<SnapshotLog> = [
    { title: "ID", dataIndex: "id", width: 60 },
    {
      title: "类型",
      dataIndex: "kind",
      width: 110,
      render: (v: string) => (v === "daily_basic" ? "估值切片" : "财务指标"),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag>,
    },
    { title: "请求", dataIndex: "requested", width: 70 },
    { title: "新增", dataIndex: "inserted", width: 70 },
    { title: "跳过", dataIndex: "skipped", width: 70 },
    { title: "失败", dataIndex: "failed", width: 70 },
    {
      title: "开始时间",
      dataIndex: "started_at",
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format("YYYY-MM-DD HH:mm:ss") : "-"),
    },
    { title: "错误", dataIndex: "error", ellipsis: true },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      {error ? <Alert type="error" showIcon title={error} closable onClose={() => setError(null)} /> : null}

      <Card
        className="mq-card"
        title="财务/估值快照状态"
        extra={
          <Button icon={<ReloadOutlined />} onClick={fetchStatus} loading={loading} size="small">
            刷新
          </Button>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <Card size="small" title="估值切片（daily_basic）">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="记录数">
                  <Statistic value={status?.daily_basic.rows ?? 0} styles={{ content: { fontSize: 16 } }} />
                </Descriptions.Item>
                <Descriptions.Item label="覆盖股票">{status?.daily_basic.tickers ?? 0}</Descriptions.Item>
                <Descriptions.Item label="最新交易日" span={2}>
                  {status?.daily_basic.latest_trade_date ?? <Text type="secondary">尚未同步</Text>}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
          <Col xs={24} md={12}>
            <Card size="small" title="财务指标（fina_indicator）">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="记录数">
                  <Statistic value={status?.fina.rows ?? 0} styles={{ content: { fontSize: 16 } }} />
                </Descriptions.Item>
                <Descriptions.Item label="覆盖股票">{status?.fina.tickers ?? 0}</Descriptions.Item>
                <Descriptions.Item label="最新公告日">{status?.fina.latest_ann_date ?? "-"}</Descriptions.Item>
                <Descriptions.Item label="最新报告期">{status?.fina.latest_end_date ?? "-"}</Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
        </Row>
        <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          财务快照表为空时，Phase 4 之后的因子评估会被显式拒绝，避免使用合成基本面。建议先按池为单位同步关键股票的财务指标。
        </Paragraph>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card className="mq-card" title="估值/换手率切片同步">
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              <div>
                <span className="mq-label">交易日区间（自动剔除周末）</span>
                <Space>
                  <DatePicker value={dbStart} onChange={setDbStart} />
                  <Text>至</Text>
                  <DatePicker value={dbEnd} onChange={setDbEnd} />
                </Space>
              </div>
              <div>
                <span className="mq-label">仅同步指定股票池（可选）</span>
                <Select
                  allowClear
                  placeholder="不选则同步全市场"
                  style={{ width: "100%" }}
                  value={dbPoolId}
                  onChange={setDbPoolId}
                  options={pools.map((p) => ({ value: p.id, label: `${p.name}（${p.item_count}只）` }))}
                />
              </div>
              <Alert
                type={tradeDatesPreview.length > 60 ? "error" : "info"}
                showIcon
                title={`将同步 ${tradeDatesPreview.length} 个交易日`}
                description={tradeDatesPreview.slice(0, 10).join("、") + (tradeDatesPreview.length > 10 ? "…" : "")}
              />
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={syncDailyBasic}
                loading={dbSyncing}
                block
              >
                开始同步估值切片
              </Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card className="mq-card" title="财务指标同步">
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              <div>
                <span className="mq-label">股票池</span>
                <Select
                  placeholder="请选择股票池"
                  style={{ width: "100%" }}
                  value={finaPoolId}
                  onChange={setFinaPoolId}
                  options={pools.map((p) => ({ value: p.id, label: `${p.name}（${p.item_count}只）` }))}
                />
              </div>
              <div>
                <span className="mq-label">起始报告期</span>
                <DatePicker value={finaStart} onChange={setFinaStart} style={{ width: "100%" }} />
              </div>
              <div>
                <span className="mq-label">最多同步股票数（限制每次请求）</span>
                <InputNumber
                  min={1}
                  max={200}
                  value={finaLimit}
                  onChange={(v) => setFinaLimit(Number(v ?? 50))}
                  style={{ width: "100%" }}
                />
              </div>
              <Alert
                type="warning"
                showIcon
                title="财务指标需按 ts_code 逐只请求，可能耗时较长"
                description="建议先用小池（如核心池前 50 只）验证 token 权限，再扩大范围。"
              />
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={syncFina}
                loading={finaSyncing}
                block
              >
                开始同步财务指标
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card className="mq-card" title="最近同步日志（最新 5 条）">
        <Table
          size="small"
          rowKey="id"
          dataSource={status?.recent_logs ?? []}
          columns={logColumns}
          pagination={false}
        />
      </Card>
    </Space>
  );
}
