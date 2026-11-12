# 轻量端（H5）与跨源声明 · 第 10 课 · 真实用户与性能验证

> 课件定义：**轻量端**＝手机浏览器直接打开的 H5 页面，**复用同一套接口，不另起后端**。
> 由此异步的 202 + 任务标识、跨班 404、审计七列在前几课做的判据对轻量端自动生效；
> 新的工程量只有两处：页面本身，以及跨源声明。

## 一、做了什么

| 项 | 实现 |
| --- | --- |
| 页面 | `GET /m`（`/m/` 同）→ `campusclaw/templates/h5.html`，单文件、零外部资源、零框架 |
| 接口 | 全部复用桌面端：`POST /api/login`、`GET /api/materials`、`POST /api/submissions`、`GET /api/tasks/<id>`、`GET /api/materials/<id>` |
| 令牌 | 只放页面内存（不写 Cookie、不写 localStorage/sessionStorage），关掉页面即失效 |
| 跨源 | `CORS_ORIGINS` 白名单，空 = 只允许同源；不回显未命中来源；不开 `Allow-Credentials` |
| 入口 | 手机与电脑同一地址：`http://<本机局域网 IP>:8110/m` |

页面按课件的四步演示组织：**登录取令牌 → 提交作业 202 → 轮询 pending/running/succeeded →
换别班账号查别班讲义 404**，每一步的结果实时打到「操作记录」里，不靠打开开发者工具确认。

## 二、四步走查（命令行实测，不经过浏览器）

轻量端复用的是同一套接口，所以「四步能不能走完」可以在命令行验证——
页面只是这四步的界面。脚本：`scripts/h5_walkthrough.py`。

```
$ python scripts/h5_walkthrough.py --base http://127.0.0.1:8110

  1) 登录 student_a1: HTTP 200
  2) 材料列表: HTTP 200，1 份
  3) 提交作业: HTTP 202，task_id=task_a0553b27426f1f71，响应含分数=False
  4) 轮询: HTTP 200，状态 pending
  4) 轮询: HTTP 200，状态 running
  4) 轮询: HTTP 200，状态 running
  4) 轮询: HTTP 200，状态 running
  4) 轮询: HTTP 200，状态 succeeded
  1) 登录 student_b1: HTTP 200
  5) 别班账号取材料 1: HTTP 404，响应={"error": {"code": "MATERIAL_NOT_FOUND", "message": "材料不存在"}}

四步全部符合预期（登录 → 202 → 轮询到 succeeded → 跨班 404）
```

三个细节值得记下来：

* **202 的响应体里没有分数**（脚本专门断言 `score` 不出现）。异步契约在轻量端同样成立：
  提交只承诺「已接收」。
* **轮询真能看到三态**：`pending → running → succeeded`。这需要消费者在跑
  （`python -m campusclaw.task_worker --delay-ms 3000`），否则会一直停在 `pending`——
  第一次走查就卡在这里，原因是没启动消费者，不是页面有问题。
* **跨班 404 的响应体里没有本班标题**（脚本对标题做了子串检查）。状态码对、内容泄露
  同样是失败，所以两条都断言。

## 三、跨源声明（实测响应头）

轻量端由本服务渲染时是同源，不需要 CORS；把页面放到别的静态站、接口仍在这台机器时才需要。
默认配置为空 = **不产生任何 CORS 响应头**，与浏览器「不声明就不放行」的默认行为一致。

设置 `CORS_ORIGINS=http://127.0.0.1:9000` 后实测：

| 请求 | 实测响应头 |
| --- | --- |
| `GET /api/materials`，`Origin: http://127.0.0.1:9000`（白名单内） | `Access-Control-Allow-Origin: http://127.0.0.1:9000`、`Vary: Origin` |
| `GET /api/materials`，`Origin: http://evil.example`（白名单外） | **无** `Access-Control-Allow-Origin` |
| `OPTIONS /api/submissions` 预检，白名单内 | `Allow-Origin` 回显、`Allow-Headers: Authorization, Content-Type, Accept, X-Requested-With`、`Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS`、`Max-Age: 600` |

三条刻意的取舍：

1. **不用 `*`**：允许任意来源等于把接口交给互联网上任何一个网页，令牌被用户带过去就等于泄露。
2. **不放开凭据**：轻量端用 `Authorization` 头带令牌、不用 Cookie，所以
   `Access-Control-Allow-Credentials` 保持关闭——少一条被跨站利用的路。
3. **`Vary: Origin`**：不同来源的响应不能共用缓存条目，否则 A 站会拿到 B 站的头。

## 四、页面渲染的验证边界（不夸大）

已经做的：

* `GET /m` → 200，页面含登录、材料、提交、跨班校验四个区块与操作记录区；
* 页面脚本用 `node --check` 过语法；再用假 canvas 在 node 里跑一遍面板同款绘图逻辑
  （见 `reports/observe-alert.md`），确认没有运行期异常；
* 四步走查在命令行全绿，与页面调用的是同一组接口。

**没有做的**：没有在真机或浏览器里截图，也没做 iOS Safari / Android Chrome 的兼容测试。
所以「手机上长什么样、16px 输入框会不会触发缩放」这类问题，只有在真机上打开才能算验证过。
这一条与「真实用户 ≥3 人」绑在一起，属于外部条件，不写成已通过。

在手机上打开的方式（同一 Wi-Fi）：

```bash
# 1) 起服务（监听 0.0.0.0，日志里会打印局域网地址）
python scripts/serve_waitress.py --port 8110 --seconds 900
# 2) 手机浏览器打开
#    http://<本机局域网 IP>:8110/m
```

## 五、判定

| 课件要求 | 实际 | 判定 |
| --- | --- | --- |
| 手机浏览器打开的 H5 页面 | `/m` 单文件页面，零外部资源 | 已实现 |
| 复用同一套接口、不另起后端 | 五个接口全部复用，无新后端、无新契约 | 达标 |
| 四步演示（登录 → 202 → 轮询三态 → 跨班 404） | 命令行实测全绿，含「响应体不含分数」「404 不含标题」两条负向断言 | 达标（命令行口径） |
| 跨源声明 | 白名单命中回显、未命中不回显、预检头齐全、不开凭据 | 达标 |
| 真机体验 | 未截图、未做机型兼容测试 | **未验证** |

一句话：**接口层面轻量端已经能和桌面端走同一套判据；页面层面还差一次真机打开。**
