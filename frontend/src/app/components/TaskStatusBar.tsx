"use client";

import { Button, Popconfirm, Progress, Space, Tag, Typography } from "antd";

const { Text } = Typography;

export type TaskBarStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "succeeded"
  | "failed";

export type TaskBarTask = {
  id: string;
  action: string;
  status: TaskBarStatus;
  progress?: number;
  chunk_progress?: number;
  message?: string;
  download_stats?: {
    total_tickers?: number;
    processed_tickers?: number;
    tickers_updated?: number;
    tickers_skipped?: number;
    tickers_failed?: number;
  };
};

const statusColor: Record<TaskBarStatus, string> = {
  queued: "blue",
  running: "blue",
  cancelling: "orange",
  cancelled: "default",
  succeeded: "green",
  failed: "red",
};

const statusLabel: Record<TaskBarStatus, string> = {
  queued: "排队中",
  running: "运行中",
  cancelling: "取消中",
  cancelled: "已取消",
  succeeded: "已完成",
  failed: "失败",
};

export interface TaskStatusBarProps {
  task: TaskBarTask | null;
  actionLabel: string;
  onCancel?: () => void;
  onJumpToUpdate?: () => void;
}

export default function TaskStatusBar({ task, actionLabel, onCancel, onJumpToUpdate }: TaskStatusBarProps) {
  if (!task) return null;
  const live = ["queued", "running", "cancelling"].includes(task.status);
  const progressPct = Math.round((task.progress ?? 0) * 100);
  const chunkPct = Math.round((task.chunk_progress ?? 0) * 100);
  const stats = task.download_stats;
  const hasStats = typeof stats?.total_tickers === "number" && stats.total_tickers > 0;
  return (
    <div
      className={`mq-task-bar mq-task-bar-${live ? "live" : task.status}`}
    >
      <Space size={8} wrap>
        <Tag color={statusColor[task.status]}>{statusLabel[task.status]}</Tag>
        <Text strong>{actionLabel}</Text>
        {task.message ? <Text type="secondary" style={{ maxWidth: 520 }} ellipsis>{task.message}</Text> : null}
      </Space>
      {live ? (
        <div style={{ minWidth: 220, flex: "1 1 220px" }}>
          <Progress percent={progressPct} size="small" status={task.status === "cancelling" ? "exception" : "active"} />
          {hasStats ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {`处理 ${stats?.processed_tickers ?? 0}/${stats?.total_tickers ?? 0}，更新 ${stats?.tickers_updated ?? 0}，跳过 ${stats?.tickers_skipped ?? 0}，失败 ${stats?.tickers_failed ?? 0}`}
            </Text>
          ) : null}
          {chunkPct > 0 && chunkPct < 100 ? (
            <Progress percent={chunkPct} size="small" showInfo={false} strokeColor="#15803d" style={{ marginTop: 4 }} />
          ) : null}
        </div>
      ) : null}
      <Space size={6}>
        {onJumpToUpdate ? (
          <Button size="small" type="link" onClick={onJumpToUpdate}>详情</Button>
        ) : null}
        {live && task.status !== "cancelling" && onCancel ? (
          <Popconfirm
            title="取消正在执行的任务？"
            description="已下载的数据会保留在 price_cache.parquet。"
            okText="取消任务"
            cancelText="再等等"
            onConfirm={onCancel}
          >
            <Button size="small" danger>取消任务</Button>
          </Popconfirm>
        ) : null}
        {task.status === "cancelling" ? <Button size="small" disabled>取消中…</Button> : null}
      </Space>
    </div>
  );
}
