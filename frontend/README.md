# MyQuant Frontend

Next.js + Ant Design frontend for the MyQuant FastAPI service.

## Start

Start the backend from the project root first:

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Then start this frontend:

```powershell
cd c:/Tarde/my_quant/frontend
npm install
npm run dev
```

Open:

- http://localhost:3000

## Current Pages

- 数据概览: cache coverage, repair signals, and factor readiness.
- 数据更新: background tasks for daily sync, price repair, fundamental refresh, and advanced rebuild.
- 筛选择股: template selection, factor weights, risk filters, and screening result table.

Only migrated pages are shown in the left navigation. 策略回测 remains in the legacy Streamlit app until its React page is implemented.

Data update actions are started with `POST /api/tasks` and monitored with `GET /api/tasks/{task_id}`.
