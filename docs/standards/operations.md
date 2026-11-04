# 部署运维规范（uv / Docker Compose）

规则编号OPS-01…OPS-07保留，按当前仓库实际方式执行。服务定义以`docker-compose.yml`为准：app、worker、qdrant、mcp；本机可用uv运行Flask和worker。具体版本以`pyproject.toml`、`uv.lock`及Dockerfile实际镜像为准。

|规则|开发动作|检查|失败判定|
|---|---|---|---|
|OPS-01 依赖|`pyproject.toml`声明直接依赖，`uv.lock`锁定解算；容器当前使用requirements.txt和Python 3.12镜像。变更依赖时说明双清单同步策略并检查锁一致性。镜像当前tag latest属现状，不自动视为不可变发布制品。|检查uv lock可复现（不安装本任务依赖）；对照requirements和镜像COPY/PIP安装；发布时记录镜像digest。|锁文件缺失/清单漂移导致不可复现即失败；latest禁止作为可追溯发布证据。|
|OPS-02 启动|本机`uv sync`、`uv run python app.py`；Compose `docker compose up --build -d`；Windows脚本`pwsh -File scripts/start-all.ps1`及stop-all。按README所列依赖顺序启动。|只在被授权的验收任务执行启动；检查容器健康、日志和退出码。|依赖不可用被报告为健康、脚本遗留进程或启动说明与配置不符即失败。|
|OPS-03 配置/数据|`.env`供本地覆盖；STRICT_CONFIG在对外部署必须打开。Compose挂载`./data`、`./uploads`及Qdrant卷；备份前停止/一致性复制SQLite和相关上传数据。不得随意`down -v`。|检查挂载、.gitignore、脱敏环境样例；恢复演练需独立授权和临时数据。|删除卷即导致数据丢失；公开运行使用默认演示凭据即失败。|
|OPS-04 健康|Flask `/health`匿名只读检查SQLite必需表，返回200或503；Compose app健康检查调用此路由。Qdrant可选，不能把向量不可用等同所有关键词功能不可用。|核对health_views.py、db.health_probe和Compose healthcheck；模拟DB故障仅在验收环境执行。|返回健康但SQLite表不可用，或健康路由泄漏内部细节即失败。当前无独立ready探针，不能按双探针门槛判通过。|
|OPS-05 日志|Python logging，容器无缓冲输出；worker记录任务状态。日志不得含口令、token、API key、会话cookie、用户完整问题/回答。request ID结构化关联若缺失列为改进项。|检查app、worker、MCP日志格式及敏感字段；以无秘密哨兵做扫描。|敏感值或用户全文泄露即失败；未具request ID标记待改进，不声称已满足。|
|OPS-06 生命周期/恢复|Compose restart策略为unless-stopped；停止和重启不能覆盖挂载数据。记录SQLite备份、Qdrant卷与上传文件的恢复步骤；本项目未定义的RPO/RTO须待组员定，不虚构演练。|在临时演示副本测试停启保留；恢复演练记录数据一致性。|启动依赖故障被静默吞掉、恢复需删除原数据即失败。|
|OPS-07 交付|文档记录提交、环境变量键名、命令、结果和回滚说明；配置值永不入记录。提交/tag按授权。|核对部署记录与实际Compose/README及镜像摘要。|无法追溯实际制品/配置，或未经授权发布即失败。|

当前Compose以requirements.txt安装、Python 3.12 slim、Gunicorn单worker；uv本机约束Python 3.11。此差异应由组员确认是否有意并用锁定依赖/实际验收证明兼容。
