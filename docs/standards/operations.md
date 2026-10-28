# 部署运维规范

适用Dockerfile、Compose、配置、日志和README。所有数值为本组建议默认值，待确认；目的：从独立clone复现并定位故障。

|规则|开发动作与具体约束|检查方法|失败判定与处置|
|---|---|---|---|
|OPS-01 构建|多阶段构建，运行镜像只含产物/必要证书；依赖锁定，镜像按commit标记并固定基础digest，不用latest；不复制.env|审Dockerfile/锁文件及镜像内容；记录构建版本|无锁、含密钥、运行镜像带完整源码即失败，修构建再验|
|OPS-02 Compose|web/api/mysql；宿主web8080，其余内部网络；test用profile隔离；填.env后一命令`docker compose up --build -d`|全新clone在120秒内访问状态页和ready；不得依赖旧CampusClaw|需口头步骤/旧服务才能启动即失败，修README/编排|
|OPS-03 配置|以design的配置表为准，必需值缺失5秒内非零退出，不监听；.env.example不含真实值|逐项删配置、测端口边界；区分配置错误与数据库断连|缺配置假启动即失败；日志暴露值按SEC处理|
|OPS-04 探针|health存活免认证；ready查MySQL SELECT 1；disabled RAG为not_configured；依赖检查1秒、总2秒|停止/恢复mysql，核对health200与ready503/200|仅TCP通就报up、ready在依赖故障时200即失败|
|OPS-05 日志|每行JSON，含time/level/module/request_id/method/path/status/duration_ms；启动事件request_id可null；无凭据/正文/query|解析每行JSON并关联请求header/body/log|解析失败、ID断链或泄密即失败，修日志再测|
|OPS-06 停机/回滚|SIGTERM先不就绪，10秒排空，容器grace≥15秒；停止默认down不带-v。保留上一个验收镜像，回滚切回旧镜像/配置，不重建旧源码|在途请求停机实验；有上版时切回并检查ready/version|切断在途请求/恢复不了上版即失败；首次部署无上版记N/A并说明，不能伪造演练|
|OPS-07 发布记录|记录commit、镜像digest、配置键清单、操作者、探针/测试证据；验收后才归档和tag|比对记录、归档spec及tag目标commit|缺证据或指向未验收提交即失败；本轮不执行发布或Git写操作|

README至少写工具版本、clone、复制.env.example并填值、启动、`curl.exe http://localhost:8080/health`与`/ready`（Windows）、一键测试、查看日志、停止。不要把.env或可能包含值的Compose展开结果作为公开证据。启动失败先看配置字段名；ready503检查MySQL容器健康/授权，再按request ID定位，不要求公开连接串。
