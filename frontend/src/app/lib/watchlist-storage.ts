/**
 * watchlist-storage.ts
 * 观察列表存储在浏览器 localStorage，每个用户独立，不依赖服务器。
 */

const STORAGE_KEY = "myquant_watchlist_v1";

export type WatchlistItem = {
  ticker: string;
  name?: string | null;
  industry?: string | null;
  入选原因?: string | null;
  风格标签?: string[] | null;
};

/** 读取全部观察列表 */
export function loadWatchlist(): WatchlistItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as WatchlistItem[]) : [];
  } catch {
    return [];
  }
}

/** 保存全部观察列表 */
export function saveWatchlist(rows: WatchlistItem[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
}

/** 添加或更新（按 ticker 去重） */
export function addToWatchlist(item: WatchlistItem): WatchlistItem[] {
  const rows = loadWatchlist();
  const idx = rows.findIndex((r) => r.ticker === item.ticker);
  if (idx >= 0) {
    rows[idx] = { ...rows[idx], ...item };
  } else {
    rows.push(item);
  }
  saveWatchlist(rows);
  return rows;
}

/** 删除单只股票 */
export function removeFromWatchlist(ticker: string): WatchlistItem[] {
  const rows = loadWatchlist().filter((r) => r.ticker !== ticker);
  saveWatchlist(rows);
  return rows;
}

/** 清空全部 */
export function clearWatchlist(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(STORAGE_KEY);
}
