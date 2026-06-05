"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, DownloadOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import StockDetailDrawer from "./StockDetailDrawer";
import { TickerCell, getTickerName, registerTickerNames } from "./TickerCell";
import type { AgentDraft } from "./AgentAssistantDrawer";
import { loadWatchlist } from "../lib/watchlist-storage";

const { Text } = Typography;

type PoolSummary = {
  id: number;
  name: string;
  pool_type: string;
  pool_type_label: string;
  description?: string | null;
  is_default: boolean;
  item_count: number;
  created_at: string;
  updated_at: string;
};

type PoolItem = {
  ticker: string;
  name?: string | null;
  industry?: string | null;
  added_at?: string | null;
  added_score?: number | null;
  added_reason?: string | null;
  current_score?: number | null;
  last_review_at?: string | null;
  tags?: string[] | null;
  priority?: number | null;
  status?: string | null;
  note?: string | null;
};

type PoolDetail = PoolSummary & { items: PoolItem[] };
type PoolType = { value: string; label: string };

type WatchlistItem = {
  ticker: string;
  name?: string | null;
  industry?: string | null;
};

type TimingRow = {
  ticker: string;
  state: string;
  label: string;
  color: string;
  description?: string;
  reasons?: string[];
  risks?: string[];
};
type TimingResponse = {
  pool_id: number;
  pool_name?: string;
  end_date?: string;
  count: number;
  items: TimingRow[];
};

type Props = { apiBase: string; onOpenAgent?: (draft: AgentDraft) => void };

export default function PoolsPanel({ apiBase, onOpenAgent }: Props) {
  const [pools, setPools] = useState<PoolSummary[]>([]);
  const [poolTypes, setPoolTypes] = useState<PoolType[]>([]);
  const [activePoolId, setActivePoolId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PoolDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [addItemOpen, setAddItemOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [addItemForm] = Form.useForm();
  const [timingMap, setTimingMap] = useState<Record<string, TimingRow>>({});
  const [timingLoading, setTimingLoading] = useState(false);
  const [timingEndDate, setTimingEndDate] = useState<string | null>(null);
  const [detailTicker, setDetailTicker] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [watchlistLoading, setWatchlistLoading] = useState(false);
  const [importSelected, setImportSelected] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);

  const fetchWatchlist = useCallback(() => {
    setWatchlistLoading(true);
    const rows = loadWatchlist() as WatchlistItem[];
    setWatchlist(rows);
    setImportSelected(rows.map((w) => w.ticker));
    setWatchlistLoading(false);
  }, []);

  const handleImportFromWatchlist = async () => {
    if (activePoolId === null || importSelected.length === 0) return;
    setImporting(true);
    const existingTickers = new Set((detail?.items ?? []).map((i) => i.ticker));
    const toAdd = watchlist.filter((w) => importSelected.includes(w.ticker) && !existingTickers.has(w.ticker));
    let successCount = 0;
    for (const item of toAdd) {
      try {
        const r = await fetch(`${apiBase}/api/pools/${activePoolId}/items`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker: item.ticker, name: item.name, industry: item.industry }),
        });
        if (r.ok) successCount++;
      } catch { /* skip individual failures */ }
    }
    setImporting(false);
    setImportOpen(false);
    if (successCount > 0) {
      message.success(`已导入 ${successCount} 条标的`);
      await fetchDetail(activePoolId);
      await fetchPools();
    } else if (toAdd.length === 0) {
      message.info("所选标的均已在该池中");
    } else {
      message.warning("导入失败，请检查导管日志");
    }
  };

  const fetchPools = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [poolsRes, typesRes] = await Promise.all([
        fetch(`${apiBase}/api/pools`),
        fetch(`${apiBase}/api/pools/types`),
      ]);
      if (!poolsRes.ok) throw new Error(`列表加载失败 (${poolsRes.status})`);
      const poolsJson = (await poolsRes.json()) as { pools?: PoolSummary[] } | PoolSummary[];
      const poolsData: PoolSummary[] = Array.isArray(poolsJson) ? poolsJson : (poolsJson.pools ?? []);
      const typesData = typesRes.ok ? ((await typesRes.json()) as { types: PoolType[] }) : { types: [] };
      setPools(poolsData);
      setPoolTypes(typesData.types ?? []);
      if (poolsData.length > 0 && (activePoolId === null || !poolsData.some((p) => p.id === activePoolId))) {
        const def = poolsData.find((p) => p.is_default) ?? poolsData[0];
        setActivePoolId(def.id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiBase, activePoolId]);

  const fetchDetail = useCallback(async (poolId: number) => {
    setDetailLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/pools/${poolId}`);
      if (!r.ok) throw new Error(`池详情加载失败 (${r.status})`);
      const data = (await r.json()) as PoolDetail;
      setDetail(data);
      registerTickerNames(data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }, [apiBase]);

  const fetchTiming = useCallback(async (poolId: number) => {
    setTimingLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/timing/pool/${poolId}`);
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `拉取择时失败 (${r.status})`);
      }
      const data = (await r.json()) as TimingResponse;
      const map: Record<string, TimingRow> = {};
      for (const row of data.items ?? []) map[row.ticker] = row;
      setTimingMap(map);
      setTimingEndDate(data.end_date ?? null);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setTimingLoading(false);
    }
  }, [apiBase]);

  useEffect(() => { void fetchPools(); }, [fetchPools]);
  useEffect(() => {
    if (activePoolId !== null) {
      void fetchDetail(activePoolId);
      setTimingMap({});
      setTimingEndDate(null);
      void fetchTiming(activePoolId);
    }
  }, [activePoolId, fetchDetail, fetchTiming]);

  const activePool = useMemo(() => pools.find((p) => p.id === activePoolId) ?? null, [pools, activePoolId]);

  const stockLabel = useCallback((ticker: string, name?: string | null) => {
    const raw = (name ?? "").trim();
    const resolved = raw && !/^t\d+$/i.test(raw) ? raw : (getTickerName(ticker) ?? "").trim();
    return resolved ? `${resolved} (${ticker})` : ticker;
  }, []);

  const displayName = useCallback((ticker: string, name?: string | null) => {
    const raw = (name ?? "").trim();
    if (raw && !/^t\d+$/i.test(raw)) return raw;
    return getTickerName(ticker) ?? "-";
  }, []);

  const handleCreate = async (values: { name: string; pool_type: string; description?: string }) => {
    try {
      const r = await fetch(`${apiBase}/api/pools`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `创建失败 (${r.status})`);
      }
      const created = (await r.json()) as PoolSummary;
      message.success(`已创建 ${created.name}`);
      setCreateOpen(false);
      createForm.resetFields();
      await fetchPools();
      setActivePoolId(created.id);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDelete = async (poolId: number) => {
    try {
      const r = await fetch(`${apiBase}/api/pools/${poolId}`, { method: "DELETE" });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `删除失败 (${r.status})`);
      }
      message.success("已删除");
      setActivePoolId(null);
      setDetail(null);
      await fetchPools();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleAddItem = async (values: { ticker: string; name?: string; industry?: string; note?: string; priority?: number }) => {
    if (activePoolId === null) return;
    try {
      const r = await fetch(`${apiBase}/api/pools/${activePoolId}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail ?? `加入失败 (${r.status})`);
      }
      message.success(`已加入 ${stockLabel(values.ticker, values.name)}`);
      setAddItemOpen(false);
      addItemForm.resetFields();
      await fetchDetail(activePoolId);
      await fetchPools();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleRemoveItem = async (ticker: string) => {
    if (activePoolId === null) return;
    try {
      const r = await fetch(`${apiBase}/api/pools/${activePoolId}/items/${encodeURIComponent(ticker)}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`移除失败 (${r.status})`);
      await fetchDetail(activePoolId);
      await fetchPools();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const poolColumns: ColumnsType<PoolSummary> = [
    { title: "名称", dataIndex: "name", key: "name", render: (v, row) => <Space>{v}{row.is_default ? <Tag color="blue">默认</Tag> : null}</Space> },
    { title: "类型", dataIndex: "pool_type_label", key: "pool_type_label" },
    { title: "成员", dataIndex: "item_count", key: "item_count", width: 80, align: "right" },
    { title: "更新时间", dataIndex: "updated_at", key: "updated_at", render: (v: string) => v?.slice(0, 19).replace("T", " ") ?? "-" },
    {
      title: "操作",
      key: "ops",
      width: 100,
      render: (_, row) => (
        <Popconfirm title={`确认删除 ${row.name}？`} disabled={row.is_default} onConfirm={() => handleDelete(row.id)}>
          <Button size="small" danger icon={<DeleteOutlined />} disabled={row.is_default}>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  const itemColumns: ColumnsType<PoolItem> = [
    {
      title: "股票",
      dataIndex: "ticker",
      key: "ticker",
      width: 180,
      render: (v: string, row) => (
        <a onClick={() => setDetailTicker(v)} style={{ cursor: "pointer" }}>
          <TickerCell ticker={v} name={row.name} layout="stack" />
        </a>
      ),
    },
    { title: "名称", dataIndex: "name", key: "name", render: (_: string | null | undefined, row) => displayName(row.ticker, row.name) },
    { title: "行业", dataIndex: "industry", key: "industry" },
    {
      title: "择时状态",
      key: "timing",
      width: 130,
      render: (_, row) => {
        const t = timingMap[row.ticker];
        if (!t) return <Tag color="default">-</Tag>;
        const tip = (
          <div style={{ maxWidth: 320 }}>
            <div style={{ marginBottom: 4 }}>{t.description}</div>
            {(t.reasons ?? []).length > 0 ? (
              <div><b>判定依据：</b><ul style={{ margin: 0, paddingLeft: 16 }}>{t.reasons!.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
            ) : null}
            {(t.risks ?? []).length > 0 ? (
              <div style={{ marginTop: 4 }}><b>风险提示：</b><ul style={{ margin: 0, paddingLeft: 16 }}>{t.risks!.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
            ) : null}
          </div>
        );
        return <Tooltip title={tip}><Tag color={t.color}>{t.label}</Tag></Tooltip>;
      },
    },
    { title: "加入评分", dataIndex: "added_score", key: "added_score", width: 100, align: "right", render: (v: number | null) => (v == null ? "-" : v.toFixed(2)) },
    { title: "最近评分", dataIndex: "current_score", key: "current_score", width: 100, align: "right", render: (v: number | null) => (v == null ? "-" : v.toFixed(2)) },
    { title: "加入原因", dataIndex: "added_reason", key: "added_reason", ellipsis: true },
    { title: "状态", dataIndex: "status", key: "status", width: 80 },
    {
      title: "操作",
      key: "ops",
      width: 90,
      render: (_, row) => (
        <Popconfirm title={`从池中移除 ${stockLabel(row.ticker, row.name)}？`} onConfirm={() => handleRemoveItem(row.ticker)}>
          <Button size="small" danger icon={<DeleteOutlined />}>移除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <>
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} /> : null}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card
            className="mq-card"
            title="股票池列表"
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} size="small" onClick={fetchPools}>刷新</Button>
                <Button icon={<PlusOutlined />} size="small" type="primary" onClick={() => setCreateOpen(true)}>新建池</Button>
              </Space>
            }
          >
            <Table
              size="small"
              rowKey="id"
              loading={loading}
              dataSource={pools}
              columns={poolColumns}
              pagination={false}
              rowClassName={(row) => (row.id === activePoolId ? "mq-row-active" : "")}
              onRow={(row) => ({ onClick: () => setActivePoolId(row.id), style: { cursor: "pointer" } })}
            />
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card
            className="mq-card"
            title={activePool ? `${activePool.name} · ${activePool.pool_type_label}` : "选择左侧池查看成员"}
            extra={activePool ? (
              <Space>
                <Button size="small" icon={<ReloadOutlined />} onClick={() => activePoolId && fetchDetail(activePoolId)}>刷新</Button>
                <Button size="small" loading={timingLoading} onClick={() => activePoolId && fetchTiming(activePoolId)}>刷新择时</Button>
                <Button size="small" icon={<DownloadOutlined />} onClick={() => { void fetchWatchlist(); setImportOpen(true); }}>从观察池导入</Button>
                <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddItemOpen(true)}>加入标的</Button>
              </Space>
            ) : null}
          >
            {activePool?.description ? <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>{activePool.description}</Text> : null}
            {timingEndDate ? <Text type="secondary" style={{ display: "block", marginBottom: 12, fontSize: 12 }}>择时基准日：{timingEndDate}</Text> : null}
            <Table
              size="small"
              rowKey="ticker"
              loading={detailLoading}
              dataSource={detail?.items ?? []}
              columns={itemColumns}
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: activePool ? "该池暂无成员" : "请选择一个池" }}
            />
          </Card>
        </Col>
      </Row>

      <Modal
        title="新建股票池"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item label="名称" name="name" rules={[{ required: true, message: "请输入池名称" }]}>
            <Input placeholder="例如：自选短线池" />
          </Form.Item>
          <Form.Item label="类型" name="pool_type" rules={[{ required: true, message: "请选择池类型" }]}>
            <Select options={poolTypes.map((t) => ({ value: t.value, label: t.label }))} placeholder="选择池类型" />
          </Form.Item>
          <Form.Item label="说明" name="description">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`加入标的 → ${activePool?.name ?? ""}`}
        open={addItemOpen}
        onCancel={() => setAddItemOpen(false)}
        onOk={() => addItemForm.submit()}
        destroyOnHidden
      >
        <Form form={addItemForm} layout="vertical" onFinish={handleAddItem}>
          <Form.Item label="代码" name="ticker" rules={[{ required: true, message: "如 600519.SS / 000001.SZ" }]}>
            <Input placeholder="600519.SS" />
          </Form.Item>
          <Form.Item label="名称" name="name"><Input /></Form.Item>
          <Form.Item label="行业" name="industry"><Input /></Form.Item>
          <Form.Item label="优先级" name="priority"><InputNumber min={0} max={100} /></Form.Item>
          <Form.Item label="备注" name="note"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
      <StockDetailDrawer
        apiBase={apiBase}
        ticker={detailTicker}
        open={detailTicker != null}
        onClose={() => setDetailTicker(null)}
        onOpenAgent={onOpenAgent}
      />

      <Modal
        title={`从筛选观察池导入 → ${activePool?.name ?? ""}`}
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onOk={() => void handleImportFromWatchlist()}
        okText={`导入所选 (${importSelected.length})`}
        okButtonProps={{ loading: importing, disabled: importSelected.length === 0 }}
        width={520}
        destroyOnHidden
      >
        {watchlist.length === 0 && !watchlistLoading ? (
          <div style={{ color: "#888", padding: "16px 0", textAlign: "center" }}>筛选观察池为空，请先在《筛选择股》页加入观察池</div>
        ) : (
          <>
            <div style={{ marginBottom: 8 }}>
              <Checkbox
                checked={importSelected.length === watchlist.length && watchlist.length > 0}
                indeterminate={importSelected.length > 0 && importSelected.length < watchlist.length}
                onChange={(e) => setImportSelected(e.target.checked ? watchlist.map((w) => w.ticker) : [])}
              >全选 ({watchlist.length} 条)</Checkbox>
            </div>
            <Table
              size="small"
              loading={watchlistLoading}
              dataSource={watchlist}
              rowKey="ticker"
              pagination={false}
              rowSelection={{
                selectedRowKeys: importSelected,
                onChange: (keys) => setImportSelected(keys as string[]),
              }}
              columns={[
                { title: "代码", dataIndex: "ticker", key: "ticker", width: 130 },
                { title: "名称", dataIndex: "name", key: "name", render: (v: string | null | undefined) => v ?? "-" },
                { title: "行业", dataIndex: "industry", key: "industry", render: (v: string | null | undefined) => v ?? "-" },
              ]}
            />
          </>
        )}
      </Modal>
    </>
  );
}
