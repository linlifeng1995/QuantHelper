# QuantHelper

QuantHelper 是一个面向 A 股研究、选股、回测和交易前检查的本地量化辅助工具。项目包含 FastAPI 后端、Next.js + Ant Design 前端、旧版 Streamlit 原型，以及本地缓存、因子打分、策略回测、观察池和 AI 助手相关模块。

## 主要功能

- 数据概览：查看本地缓存覆盖情况、最新交易日状态、因子可用性和推荐修复动作。
- 数据更新：通过后台任务执行日常同步、行情修复、基础面刷新和高级重建。
- 筛选择股：按行业、风险过滤、因子模板和自定义权重生成候选股票池。
- 观察池：保存关注标的，复查评分变化、风险项和交易前检查信息。
- 策略回测：基于本地缓存执行多策略回测，展示组合指标、权益曲线、买卖点和策略建议。
- 风险与情景分析：提供市场状态、组合风险、止损/仓位规划和情景模拟辅助。
- AI 助手：支持基于股票、筛选结果和回测上下文的诊断与解释。

## 技术栈

- 后端：Python, FastAPI, SQLAlchemy
- 前端：Next.js, React, TypeScript, Ant Design
- 数据与策略：本地价格缓存、因子注册、筛选管线、滚动/固定股票池回测
- 旧版原型：Streamlit

## 快速启动

### 后端

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m pip install -r c:/Tarde/my_quant/requirements-api.txt
c:/Tarde/my_quant/.venv/Scripts/python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```powershell
cd c:/Tarde/my_quant/frontend
npm install
npm run dev:lan
```

打开：

- 本机前端：http://localhost:3000
- API 文档：http://localhost:8000/docs

如果需要同一局域网设备访问，请允许 Windows 防火墙入站 TCP 端口 `3000` 和 `8000`。

## 旧版 Streamlit

```powershell
c:/Tarde/my_quant/.venv/Scripts/python.exe -m streamlit run c:/Tarde/my_quant/web_app.py --server.headless true --server.address 0.0.0.0 --server.port 8501
```

打开：http://localhost:8501

## 目录结构

```text
api/                 FastAPI 应用和路由
frontend/            Next.js 前端
myquant/             核心量化模块
docs/                用户手册、设计文档和快速入门
deploy/              部署配置与脚本
scripts/             本地启动、停止和 smoke test 脚本
outputs/             本地输出和缓存目录
WEB_APP_README.md    Web 应用详细说明
web_app.py           旧版 Streamlit 应用
```

## 重要说明

- Tushare 令牌用于同步最新行情、修复价格缓存、刷新基础面字段和全量重建。
- 已有本地缓存时，策略回测可以不依赖实时下载。
- `outputs/cache/` 下的价格缓存、观察池和数据库文件属于本地运行数据，通常不应提交到 Git。
- 回测结果和 AI 诊断用于研究与复核，不构成确定性买卖建议。

## 腾讯云部署

部署流程和服务器说明见 [项目设计文档：服务器部署](docs/项目设计文档.md#17-服务器部署)。

关键部署文件：

- [server-setup.sh](deploy/server-setup.sh)：腾讯云 Ubuntu 22.04 初始化，安装系统依赖、Node.js、Nginx，并创建应用用户和目录。
- [upload.ps1](deploy/upload.ps1)：从 Windows 本地打包并上传项目到云服务器。
- [server-setup-2.sh](deploy/server-setup-2.sh)：上传后在服务器执行，安装 Python 依赖、构建前端、配置 `.env`、systemd 和 Nginx。
- [nginx.conf](deploy/nginx.conf)：Nginx 反向代理配置。
- [myquant-backend.service](deploy/myquant-backend.service)：FastAPI 后端 systemd 服务。
- [myquant-frontend.service](deploy/myquant-frontend.service)：Next.js 前端 systemd 服务。
- [requirements-deploy.txt](deploy/requirements-deploy.txt)：云服务器 Python 依赖清单。

## 更多文档

- [Web 应用详细说明](WEB_APP_README.md)
- [用户使用手册](docs/用户使用手册.md)
- [股票小白快速入门](docs/股票小白快速入门.md)
- [因子和策略白话手册](docs/因子和策略白话手册.md)
- [项目设计文档](docs/项目设计文档.md)
