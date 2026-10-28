# Skeleton

## ADDED Requirements

下列 SHALL 为本组拟定可执行基线；技术与数值为建议默认值，待确认后冻结。
### Requirement: SK-01 分层与最小入口
系统 SHALL 提供 cmd/api、internal/{transport,application,domain,ports,adapters,config} 及 web 最小状态页。domain/ports 不导入 transport/adapters，业务入口只到 application。L7 不注册业务 API。

#### Scenario: SC-SK-01-01
- **GIVEN** （前置条件）新克隆且配置有效。
- **WHEN** （操作）构建后访问根页面。
- **THEN** （可观测结果）HTTP200，页面显示项目名/版本/服务状态；未知页面显示可返回首页的404页。

#### Scenario: SC-SK-01-02
- **GIVEN** （前置条件）编译目录和依赖图可检查。
- **WHEN** （操作）执行分层检查并访问 /api/v1/classes/demo/questions。
- **THEN** （可观测结果）无反向依赖，业务路由HTTP404/NOT_FOUND；不返回虚构业务数据。

### Requirement: SK-02 外置配置与失败启动
系统 SHALL 从环境读取 APP_ENV、APP_VERSION、HTTP_PORT、MYSQL_DSN、OPS_TOKEN、RAG_MODE。必需配置缺失或非法必须先报错再退出，不打开监听端口。

#### Scenario: SC-SK-02-01
- **GIVEN** （前置条件）七个必需项合法，RAG_MODE=disabled。
- **WHEN** （操作）启动应用。
- **THEN** （可观测结果）进程开始监听；日志不含DSN/令牌；配置不写入前端。

#### Scenario: SC-SK-02-02
- **GIVEN** （前置条件）依次删除任一必需项，或 HTTP_PORT=0/65536，APP_ENV=oops、RAG_MODE=oops、OPS_TOKEN不足32字符。
- **WHEN** （操作）逐项启动。
- **THEN** （可观测结果）每项进程在5秒内非零退出，单行JSON含CONFIG_INVALID与字段名但无值，端口未监听。

#### Scenario: SC-SK-02-03
- **GIVEN** （前置条件）RAG_MODE=remote但RAG_BASE_URL或RAG_SERVICE_TOKEN缺失。
- **WHEN** （操作）启动。
- **THEN** （可观测结果）5秒内非零退出；disabled时两项无需配置。

### Requirement: SK-03 公开健康与就绪
系统 SHALL 提供免认证 GET /health 与 GET /ready。health 表示存活，ready 表示必需依赖就绪；两者均含版本、UTC时间、依赖枚举，无敏感连接信息。

#### Scenario: SC-SK-03-01
- **GIVEN** （前置条件）应用已启动，MySQL通，RAG_MODE=disabled；匿名。
- **WHEN** （操作）GET /health 和 /ready。
- **THEN** （可观测结果）均200/OK；data含version、time、status、dependencies.mysql=up、dependencies.rag=not_configured；health.status=alive，ready.status=ready。

#### Scenario: SC-SK-03-02
- **GIVEN** （前置条件）MySQL停止或网络拒绝；匿名。
- **WHEN** （操作）GET两探针。
- **THEN** （可观测结果）health200/OK且alive/mysql=down；ready503/DEPENDENCY_UNAVAILABLE，data含version/time/status=not_ready/dependencies；这是统一错误data=null的探针专用例外。

#### Scenario: SC-SK-03-03
- **GIVEN** （前置条件）MySQL端口可连但凭据无效。
- **WHEN** （操作）GET /ready。
- **THEN** （可观测结果）真实SELECT 1失败，mysql=down和503，不能仅以TCP端口打开判断up。

#### Scenario: SC-SK-03-04
- **GIVEN** （前置条件）依赖检查可能阻塞。
- **WHEN** （操作）发出探针请求。
- **THEN** （可观测结果）每个依赖超时1秒，并行检查总响应<=2秒；不返回host、DB名、堆栈或token。

### Requirement: SK-04 受保护的依赖诊断
系统 SHALL 提供真实运维接口 GET /internal/diagnostics?dependency=mysql|rag，用于诊断单一依赖状态；只接受 Authorization: Bearer OPS_TOKEN，禁止URL令牌。

#### Scenario: SC-SK-04-01
- **GIVEN** （前置条件）有效OPS_TOKEN，dependency=mysql且MySQL可用。
- **WHEN** （操作）调用诊断。
- **THEN** （可观测结果）200/OK，data={dependency:mysql,status:up,checked_at:<UTC>}，无连接串。

#### Scenario: SC-SK-04-02
- **GIVEN** （前置条件）缺少或错误令牌。
- **WHEN** （操作）调用诊断。
- **THEN** （可观测结果）401/AUTH_REQUIRED，data=null，不执行依赖探测；响应与日志不回显令牌。

#### Scenario: SC-SK-04-03
- **GIVEN** （前置条件）有效令牌但dependency缺失、重复或为redis，或额外未知参数。
- **WHEN** （操作）调用诊断。
- **THEN** （可观测结果）400/VALIDATION_ERROR，不忽略筛选。

#### Scenario: SC-SK-04-04
- **GIVEN** （前置条件）有效令牌，dependency=rag且disabled。
- **WHEN** （操作）调用诊断。
- **THEN** （可观测结果）200/OK，status=not_configured，不伪称up也不连接旧服务。

#### Scenario: SC-SK-04-05
- **GIVEN** （前置条件）有效令牌，dependency=mysql但依赖不可达。
- **WHEN** （操作）调用诊断。
- **THEN** （可观测结果）503/DEPENDENCY_UNAVAILABLE，data=null，message=依赖不可用。

### Requirement: SK-05 统一错误和路由边界
系统 SHALL 统一JSON响应和错误码；API未知路由不可被SPA回退吞掉。

#### Scenario: SC-SK-05-01
- **GIVEN** （前置条件）服务启动；匿名。
- **WHEN** （操作）GET /does-not-exist 或 /api/v1/missing。
- **THEN** （可观测结果）404/NOT_FOUND/message=资源不存在/data=null且有request_id；后端不返回HTML。

#### Scenario: SC-SK-05-02
- **GIVEN** （前置条件）服务启动；匿名。
- **WHEN** （操作）POST /health。
- **THEN** （可观测结果）405/METHOD_NOT_ALLOWED，Allow含GET，统一JSON错误。

#### Scenario: SC-SK-05-03
- **GIVEN** （前置条件）故障注入使handler panic，仅测试构建。
- **WHEN** （操作）请求被注入处理器。
- **THEN** （可观测结果）500/INTERNAL_ERROR，进程仍存活，响应无堆栈；测试专用处理器不进生产路由。

### Requirement: SK-06 request ID 与结构化日志
系统 SHALL 为每个请求返回 X-Request-ID 并写单行JSON完成日志，字段time/level/module/request_id/method/path/status/duration_ms齐全。

#### Scenario: SC-SK-06-01
- **GIVEN** （前置条件）客户端未传ID或传入非法字符/长度65。
- **WHEN** （操作）请求health。
- **THEN** （可观测结果）生成UUID，header/body/log的request_id一致；非法输入不拼入日志。

#### Scenario: SC-SK-06-02
- **GIVEN** （前置条件）X-Request-ID符合[A-Za-z0-9_-]{1,64}。
- **WHEN** （操作）请求health。
- **THEN** （可观测结果）沿用ID贯穿响应及依赖调用，日志每行可JSON解析；duration_ms非负。

#### Scenario: SC-SK-06-03
- **GIVEN** （前置条件）Authorization/DSN/含token的query出现在请求环境。
- **WHEN** （操作）触发诊断失败并检查日志。
- **THEN** （可观测结果）无token、DSN、body和完整query；path只记路由模板或脱敏路径，未知路由只记UNMATCHED。

### Requirement: SK-07 Compose 可复现启动
系统 SHALL 交付锁版本多阶段Dockerfile、Compose与安全.env.example；web/api/mysql/test服务隔离，默认启动不依赖外部RAG。

#### Scenario: SC-SK-07-01
- **GIVEN** （前置条件）安装已登记Docker/Compose版本，新clone后填本地.env。
- **WHEN** （操作）docker compose up --build -d。
- **THEN** （可观测结果）120秒内web可访问，health200、ready200；镜像含APP_VERSION，无latest标签；mysql不暴露宿主端口。

#### Scenario: SC-SK-07-02
- **GIVEN** （前置条件）缺MYSQL_DSN或OPS_TOKEN。
- **WHEN** （操作）运行同启动命令。
- **THEN** （可观测结果）Compose变量检查或应用启动明确失败，不进入假健康状态；记录退出/服务状态。

#### Scenario: SC-SK-07-03
- **GIVEN** （前置条件）新环境无旧CampusClaw容器和Qdrant。
- **WHEN** （操作）执行启动。
- **THEN** （可观测结果）骨架可运行，rag=not_configured；容器非root运行（mysql使用官方支持用户），运行镜像无源码和.env。

### Requirement: SK-08 一键自动验收与隔离
系统 SHALL 提供 python scripts/check.py --suite skeleton，串行汇总格式/静态检查、单测、容器集成与追溯检查，任一子项失败非零退出。

#### Scenario: SC-SK-08-01
- **GIVEN** （前置条件）工具版本已登记且隔离测试环境配置齐全。
- **WHEN** （操作）运行一键命令。
- **THEN** （可观测结果）覆盖本spec全部自动场景，输出reports/skeleton/summary.json和junit.xml，含各T编号、结果、耗时；人工项保持NOT_RUN。

#### Scenario: SC-SK-08-02
- **GIVEN** （前置条件）人为破坏ready状态码或request ID传递。
- **WHEN** （操作）运行测试后恢复改动。
- **THEN** （可观测结果）对应测试失败且总退出码非零；不得通过删断言或skip使结果变绿。

#### Scenario: SC-SK-08-03
- **GIVEN** （前置条件）两次测试以不同run_id运行，单测网络禁用。
- **WHEN** （操作）运行测试。
- **THEN** （可观测结果）单测可离线完成，DB名/Compose项目独立，清理仅本次run资源，无生产/开发数据删除。

### Requirement: SK-09 README 与独立复现
团队 SHALL 在README登记前置工具、.env填写、启动、探针、测试、停止和故障定位；另一成员从独立clone复现。

#### Scenario: SC-SK-09-01
- **GIVEN** （前置条件）成员B无历史聊天，只拿仓库地址和change名。
- **WHEN** （操作）按README启动并运行测试。
- **THEN** （可观测结果）无需口头补步骤；记录commit、OS、工具版本、命令、退出码及证据，问题按真实FAIL/BLOCKED记录。

#### Scenario: SC-SK-09-02
- **GIVEN** （前置条件）缺配置或ready503。
- **WHEN** （操作）按README故障章节处理。
- **THEN** （可观测结果）能区分字段缺失与依赖不可达；指导查request_id，不要求公开.env。

### Requirement: SK-10 规则入口与交付门禁
团队 SHALL 提供AGENTS与五类规则索引、strict验证记录及交叉评审；验收后归档并打骨架标签。

#### Scenario: SC-SK-10-01
- **GIVEN** （前置条件）新Harness会话，仅给路径/change名。
- **WHEN** （操作）要求列当前范围及相关规则后执行骨架任务。
- **THEN** （可观测结果）读取AGENTS和相应标准，列SK编号，不生成五模块业务代码；不能以文件存在代替生效。

#### Scenario: SC-SK-10-02
- **GIVEN** （前置条件）候选PR故意含业务层SQL、明文密钥样本占位、无空态页面或无request_id日志。
- **WHEN** （操作）执行规范符合性审查。
- **THEN** （可观测结果）分别指出BE/SEC/PRD/OPS规则，测试缺场景指出TST；测试样本不得使用真实密钥，违规改动不合并。

#### Scenario: SC-SK-10-03
- **GIVEN** （前置条件）全部证据通过且交叉评审同意。
- **WHEN** （操作）执行归档并创建v0.0.1-skeleton。
- **THEN** （可观测结果）归档规约与实际commit一致，tag可解析到验收提交；未运行或有失败不得打完成标签。

#### Scenario: SC-SK-10-04
- **GIVEN** 已安装且记录版本的OpenSpec，四份文件齐全，已核对本版本validate帮助。
- **WHEN** 执行该版本支持的change严格校验命令并保留原始输出。
- **THEN** 退出码为0才记录strict通过；未运行记NOT_RUN，非零记FAIL，不以文档静态检查代替。
