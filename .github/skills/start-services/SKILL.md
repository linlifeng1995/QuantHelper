---
name: start-services
description: '启动 MyQuant Web 应用的开发服务 (start services / launch dev server / run backend / run frontend)。覆盖 FastAPI 后端 (uvicorn api.main:app, 端口 8000) 与 Next.js 前端 (npm run dev, 端口 3000)。在后台启动并完成端口占用、venv、依赖、node_modules 等完整预检，最后通过健康检查 (/docs 轮询 + 终端日志解析) 报告实际可访问 URL。用于："启动服务"、"启动前后端"、"run uvicorn"、"启动 next dev"、"开发服务器没起来"。不包含旧版 Streamlit 和自动安装依赖。'
argument-hint: '[backend|frontend|both] 默认 both'
---

# Start Services (MyQuant Web App)

## When to Use

- 用户要求"启动服务"、"启动 web 应用"、"启动前后端"、"run dev server"、"启动 FastAPI / Next.js"。
- 用户报告 dev server 没起来、想验证本地能不能访问 `http://localhost:3000` 或 `http://localhost:8000/docs`。
- 用户希望按推荐方式（后台 + 健康检查）一次性拉起开发环境。

**不适用于**：生产部署、Docker 构建、旧版 Streamlit (`web_app.py`) — 如需可手动按 [WEB_APP_README.md](../../../WEB_APP_README.md) 执行。

## Modes

| Mode | 启动内容 |
|------|---------|
| `both`（默认） | FastAPI + Next.js |
| `backend` | 仅 FastAPI (uvicorn) |
| `frontend` | 仅 Next.js (npm run dev) |

如果用户没明确说，按 `both` 处理。

## Prerequisites（必须全部通过才能启动）

按顺序执行下列检查；任一项失败就**停下来报告给用户**，不要自动修复环境。

1. **venv 存在**
   - 检查 `c:\Tarde\my_quant\.venv\Scripts\python.exe` 是否存在。
   - 命令：`Test-Path c:\Tarde\my_quant\.venv\Scripts\python.exe`
   - 失败：提示用户先创建虚拟环境。

2. **后端依赖已安装**（仅 backend / both 模式）
   - 命令：`c:/Tarde/my_quant/.venv/Scripts/python.exe -c "import fastapi, uvicorn; print('ok')"`
   - 失败：提示用户运行 `c:/Tarde/my_quant/.venv/Scripts/python.exe -m pip install -r c:/Tarde/my_quant/requirements-api.txt`，不要自动执行。

3. **前端依赖已安装**（仅 frontend / both 模式）
   - 检查 `Test-Path c:\Tarde\my_quant\frontend\node_modules`
   - 失败：提示用户在 `c:\Tarde\my_quant\frontend` 执行 `npm install`，不要自动执行。

4. **端口占用检查**
   - 后端 8000：`Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1 OwningProcess,State`
   - 前端 3000：同上换 3000
   - 端口被占用：**仅报告 PID 和占用进程名**（`Get-Process -Id <pid>`），询问用户是结束旧进程还是放弃启动。**不要**自动 `Stop-Process`。
   - 前端端口 3000 被占用时也可以直接启动；Next.js 会自动回退到 3001/3002，健康检查阶段会解析实际端口。

5. **Tushare token 提醒**
   - 启动服务本身**不需要** token。仅在用户后续触发"数据更新/同步"等接口时才需要。无需在此校验。

## Procedure

> 全部使用绝对路径 + PowerShell 语法 + 后台运行（`run_in_terminal` 设 `isBackground: true`）。
> 每个后台终端要记录返回的 `terminal id`，后续健康检查靠它读日志。

### 启动 FastAPI 后端（backend / both）

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

工作目录设为 `c:\Tarde\my_quant`。

### 启动 Next.js 前端（frontend / both）

```powershell
cd c:\Tarde\my_quant\frontend; npm run dev
```

> Next.js 首次编译可能需要 20–60 秒，健康检查要预留时间。

## Health Check

### 后端健康检查（轮询 /docs，最多 20 次，间隔 1 秒）

```powershell
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/docs' -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ok = $true; break }
  } catch { Start-Sleep -Seconds 1 }
}
if ($ok) { 'FastAPI ready: http://127.0.0.1:8000' } else { 'FastAPI NOT ready' }
```

### 前端健康检查（读后台终端日志）

1. 用 `get_terminal_output` 拉前端终端最新输出。
2. 找形如 `Local: http://localhost:3000`（或 3001/3002）的行，提取实际端口。
3. 如 30 秒内未出现 `Local:` 行，再等 30 秒重试一次；仍未出现则报告"前端疑似启动失败"并附上最新日志末尾给用户。

### 最终汇报给用户

成功时输出：

- FastAPI: `http://127.0.0.1:8000`
- API Docs: `http://127.0.0.1:8000/docs`
- Next.js: `http://localhost:<实际端口>`

任一服务未通过健康检查时，明确说明哪一项失败，附上对应终端日志末尾 20 行让用户判断。

## Troubleshooting

| 现象 | 处理 |
|------|------|
| 8000 被占用 | 报告 PID + 进程名，询问是否让用户手动 `Stop-Process -Id <pid>` |
| `ModuleNotFoundError: fastapi` | 提示用户执行 `pip install -r requirements-api.txt`（不自动执行） |
| `next: not found` 或缺少依赖 | 提示用户在 `frontend/` 执行 `npm install` |
| 前端长时间停在 "Compiling..." | 这是正常首启动，等待最多 60 秒；超时再判定失败 |
| 端口 3000 被占用 → Next.js 自动跳到 3001 | 不是错误，从日志中解析实际端口即可 |

## Stop Services

不要在用户没要求时关闭服务。当用户明确说"停止服务"时：

- 通过保留的 terminal id 调用 `kill_terminal`，或
- `Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess` 拿到 PID 后 `Stop-Process -Id <pid>`（前端同理换 3000/实际端口）。
- 销毁前确认无未保存工作。
