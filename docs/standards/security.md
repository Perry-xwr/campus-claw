# 安全开发规范

适用Flask会话/API、SQLite、上传、LangChain/Qdrant及MCP。

|规则|约束|检查|失败判定|
|---|---|---|---|
|SEC-01 默认拒绝|HTML使用Cookie会话；写请求须CSRF；API可使用Bearer；访问前认证、角色和班级授权。MCP `/mcp` 要Bearer，MCP health按实现公开。|匿名、过期/撤销会话、无/错CSRF、Bearer缺失/错误；逐角色调用。|未授权读写或Cookie写可无CSRF即失败。|
|SEC-02 班级隔离|服务端session user/class/role为可信上下文；每个SQL资源访问限定class_id；父子资源一致；跨班和不存在统一404。|A/B交换材料、问题、回复、FAQ、检索chunk、MCP server/skill ID；检查响应和副作用。|跨班泄漏、只在页面隐藏或IDOR即阻断。|
|SEC-03 凭据|SECRET_KEY、种子口令、模型API key、MCP_AUTH_TOKEN只由环境/.env注入；strict部署禁止开发默认值。公开种子账号只限本机演示，不得对外开放。cookie Secure用于HTTPS；令牌不得URL/日志。|全历史秘密扫描、环境样例、启动横幅、容器环境与日志审查。|默认凭据公开部署、真实秘密入Git/镜像/日志即失败；泄漏先轮换。|
|SEC-04 请求防护|Cookie写请求CSRF；Bearer豁免应限于合法Bearer认证；输入类型/长度/枚举检查；SQL占位符绑定；上传扩展名/大小/私有路径验证；检索内容/MCP返回均视为不可信数据。|CSRF伪造、SQL/XSS、路径穿越、伪造工具响应/提示注入。|校验绕过、命令/路径执行、MCP未经白名单调用即失败。|
|SEC-05 隐私与错误|错误只回稳定业务码和安全信息，不回堆栈/路径/密钥；日志不记录cookie/token/API key及完整用户内容。|用非秘密哨兵搜索响应、应用/容器/worker/MCP日志。|哨兵出现即失败；当前日志未形成统一request ID时登记差距。|
|SEC-06 SQLite与存储|启用外键；私有上传不静态暴露；数据目录权限限服务账户；备份与上传/向量版本保持可恢复一致。|检查db.connect、storage路径、Compose挂载及权限；故障恢复演练。|外键关闭、文件可任意读取或删除操作破坏数据一致性即失败。|

部署环境必须设置`CAMPUSCLAW_STRICT_CONFIG=1`和自有强随机SECRET_KEY/种子口令；README公开的内置账号只供本机演示。
