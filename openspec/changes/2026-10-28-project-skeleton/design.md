## Context
本工作区未见Git仓库；远程小组仓库状态未核验。本设计为L7骨架，不能依赖旧项目运行状态。所有业务契约仅预留port边界，不实现空壳业务API。

## Goals / Non-Goals
目标：SK-01…SK-10可在独立机器复现；非目标：docs/requirements的P1/P2/P3业务。本课采用最小前后端状态页，不承担身份系统。

## Decisions
1. 建议Go net/http + React/TS + MySQL。复用已有经验，避免新增框架负担；备选全TS会减少语言数量但迁移经验有成本。具体Go/Node/MySQL版本、依赖锁、镜像digest、Docker/Compose最低版本在docs/lesson-07/team-handoff.md登记后冻结，不声称本包已固定运行环境。
2. handler→application→domain/ports，adapter实现port，cmd装配；弃用handler直查SQL，便于隔离测试和未来授权复用。推荐目录 cmd/api/main.go、internal/transport/http、application、domain、ports、adapters/mysql、adapters/rag、config，web/src、tests/integration、deploy、scripts；不为凑分层创造空业务实现。
3. MySQL必需，RAG可选。health是存活，ready只取决于MySQL；rag即使remote失败仍不影响核心就绪，但状态必须down。免认证探针不暴露拓扑；运维诊断独立Bearer令牌（32字符以上，常量时间比较）。拒绝复用教师登录来完成骨架权限测试，避免引入业务身份范围。
4. 配置格式错误即启动失败；格式合法但依赖暂时不通允许监听并返回ready503，以便观察恢复。探针实时并行检查、单依赖1秒，总2秒；MySQL实际SELECT 1。remote RAG仅实现供应方确认的健康适配器，不执行问答；没有供应方契约时保持disabled。

## Contracts
统一响应契约：`{"code":"OK","message":"成功","data":{},"request_id":"..."}`，Content-Type为application/json；成功HTTP200，常规错误data=null，request_id与X-Request-ID一致。错误映射：400/VALIDATION_ERROR（参数非法）、401/AUTH_REQUIRED（诊断权限凭据缺失或错误）、404/NOT_FOUND（资源不存在）、405/METHOD_NOT_ALLOWED（错误方法）、500/INTERNAL_ERROR（未处理异常）、503/DEPENDENCY_UNAVAILABLE（依赖不可达）。未知路由固定message=资源不存在；诊断依赖故障message=依赖不可用；其余message给简短中文错误原因且不含敏感值。业务角色403属于未来业务规约，本课没有学生/教师鉴权接口，不能虚构它来测试。

响应见本文下方统一响应契约，health/ready data={version,time,status,dependencies:{mysql:up|down,rag:up|down|not_configured}}。ready503是唯一保留诊断data的错误响应例外。public探针和内部诊断不提供数据库名称、主机、异常堆栈。
APP_ENV枚举development/test/production；HTTP_PORT整数1..65535；APP_VERSION非空、最大64字符；MYSQL_DSN可解析且含库名；OPS_TOKEN>=32字符且非示例占位；RAG_MODE=disabled|remote。remote要求HTTPS RAG_BASE_URL和非空RAG_SERVICE_TOKEN，开发仅允许显式localhost HTTP。配置解析先于连接和listen；Compose MYSQL_PASSWORD只用于本地数据库初始化，也必须非空不为占位。
GET /health,/ready不接受query；未知query400。internal diagnostics只允许一个dependency参数。所有响应application/json，web经同源代理展示，后端404不被SPA吞掉。日志完成事件与响应共用request ID，启动日志request_id=null而不是伪造HTTP请求。
`GET /internal/diagnostics?dependency=mysql|rag`先验证令牌再校验参数，未获运维权限返回401且不探测；有效令牌查询mysql成功返回data={dependency:"mysql",status:"up",checked_at:<UTC>}，失败503；查询disabled rag返回200/status=not_configured。此入口用于真实单依赖诊断，权限失败场景测试拒绝未授权运维操作，不提前引入业务身份。前端状态页仅调用公开探针，OPS_TOKEN不进入浏览器代码。

L7冻结为disabled RAG，remote配置仅保留未来扩展边界；remote若被选择而尚无已验收健康适配器，应启动失败CONFIG_UNSUPPORTED_MODE，不允许无依据报up。缺remote必需项优先报CONFIG_INVALID。新环境验收统一使用disabled，不要求组员本课实现外部RAG。

前端根路径由web服务提供；未知前端路径显示404页。后端未知路径返回JSON404；web对/api、/internal、/health、/ready及其子路径转发到api，不得fallback成SPA成功页。spec中对后端未知路径的测试从Compose内部或本地api监听端口执行。

## Deployment and Lifecycle
Compose服务web/api/mysql，test仅profile启用；宿主仅web映射8080，反代探针与/internal路径；api/mysql留内部网络。开发本地可直接api端口。使用.env注入变量、.dockerignore排除.env/.git/reports，构建不复制凭据。web运行镜像仅静态产物；api多阶段仅二进制/证书；mysql官方镜像固定digest。APP_VERSION按commit SHA构建，验收后tag不改变已验证二进制。
SIGTERM后ready立即503，最多10秒排空在途请求，之后退出；容器stop_grace_period≥15秒。启动探针可重试至120秒，超时判验收失败。Compose停止默认down，不带-v，避免删开发数据。

## Risks / Migration
无业务迁移；只准备独立测试数据库，不导入旧库。remote服务实际契约/工具链版本为阻塞业务接入项。规则文件存在不证明Harness生效，需独立会话注入测试。运维令牌是过渡实现，生产运维身份未来另提change。

## Validation
每个SK映射spec场景与tasks中列出的Scenario对应测试。strict命令先核对版本/帮助；参数、权限、缺失资源、依赖故障对应SC-SK-04-03、SC-SK-04-02、SC-SK-05-01、SC-SK-03-02。所有工程验证当前NOT_RUN。
