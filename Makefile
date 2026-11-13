# CampusClaw 一键检查入口（第 8–10 课）
# 用法：make check / make check-security / check-async / check-apitest / check-audit …
#
# `make` 只是一层壳：真正的步骤清单在 scripts/check_all.py（顺序、参数、退出码）。
# Windows 没有 GNU make 时，等价入口是同一条命令的后半截：
#     python scripts/check_all.py
# 单项目标也走这同一份清单（--only），所以不存在「Makefile 与脚本各写一套参数」
# 的漂移——DEF-07（check-compose 被写成字面量 /n/t 却没人发现）正是漂移的产物。

PYTHON ?= python
GATE := $(PYTHON) scripts/check_all.py

.PHONY: help check check-security check-async check-apitest check-audit check-observe check-compose check-bench

help:
	@echo make check-security  SEC-05 密钥扫描 + SEC-06 依赖基线
	@echo make check-async     第 8 课三条判据复现
	@echo make check-apitest   第 9 课注入三件套（SQL / XSS / CSRF 反例）
	@echo make check-audit     SEC-07 审计日志七列回查（结构断言 + 数据断言）
	@echo make check-observe   第 10 课运行观测告警判定（critical 即红）
	@echo make check-compose   容器配置静态校验（不需要 Docker）
	@echo make check-bench     第 10 课压测基线（需先启动实例）
	@echo make check           六项一起跑（= python scripts/check_all.py，红即退出码非 0）

check-security:
	$(GATE) --only security

check-async:
	$(GATE) --only async

check-apitest:
	$(GATE) --only apitest

check-audit:
	$(GATE) --only audit

check-observe:
	$(GATE) --only observe

check-compose:
	$(GATE) --only compose

# 压测不进 `check`：它需要一个已经跑起来的实例，且会写库，
# 不适合作门禁的一部分（门禁必须能在任何干净环境里离线跑出同样的结果）。
check-bench:
	$(PYTHON) scripts/bench.py --vus $(or $(VUS),20) --duration $(or $(DURATION),60)

check:
	$(GATE)
