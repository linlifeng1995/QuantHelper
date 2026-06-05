# MyQuant Web 应用

## 启动方式：Next.js + Ant Design + FastAPI

### 一键启动（推荐）

如果已经安装 `myquant-lan-service` Codex skill，可以直接运行一键启动脚本：

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\64469\.codex\skills\myquant-lan-service\scripts\start-myquant-lan.ps1
```

脚本会同时启动 FastAPI 后端和 Next.js 前端，并输出本机地址、局域网地址和日志目录。

关闭服务：

```powershell
powershell -ExecutionPolicy Bypass -File c:\Tarde\my_quant\scripts\stop-lan.ps1
```

关闭脚本会停止监听 `3000` 和 `8000` 端口的进程。

快速重启：

```powershell
powershell -ExecutionPolicy Bypass -File c:\Tarde\my_quant\scripts\stop-lan.ps1
powershell -ExecutionPolicy Bypass -File C:\Users\64469\.codex\skills\myquant-lan-service\scripts\start-myquant-lan.ps1
```

如果一键启动提示 `Frontend already listening on 3000`，但浏览器页面打不开或返回 404，通常是旧前端进程占着端口。先运行关闭脚本，再重新启动。日志位置：

- `outputs/logs/frontend-lan.out.log`
- `outputs/logs/frontend-lan.err.log`
- `outputs/logs/backend-lan.out.log`
- `outputs/logs/backend-lan.err.log`

### 手动启动

安装或更新后端依赖：

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m pip install -r c:/Tarde/my_quant/requirements-api.txt
```

启动 FastAPI 后端服务：

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

启动 Next.js 前端服务：

```powershell
cd c:/Tarde/my_quant/frontend
npm install
npm run dev:lan
```

浏览器打开：

- 本机：http://localhost:3000
- 同一局域网其他设备：http://本机局域网IP:3000
- API 文档：http://本机局域网IP:8000/docs

如果 `3000` 端口已被占用，Next.js 会自动尝试使用其他端口，例如 `http://localhost:3001`。终端输出中的 `Local` 地址就是实际可访问地址。
如果其他设备仍无法访问，请确认 Windows 防火墙允许入站 TCP 端口 `3000` 和 `8000`，并确认访问设备与本机在同一局域网。

## 旧版 Streamlit 启动方式

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m streamlit run c:/Tarde/my_quant/web_app.py --server.headless true --server.address 0.0.0.0 --server.port 8501
```

浏览器打开：

- 本机：http://localhost:8501
- 同一局域网其他设备：http://本机局域网IP:8501

Streamlit 版本仍保留为旧版原型，React 前端迁移期间可以作为对照使用。

## 页面入口

新版前端分为以下工作区：

- 数据概览：查看缓存健康度、最新交易日覆盖情况、选股可用性、异常明细、推荐操作和近期更新记录。
- 数据更新：根据当前诊断结果推荐修复动作，并通过 FastAPI 后台任务执行日常同步、行情修复、基础面刷新和高级价格缓存重建。
- 筛选择股：展示数据可用性、筛选模板解释、因子权重、过滤摘要、候选股票表、股票详情抽屉和持久化观察池。
- 策略回测：调用 `/api/backtest`，基于当前筛选结果或持久化观察池进行只读缓存回测，包含数据预检、可选策略、买卖点明细、交易辅助建议、组合指标、权益曲线、策略对比和实际回测股票池。
- 首页会把数据状态明确分成“可实盘使用”“可研究使用”“禁止选股”。如果行情落后最新交易日但因子仍可用，页面会提示当前结果仅适合研究，不建议直接实盘使用。

旧版 Streamlit 应用分为 3 个页签：

- 数据更新：日常同步 / 缓存健康检查 / 修复工具 / 高级重建
- 筛选择股：股票池筛选并展示结果
- 策略回测：仅使用已筛选股票池和缓存价格回测

新版界面使用 Next.js、React 和 Ant Design。迁移期间，FastAPI 服务会复用 `web_app.py` 中已有的缓存、数据更新、选股和回测函数。

旧版界面使用 Streamlit 原生组件，并保留一层轻量自定义主题样式。

令牌使用说明：

- 同步到最新、修复行情价格缓存、刷新基础面字段缓存、全量重建需要 Tushare 令牌。
- 如果本地缓存文件已经存在，策略回测不需要令牌。

## 缓存行为

- 价格数据缓存在项目本地，不会在每次运行时全量重新下载。
- 应用会展示当前缓存日期范围。
- 更新、选股、回测前都会诊断数据缺口，包括价格缓存缺失、标的落后、基础面字段缺失和因子可用性。
- 当所选股票存在缺失或不完整价格缓存时，回测默认会被阻止；用户确认风险后，可以显式允许不完整数据继续回测。
- “同步到最新”是推荐的日常操作：先查询交易所最新交易日，只有当本地缓存落后于该交易日时才增量更新价格缓存。
- 数据概览中的“0 缺失 / 0 落后”表示当前本地缓存对当前股票池内部完整，不一定代表缓存已经覆盖交易所最新交易日。
- 修复工具采用单选流程：选择“修复行情价格缓存”或“刷新基础面字段缓存”，再执行对应操作。
- “修复行情价格缓存”只下载价格缓存中缺失的标的；也可以选择重试最新缓存日期落后于全局缓存最新日期的标的。
- “刷新基础面字段缓存”会按 `ts_code` 批量查询 `fina_indicator` 更新股票池缓存中的 ROE/GROWTH，并在最近报告期之间回退补数。PE/PB/成交额来自股票池快照，会在“同步到最新”时刷新。
- “全量重建”是高级恢复操作，会从配置的开始日期到今天重新构建价格缓存，只建议在普通修复工具无法解决问题时使用。
- 下载任务支持通过“下载并发数”调整并发，提高吞吐。
- React 前端的数据更新操作会作为 FastAPI 后台任务运行，前端通过 `/api/tasks/{task_id}` 轮询进度和结果。
- 数据概览页和数据更新页通过 `/api/cache/summary` 的诊断结果联动：数据概览解释是否可用于选股，数据更新页高亮推荐修复动作。
- 当前 FastAPI 进程生命周期内的近期更新历史可通过 `/api/tasks/history` 获取。
- 观察池通过 `/api/watchlist` 读取、添加、移出和清空，数据保存到 `outputs/cache/watchlist.json`，刷新页面后仍会保留。
- `/api/backtest` 接收所选股票和策略参数，验证指定日期区间内缓存价格是否可用，并返回组合指标、策略对比、权益曲线点、预检详情和实际使用标的。
- `/api/backtest/strategies` 返回当前可选策略目录。第一版包括双均线趋势、均线趋势+止损、小盘动量轮动、均值回归(RSI)、布林带均值回归、MACD趋势确认和52周新高突破。
- `/api/backtest` 支持通过 `strategy_names` 选择一个或多个策略，并返回 `signals` 买卖点明细和 `advice` 当前交易辅助建议。建议内容基于规则状态生成，用于复核持仓、等待条件、退出条件和止损参考，不构成确定性买卖承诺。
- 固定股票池回测会显著提示幸存者偏差和未来信息偏差：它只说明当前这组股票在历史区间内的价格表现，不代表历史上当时能选出这些股票。
- `/api/backtest/rolling` 已预留滚动选股回测接口和前端模式说明。真正启用前需要逐期历史基础面/估值快照，避免生成不可信的漂亮回测。
- 回测支持沪深300、中证500、中证1000、创业板指等基准名称；若缓存中没有对应指数序列，前端会明确提示“基准不可用，本次回测不能判断超额收益”。
- 前端 RSI 控件与后端校验保持一致：买入阈值不超过 50，卖出阈值不低于 50。
- 日常同步只按标的补拉缺失日期，直到最新确认交易日。如果价格缓存和基础面字段已经可用，会快速结束并报告价格/股票池刷新已跳过。
- 高级全量重建会从开始日期到今天重建价格缓存。
- 策略回测页按所选日期区间读取缓存，不下载新数据。若所选股票存在不完整缓存，默认阻止回测，除非用户显式允许不完整数据。
- 如果所选股票池与价格缓存没有标的交集，回测可以选择回退到价格缓存中已有的标的。
- 买卖点明细来自历史收盘价和策略条件，尚未接入实时盘口、涨跌停、公告、财报和成交量冲击。用于下单前仍需要人工复核交易可执行性和仓位风险。

## 输出结果

- 策略对比表
- 股票池表
- 下载按钮：
  - 小盘三策略对比.csv
  - 小盘池样本清单.csv

应用也会将 CSV 文件写入：

- outputs/小盘三策略对比.csv
- outputs/小盘池样本清单.csv

价格缓存文件：

- outputs/cache/price_cache.pkl

观察池文件：

- outputs/cache/watchlist.json

## Agent 助手

前端支持两类入口：

- 全局入口：页头右上角“AI 助手”。
- 功能内入口：
  - 筛选结果表每行“Agent诊断”
  - 观察池表每行“Agent诊断”
  - 股票详情抽屉“Agent 诊断”
  - 回测页“复盘本次回测”
  - 推荐关注卡片“Agent解读”

聊天体验：

- 支持多会话（新建会话、切换会话、会话本地保存）。
- 支持 Enter 发送，Shift+Enter 换行。
- 支持打字机式显示回复，并可“停止生成”。

后端接口：

- 健康检查：`GET /api/agent/health`
- 调用入口：`POST /api/agent/invoke`

配置方式：

- 推荐在后端配置（环境变量）：
  - `AGENT_DEFAULT_PROVIDER`（可选：`kimi` / `deepseek`，默认 `kimi`）
  - Kimi：
    - `KIMI_API_KEY`
    - `KIMI_BASE_URL`（默认 `https://api.moonshot.cn/v1`）
    - `KIMI_MODEL`（默认 `moonshot-v1-8k`）
  - DeepSeek：
    - `DEEPSEEK_API_KEY`
    - `DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）
    - `DEEPSEEK_MODEL`（默认 `deepseek-v4-flash`）
- 可选口令：`AGENT_ACCESS_TOKEN`。配置后前端需要输入访问口令。
- 前端“会话栏”支持在 `Kimi` 与 `DeepSeek` 间切换；“高级设置”支持临时覆盖 key/base_url/model（仅保存在浏览器本地）。

## 筛选择股

- 筛选页采用“先风险过滤，再因子打分”的流程，并支持配置各类因子权重。
- React 筛选页会在数据不适合选股时提示用户。如果 `/api/cache/summary` 返回 `diagnostic.can_screen = false`，执行按钮会被禁用，并引导用户先进入数据更新页。
- 筛选页支持按板块/行业多选过滤。用户可以先选择一个或多个看好的行业，系统会先把股票池限定在这些行业内，再执行风险过滤和多因子打分；不选择行业时仍按全市场股票池筛选。
- 筛选模板包含面向用户的解释。因子滑块会显示当前百分比，也可以恢复为所选模板默认权重。
- 筛选结果默认展示自然语言过滤摘要和紧凑候选表。详细因子分、财务指标、收益、波动、最大回撤、入选标签和风险标签可在股票详情抽屉中查看。
- 筛选结果会额外生成风格标签、进攻分、防守分、估值压力、波动风险、回撤风险和流动性风险。详情页会用投资决策语言解释入选原因、主要风险和行业内分位数。
- 结果行支持“加入观察池”，观察池会写入后端本地缓存，可刷新保留、移出股票，并作为策略回测输入。
- 观察池升级为交易前检查清单：展示加入时评分、当前复筛评分变化、最新数据日期、当前触发风险项，并提醒下单前复核止损/止盈、财报日期和涨跌停可交易性。
- 筛选页会在排序前执行因子数据可用性检查。如果必要数据不完整，默认阻止筛选，除非用户显式允许不完整因子。
- 内置模板包括：稳健质量股、趋势质量股、低估值修复股、高成长强势股。稳健质量股为默认模板；趋势质量股和高成长强势股会明确提示进攻、高波动或高估值风险。
- 当前缓存已实现的因子包括：20/60/120 日动量、距离 52 周高点、行业相对强度、动量加速度、ROE、PE、PB、营收增长、波动率、最大回撤和流动性代理指标。
- 支持行业中性打分；样本过小的行业会回退到全市场分位数，避免排名不稳定。
- 因子权重会自动归一化。综合评分 = 动量、质量、估值、成长、风险控制和资金情绪等因子桶得分的加权和。
- 提高某类因子权重会让候选池向对应风格倾斜：动量偏向近期趋势更强，质量偏向 ROE 更高，估值偏向 PE/PB 更低，成长偏向营收扩张，风险控制偏向低波动/低回撤，资金情绪偏向交易更活跃/流动性更好。
- 每只入选股票都会包含入选解释和风险提示。
- 以下接口字段已验证可扩展，但在缓存并接入因子引擎前暂不参与打分：审计意见、长时间停牌状态、负债、商誉、ROA、利润率、现金流、PS、PEG、股息率、北向资金、融资融券、机构持仓、涨跌停执行约束。
