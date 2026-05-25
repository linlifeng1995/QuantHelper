import tushare as ts

# 官方推荐方式: 直接传 token
pro = ts.pro_api('c2e997be7edf782f096c2b71a55cb1da4460a1aa6e6f2205')

# 按 TeaJoin 文档切换请求入口
pro._DataApi__http_url = 'http://teajoin.com'

# 测试一个基础接口
df = pro.index_basic(limit=5)
print(df)
