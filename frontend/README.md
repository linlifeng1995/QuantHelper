# MyQuant Frontend

Next.js + Ant Design frontend for the MyQuant FastAPI service.

## Start

Start the backend from the project root first:

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Then start this frontend:

```powershell
cd c:/Tarde/my_quant/frontend
npm install
npm run dev:lan
```

Open:

- Local: http://localhost:3000
- LAN: http://YOUR_LAN_IP:3000

If another device cannot connect, allow inbound TCP ports `3000` and `8000` in Windows Firewall.

## Current Pages

- 数据概览: cache coverage, repair signals, and factor readiness.
- 数据更新: background tasks for daily sync, price repair, fundamental refresh, and advanced rebuild.
- 筛选择股: template selection, factor weights, risk filters, and screening result table.

Only migrated pages are shown in the left navigation. 策略回测 remains in the legacy Streamlit app until its React page is implemented.

Data update actions are started with `POST /api/tasks` and monitored with `GET /api/tasks/{task_id}`.
