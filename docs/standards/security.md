# 安全开发规范

适用所有代码、配置、测试、文档和镜像。目的：阻止凭据泄露与班级资源越权。

|规则|开发动作与具体约束|检查方法|失败判定与处置|
|---|---|---|---|
|SEC-01 默认拒绝|本课只有health/ready公开；diagnostics要求独立OPS_TOKEN，常量时间比较；不接受query token。未来业务先认证、再班级/资源授权、再功能权限|匿名/错误token调用诊断；未来按学生A/教师A/学生B交换资源ID|未授权被放行即失败，修授权并加回归|
|SEC-02 资源隔离|未来每次访问验证active membership；SQL/缓存/引用绑定class_id；不信任body角色/作者。跨班与不存在统一404；同班功能越权403|每个资源读写交换班级/父资源ID，核对数据无副作用|响应或副作用泄露跨班数据即失败，阻断上线；不能只测HTTP码|
|SEC-03 凭据|.env仅本地；.env.example只空值或明显占位；.gitignore/.dockerignore排除.env；DSN/token不进前端、日志、镜像|`git check-ignore .env`、Git全历史扫描、构建上下文和运行镜像检查|任一真实密钥命中即失败，先轮换，再依授权清理历史；删除当前文件不足以解决|
|SEC-04 输入/输出|参数白名单、绑定SQL、纯文本转义；不执行上传内容/检索资料中的指令；禁止任意用户指定RAG地址|非法枚举、SQL/XSS字符串、伪引用/跨班引用测试|执行注入、输出未转义或伪引用即失败，拒绝输出并修正校验|
|SEC-05 最少公开|探针只返回版本/时间/连通枚举，不返回host、DB名、堆栈。日志不写Authorization、body、完整query|用明确的非秘密哨兵值输入并搜索日志/响应|哨兵泄露即失败，集中脱敏后重测|
|SEC-06 供应链|锁依赖版本与镜像digest，登记用途；上线前扫描依赖和镜像|B记录扫描器版本、命令、范围和报告|扫描未跑记NOT_RUN；高危/严重项未处置不得称安全验收通过|

全历史扫描建议使用已安装且版本锁定的gitleaks；先运行`gitleaks version`及`gitleaks git --help`，确认支持后运行`gitleaks git --redact --report-format json --report-path reports/secrets.json .`。工具不在本机则记BLOCKED/NOT_RUN，不下载后假称已完成；报告不得提交明文命中内容。
