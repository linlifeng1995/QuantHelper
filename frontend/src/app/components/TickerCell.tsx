"use client";

import { useEffect, useState } from "react";

const map = new Map<string, string>();
const listeners = new Set<() => void>();
const aliasNameRe = /^t\d+$/i;

function normalizeName(name?: string | null): string | undefined {
  const text = (name ?? "").trim();
  if (!text) return undefined;
  if (aliasNameRe.test(text)) return undefined;
  return text;
}

export function registerTickerNames(items: Array<{ ticker?: string | null; name?: string | null; 名称?: string | null } | null | undefined>) {
  let changed = false;
  for (const it of items) {
    if (!it) continue;
    const code = it.ticker;
    const name = normalizeName(it.name ?? it.名称);
    if (code && name && map.get(code) !== name) {
      map.set(code, name);
      changed = true;
    }
  }
  if (changed) listeners.forEach((fn) => fn());
}

export function getTickerName(ticker?: string | null): string | undefined {
  return ticker ? map.get(ticker) : undefined;
}

export function useTickerName(ticker?: string | null): string | undefined {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((x) => x + 1);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return ticker ? map.get(ticker) : undefined;
}

type CellProps = {
  ticker?: string | null;
  name?: string | null;
  layout?: "stack" | "inline";
  emphasize?: boolean;
};

export function TickerCell({ ticker, name, layout = "stack", emphasize = false }: CellProps) {
  const fallback = useTickerName(ticker ?? undefined);
  const display = normalizeName(name) ?? normalizeName(fallback) ?? null;
  if (!ticker) return <span>-</span>;
  if (layout === "inline") {
    return (
      <span className="mq-ticker-inline">
        {display ? <span className="mq-ticker-name-inline">{display}</span> : null}
        <span className={emphasize ? "mq-ticker-code-em" : "mq-ticker-code"}>{ticker}</span>
      </span>
    );
  }
  return (
    <div className="mq-ticker-cell">
      {display ? <div className="mq-ticker-name">{display}</div> : null}
      <div className={emphasize ? "mq-ticker-code-em" : "mq-ticker-code"}>{ticker}</div>
    </div>
  );
}
