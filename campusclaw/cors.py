"""第 10 课「轻量端」：跨源声明（CORS）。

轻量端是手机浏览器直接打开的 H5 页面。页面通常就由本服务渲染（同源），但课件
要求「页面与接口不同源时服务端要明确声明允许」——把页面放到别的静态站、接口
仍在这台机器上，是最常见的部署形态，那时浏览器会拦下所有响应。

三条纪律：

* **白名单，不是 ``*``**：允许任意来源等于把接口交给互联网上任何一个网页，
  令牌一旦被用户带过去就等于泄露。这里只回显命中白名单的 ``Origin``。
* **不放开凭据**：轻量端用 ``Authorization: Bearer`` 带令牌，不使用 Cookie，
  因此 ``Allow-Credentials`` 保持关闭——少一条被跨站利用的路。
* **预检只放行需要的头**：``Authorization`` 与 ``Content-Type`` 够用，
  ``Max-Age`` 减少 OPTIONS 往返次数。

默认 ``CORS_ORIGINS`` 为空 = 只允许同源，也就是「不声明就不放行」，
与浏览器的默认行为一致，不会因为加了这段代码就悄悄放宽。
"""

from __future__ import annotations

from flask import Flask, Response, request

#: 预检放行的请求头。少一个都会让浏览器在真实请求前失败，故一次性列全。
ALLOW_HEADERS = "Authorization, Content-Type, Accept, X-Requested-With"
ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
PREFLIGHT_MAX_AGE = "600"


def register_cors(app: Flask, origins: tuple[str, ...]) -> None:
    """按白名单回显跨源头；未配置时不产生任何 CORS 响应头。"""
    allowed = {item.rstrip("/") for item in origins or () if item.strip()}

    @app.after_request
    def _cors_headers(response: Response) -> Response:
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if not origin or origin not in allowed:
            return response
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = ALLOW_HEADERS
        response.headers["Access-Control-Allow-Methods"] = ALLOW_METHODS
        response.headers["Access-Control-Max-Age"] = PREFLIGHT_MAX_AGE
        # 不同 Origin 的响应不能共用一个缓存条目，否则 A 站会拿到 B 站的头。
        existing = response.headers.get("Vary")
        response.headers["Vary"] = f"{existing}, Origin" if existing else "Origin"
        return response
