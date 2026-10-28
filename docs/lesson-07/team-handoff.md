# 第7课团队交接

正式交付根目录：`E:\campus-claw`。个人旧项目`E:\CampusClaw`不得修改。现有build_spec_pack.py和子目录phase-a保留作历史草稿，不再运行全量生成。当前仅文档交付，无业务代码、无已运行骨架、无Git写操作。

## 1. 阅读顺序与三人分工

先读AGENTS.md→project-requirements.md→本change proposal/design/spec/tasks→对应五类标准→验收清单。功能说明是产品方向，只有本change列入第7课apply。

|责任人|需要完成/维护的文件|执行与验收|
|---|---|---|
|组长|功能说明、OpenSpec四文件、AGENTS、五类标准、验收口径|组织技术栈/版本/探针决策确认；建立独立仓库并先保护main；核对strict；审查范围和证据。当前文档已生成，团队批准TODO|
|组员A|cmd/api、internal分层、web状态页、go.mod/go.sum、前端锁文件、Dockerfile、compose.yaml、.dockerignore、.env.example、README及.gitignore|按tasks 1.1–1.6实现；不得创建五模块业务代码。证明启动、配置失败、探针/诊断、JSON日志、Compose可运行。自测后交B复核|
|组员B|tests、scripts/check.py、测试fixture、reports/skeleton报告；docs/lesson-07/verification-record.md；参与README及必要实现|按tasks 2.1–2.3、3.1–3.3编写和执行测试；独立机器clone启动；审A代码。A交叉审B测试，组长核对需求口径|

## 2. 开始开发前

1. 组长创建**独立小组仓库**，给教师访问权限，先设置main保护/ruleset。若空仓库平台不能保护不存在的分支，记录阻塞并请教师确认替代步骤，不声称满足“先保护”。
2. 首次提交仅README.md、.gitignore和可选LICENSE。README此时说明定位及骨架待实现状态，不编造可运行命令；实现后补齐实际启动步骤。本包在首次提交之后导入，不能整包首次提交。
3. 三人确认推荐Go/React/TS/MySQL、默认RAG disabled及受保护运维诊断。A在README填写实际Go/Node/npm/MySQL/Docker/Compose/Python版本、锁文件和基础镜像digest。当前版本冻结状态TODO，未给出未经验证的版本组合。
4. 组长确认规约；按本机真实OpenSpec入口完成propose及strict，再执行骨架tasks。B可先按Scenario设计测试，不需等待业务代码。

## 3. OpenSpec真实工具核对

本机已检查PATH，未发现`openspec`命令；strict为**NOT_RUN**。本轮不自动安装CLI，不把静态格式审查当作strict。

在组员安装的工具环境先执行并保留输出：

```text
openspec --version
openspec --help
openspec init --help
openspec validate --help
```

在新仓库初始化前备份本包四文件，核对帮助中的Codex工具标识后使用 `openspec init --tools codex`（仅当该版本支持）。不要让初始化覆盖规约或AGENTS。若帮助确认支持change名和strict，执行：

```text
openspec validate 2026-10-28-project-skeleton --strict
```

若CLI需要`--type change`等参数，使用实际help定义的等价形式并记录。目标是严格模式真实退出0；未支持或命令失败应修正/报告，不使用普通模式冒充strict。

课程要求保留四步语义：`/opsx-propose`→`/opsx-validate ... --strict`→`/opsx-apply`→`/opsx-archive`。当前官方说明的命名因Harness而异，Codex可能使用`$openspec-propose`；以init生成入口为准。代理verify不自动等于CLI strict。课件validate入口不存在时，记录命令差异、执行真实CLI严格校验，并让组长确认课程对应关系。见[OpenSpec官方仓库说明](https://github.com/Fission-AI/OpenSpec)。

归档和tag只有真实验收完成后才做，且由组长按授权操作；本轮不执行。不要为勾完tasks提前归档。

## 4. A/B统一验收入口

以下是**实现契约，不是当前可执行成品**：

```text
docker compose up --build -d
curl.exe http://localhost:8080/health
curl.exe http://localhost:8080/ready
python scripts/check.py --suite skeleton
docker compose down
```

Linux/macOS使用curl。配置前先从.env.example复制到本地.env，填写design列出的必需值；A负责使README无需口头补充。B先隔离Compose项目和DB，再模拟MySQL断连、配置缺失、非法参数、无令牌诊断及未知路由。令牌只在本机注入，不写到报告命令行。summary记录每个T编号，规则为`SC-SK-xx-yy`映射`T-SK-xx-yy`。所有尚未执行项保持NOT_RUN。

新Harness会话只给仓库路径及change名，要求列当前任务/规则来源，按tasks完成一个已授权骨架任务；另以不含真实密钥的临时违规样本检查五类规则，撤回样本。记录是否实际读取规则，不以AGENTS存在代替生效。仓库根AGENTS会作为Codex项目指导入口；路径索引要求代理主动读标准。[官方AGENTS说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

## 5. 今天提交与后续缺口

今天可提交的是这套P0正式文档。尚缺：三人确认及版本冻结；独立仓库/权限/保护/首次提交证据；本机或组员环境strict真实通过；A的骨架代码及部署文件；B的自动测试、跨机器启动和审查记录；规范新会话生效验证；全历史秘密扫描；最后归档和骨架tag。不能将阶段性文档提交表述为第7课最终工程验收完成。
