"""MyQuant 主动交易工作台核心业务包。

子模块：
- db: SQLAlchemy 引擎与 ORM 模型
- pools: 多股票池管理 DAO
- factors: Factor Registry 与因子桶计算器
- screening: 多因子选股流水线
- risk: 风控设置
- migrations: 启动建表 + watchlist.json 迁移
"""
