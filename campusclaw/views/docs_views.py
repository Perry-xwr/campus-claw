"""接口文档路由：/openapi.json 与 /swagger/index.html。"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, render_template_string

from campusclaw.openapi import openapi_document

bp = Blueprint("docs", __name__)

_SWAGGER_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CampusClaw API · Swagger UI</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📘</text></svg>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>
  :root{--brand:#4a3f8f;--accent:#0f7b7d;--bg:#f4f5f9;--surface:#fff;--border:#e4e6ee;--text:#1a1d29;--text-2:#555b6e}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
  .topbar{position:sticky;top:0;z-index:10;background:var(--surface);border-bottom:1px solid var(--border);
          display:flex;align-items:center;gap:14px;padding:10px 22px}
  .logo{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#5f53a8,#372e6d);
        display:flex;align-items:center;justify-content:center;font-size:16px}
  .topbar strong{font-size:15px}
  .topbar span{color:var(--text-2);font-size:12.5px}
  .topbar a{margin-left:auto;color:var(--brand);font-size:13px;font-weight:600;text-decoration:none}
  #swagger-ui{max-width:1180px;margin:0 auto;padding:18px}
  .fallback{display:none;margin:40px auto;max-width:640px;background:var(--surface);border:1px solid var(--border);
            border-radius:12px;padding:26px 30px}
  .fallback h2{margin:0 0 8px;font-size:18px}
  .fallback p{margin:6px 0;color:var(--text-2)}
  .fallback code{background:#eef0f6;border-radius:5px;padding:2px 7px;font-size:13px}
</style>
</head>
<body>
<header class="topbar">
  <div class="logo">📘</div>
  <div><strong>CampusClaw API</strong><br><span>OpenAPI 3 · Bearer 令牌认证</span></div>
  <a href="/openapi.json" target="_blank" rel="noopener">openapi.json ↗</a>
</header>
<div id="swagger-ui"></div>
<div class="fallback" id="fallback">
  <h2>Swagger UI 资源未能加载</h2>
  <p>当前网络无法访问 CDN（cdn.jsdelivr.net）。你仍然可以：</p>
  <p>· 直接打开 <code>/openapi.json</code> 查看完整接口描述；</p>
  <p>· 用 <code>curl</code> 或任意 HTTP 客户端试调接口；</p>
  <p>· 联网后刷新本页即可恢复交互式文档。</p>
</div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js" onerror="document.getElementById('fallback').style.display='block'"></script>
<script>
window.addEventListener('load', function () {
  if (!window.SwaggerUIBundle) {
    document.getElementById('fallback').style.display = 'block';
    return;
  }
  window.ui = SwaggerUIBundle({
    url: '/openapi.json',
    dom_id: '#swagger-ui',
    deepLinking: true,
    persistAuthorization: true,
    tryItOutEnabled: true,
    layout: 'BaseLayout'
  });
});
</script>
</body>
</html>
"""


@bp.get("/openapi.json")
def openapi_json():
    return jsonify(openapi_document()), 200


@bp.get("/swagger/index.html")
def swagger_page():
    return Response(_SWAGGER_PAGE, mimetype="text/html; charset=utf-8"), 200
