from __future__ import annotations

import tushare as ts


DEFAULT_TUSHARE_TOKEN = "65a33a6fccb700cb781377ed3057fdbe2aab458e3276894f994e0688"
DEFAULT_TUSHARE_HTTP_URL = "http://111.170.140.159:8020/"


def resolve_tushare_token(token: str | None = None) -> str:
    value = str(token or "").strip()
    return value or DEFAULT_TUSHARE_TOKEN


def resolve_tushare_http_url(http_url: str | None = None) -> str:
    value = str(http_url or "").strip()
    return value or DEFAULT_TUSHARE_HTTP_URL


def init_tushare_pro(token: str | None = None, http_url: str | None = None):
    pro = ts.pro_api(resolve_tushare_token(token))
    pro._DataApi__http_url = resolve_tushare_http_url(http_url)
    return pro


def init_tushare_pro_bar(token: str | None = None, http_url: str | None = None, **kwargs):
    pro = init_tushare_pro(token=token, http_url=http_url)
    return ts.pro_bar(api=pro, **kwargs)