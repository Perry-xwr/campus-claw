# 后端开发规范（Python / Flask / SQLite）

适用当前`app.py`、`campusclaw/`和`mcp-server/`。规则继承业务需求；API具体错误码可适配现有`campusclaw/errors.py`，不得改变业务语义。

|规则|约束|检查|失败判定|
|---|---|---|---|
|BE-01 分层|`app.py`负责创建/启动与配置装配；`campusclaw/views/`负责Flask路由、协议校验和响应；`campusclaw/`业务模块负责规则及数据访问；`templates/`负责呈现；MCP独立服务。保持导入方向清晰，不强制引入Go式ports/adapter目录。|检查蓝图注册、模块import和SQL所在位置；搜索views中的SQL与业务重复实现。|路由跨模块复制核心状态规则、模板承担授权、MCP绕过主应用鉴权即失败；移入现有职责模块。|
|BE-02 响应与异常|保留`ApiError`统一JSON错误处理和HTTP状态；成功JSON/API、HTML页面、SSE各遵协议。未知/跨班资源不得因全局异常处理变成200或泄漏存在性。request_id若当前未实现，列缺口，不假定已有。|用Flask test client覆盖成功、ApiError、404/405、意外异常、SSE断开；检查错误处理器。|异常堆栈/密钥回传、错误变成功、跨班响应可区分即失败。|
|BE-03 输入边界|请求体要求正确JSON类型；整数/ID拒绝非法值、bool冒充整数和越界；筛选值使用白名单，非法值显式400；文本按需求长度和空白规则校验。查询参数不能静默回落到宽范围。|检视各`*_views.py`解析帮助函数，对每个筛选做非法值测试并检查DB副作用。|非法筛选被忽略、超限被接受或未知字段覆盖权限即失败。|
|BE-04 配置|由`campusclaw/config.py`集中解析环境和根目录`.env`；开发模式可用显式dev defaults；部署必须`CAMPUSCLAW_STRICT_CONFIG=1`并提供SECRET_KEY及所有SEED口令。模型/嵌入三元组全配才启用，缺配置的降级按README。|比较.env.example与config解析；strict模式逐项缺值启动检查，不记录值。|线上或公开演示仍用公开口令/开发密钥即严重失败；启动横幅泄漏自定义口令即失败。|
|BE-05 SQLite事务|连接启用外键和busy_timeout；写事务使用`db.transaction`/`BEGIN IMMEDIATE`或模块等价明确commit/rollback。事务内不调用Qdrant、LangChain网络或MCP。使用SQL参数绑定；动态表名只能来自代码常量白名单。|检查提交/回滚路径、外键、参数绑定；在DB锁竞争和提交异常场景做集成验证。|半提交、吞掉回滚错误后报成功、事务持锁期间外呼即失败；修复后加回归。|
|BE-06 幂等与并发|按需求实现防重复和版本冲突。SQLite单写者及busy_timeout不是业务幂等，也不自动满足并发冲突要求。实现可用唯一约束、条件更新或事务比较；不强制引入额外框架。|重复FAQ/转人工/写请求；双会话基于同一版本采纳、关闭、更新；断言状态和副作用。|重复副作用、静默覆盖或以500掩盖冲突即失败。|
|BE-07 文件与边界|上传路径由服务端storage_key生成，目录私有；路径解析后必须在UPLOAD_DIR内。Flask蓝图只登记对应能力路由，限流/文件大小与错误行为沿用需求。|路径穿越、超限、删除失败恢复测试；检查配置路径与实际文件权限。|用户可控制任意文件路径、上传通过静态目录公开即失败。|

检查命令/运行入口参考`docs/IMPLEMENTATION.md`和testing规范；不虚构`go list`或未存在的check脚本。
