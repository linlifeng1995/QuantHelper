"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, Card, Checkbox, Space, Tag, Tooltip, Typography, Skeleton, Alert, Empty } from "antd";
import { ClockCircleOutlined, LinkOutlined, RobotOutlined, CheckSquareOutlined, BorderOutlined } from "@ant-design/icons";
import type { AgentDraft } from "./AgentAssistantDrawer";

const { Text, Link } = Typography;

type NewsItem = {
  id: string;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
  published_display: string;
  tags: string[];
};

const TAG_COLORS: Record<string, string> = {
  业绩: "gold",
  政策: "blue",
  并购重组: "purple",
  回购分红: "green",
  资金面: "cyan",
  产品业务: "geekblue",
  风险事件: "red",
  股价异动: "orange",
  行业动态: "default",
};

type Props = {
  apiBase: string;
  ticker: string;
  name?: string | null;
  /** Number of items to show, default 15 */
  limit?: number;
  /** Called when user clicks "分析新闻" button */
  onOpenAgent?: (draft: AgentDraft) => void;
};

export default function StockNewsCard({ apiBase, ticker, name, limit = 15, onOpenAgent }: Props) {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!ticker) return;
    let aborted = false;
    setLoading(true);
    setError(null);
    setItems([]);
    setSelected(new Set());

    const qs = new URLSearchParams({ limit: String(limit) });
    if (name) qs.set("name", name);
    fetch(`${apiBase}/api/stock/${encodeURIComponent(ticker)}/news?${qs.toString()}`)
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (!r.ok) throw new Error(j?.detail ?? `新闻加载失败 (${r.status})`);
        return (j?.items ?? []) as NewsItem[];
      })
      .then((news) => {
        if (!aborted) setItems(news);
      })
      .catch((err: unknown) => {
        if (!aborted) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!aborted) setLoading(false);
      });

    return () => {
      aborted = true;
    };
  }, [apiBase, ticker, name, limit]);

  const selectedItems = useMemo(
    () => items.filter((it) => selected.has(it.id)),
    [items, selected],
  );

  const allChecked = items.length > 0 && selected.size === items.length;
  const someChecked = selected.size > 0 && selected.size < items.length;

  function toggleAll() {
    if (allChecked) {
      setSelected(new Set());
    } else {
      setSelected(new Set(items.map((it) => it.id)));
    }
  }

  function toggleItem(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleAnalyze() {
    if (!onOpenAgent || selectedItems.length === 0) return;
    const newsBlock = selectedItems
      .map((it, i) => {
        const tags = it.tags.length ? `[${it.tags.join("/")}]` : "";
        return `${i + 1}. ${tags}【${it.published_display}·${it.source}】\n   ${it.title}\n   链接：${it.url}`;
      })
      .join("\n\n");
    const stockLabel = name ? `${ticker}（${name}）` : ticker;
    const userInput =
      `请以专业 A 股投资研究员的视角，分析以下关于 ${stockLabel} 的 ${selectedItems.length} 条近期新闻：\n\n` +
      newsBlock +
      `\n\n请按以下框架输出：\n` +
      `1. **核心要点** — 逐条提炼关键信息（1-2 句/条）\n` +
      `2. **综合影响评估** — 对基本面及短期股价的影响（标注 利好🟢/利空🔴/中性⚪，及影响程度 ★1-5）\n` +
      `3. **关联与叠加效应** — 多条新闻间的内在逻辑联系（若仅一条可略）\n` +
      `4. **风险信号识别** — 从新闻中提炼需警惕的潜在风险点\n` +
      `5. **可执行跟踪建议** — 给出 2-3 条具体操作或监控动作\n\n` +
      `请保持客观专业，结合当前市场环境给出有深度的投资参考意见。`;
    onOpenAgent({
      scene: "news_analysis",
      userInput,
      payload: {
        ticker,
        name: name ?? null,
        news_count: selectedItems.length,
        news_items: selectedItems.map((it) => ({
          title: it.title,
          source: it.source,
          published_display: it.published_display,
          url: it.url,
          tags: it.tags,
        })),
      },
    });
  }

  return (
    <Card
      className="mq-card"
      size="small"
      title={
        <Space size={8} style={{ width: "100%", justifyContent: "space-between", flexWrap: "nowrap" }}>
          <Space size={6}>
            <span>近期新闻热点</span>
            {!loading && items.length > 0 && (
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                {items.length} 条
              </Text>
            )}
          </Space>
          {!loading && items.length > 0 && onOpenAgent && (
            <Space size={6}>
              <Tooltip title={allChecked ? "取消全选" : "全选"}>
                <Button
                  type="text"
                  size="small"
                  icon={allChecked ? <CheckSquareOutlined /> : <BorderOutlined />}
                  onClick={toggleAll}
                  style={{ fontSize: 12, padding: "0 4px" }}
                >
                  {someChecked ? `已选 ${selected.size}` : allChecked ? `已选 ${selected.size}` : "全选"}
                </Button>
              </Tooltip>
              <Button
                type="primary"
                size="small"
                icon={<RobotOutlined />}
                disabled={selected.size === 0}
                onClick={handleAnalyze}
                style={{ fontSize: 12 }}
              >
                {selected.size > 0 ? `分析 ${selected.size} 条` : "Agent 分析"}
              </Button>
            </Space>
          )}
        </Space>
      }
    >
      {loading && <Skeleton active paragraph={{ rows: 4 }} />}
      {!loading && error && (
        <Alert type="warning" showIcon title={`新闻加载失败：${error}`} style={{ fontSize: 12 }} />
      )}
      {!loading && !error && items.length === 0 && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无相关新闻" />
      )}
      {!loading && !error && items.length > 0 && (
        <Space direction="vertical" size={0} style={{ width: "100%" }}>
          {items.map((item, idx) => (
            <div
              key={item.id}
              style={{
                padding: "8px 4px",
                borderBottom: idx < items.length - 1 ? "1px solid #f0f0f0" : undefined,
                cursor: onOpenAgent ? "default" : undefined,
              }}
            >
              <Space align="start" size={8} style={{ width: "100%" }}>
                {onOpenAgent && (
                  <Checkbox
                    checked={selected.has(item.id)}
                    onChange={() => toggleItem(item.id)}
                    style={{ marginTop: 2, flexShrink: 0 }}
                  />
                )}
                <Space direction="vertical" size={3} style={{ width: "100%", flex: 1 }}>
                  {/* Title + link */}
                  <Link
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ fontSize: 13, lineHeight: "1.45", fontWeight: 500 }}
                  >
                    {item.title}
                    <LinkOutlined style={{ marginLeft: 4, fontSize: 11, opacity: 0.6 }} />
                  </Link>
                  {/* Meta row */}
                  <Space size={6} wrap>
                    <Space size={3}>
                      <ClockCircleOutlined style={{ fontSize: 11, color: "#8c8c8c" }} />
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {item.published_display}
                      </Text>
                    </Space>
                    {item.source && (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {item.source}
                      </Text>
                    )}
                    {item.tags.map((tag) => (
                      <Tag
                        key={tag}
                        color={TAG_COLORS[tag] ?? "default"}
                        style={{ fontSize: 11, lineHeight: "16px", margin: 0 }}
                      >
                        {tag}
                      </Tag>
                    ))}
                  </Space>
                </Space>
              </Space>
            </div>
          ))}
        </Space>
      )}
    </Card>
  );
}
