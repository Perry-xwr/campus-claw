# CampusClaw 一键检查入口（第 8–10 课）
# 用法：make check-security / check-async / check-apitest / check-audit / check
# Windows 若无 GNU make，等价入口：pwsh -File scripts/check-all.ps1

PYTHON ?= python
EVIDENCE := reports/evidence
# 审计回查默认读运行库；CI 或干净环境没有库时用 --allow-empty 跳过数据断言，
# 结构断言（七列是否齐备）仍然生效。
AUDIT_DB ?= data/app.db

.PHONY: help check check-security check-async check-apitest check-audit check-bench

help:
	@echo make check-security  SEC-05 密钥扫描 + SEC-06 依赖基线
	@echo make check-async     第 8 课三条判据复现
	@echo make check-apitest   第 9 课注入三件套（SQL / XSS / CSRF 反例）
	@echo make check-audit     SEC-07 审计日志七列回查（结构断言 + 数据断言）
	@echo make check-bench     第 10 课压测基线（需先启动实例）
	@echo make check           以上四项一起跑（门禁入口，红即退出码非 0）

check-security:
	$(PYTHON) scripts/check_security.py --out $(EVIDENCE)/security-baseline.json

check-async:
	$(PYTHON) scripts/acceptance_async.py --out $(EVIDENCE)/async-acceptance.json

check-apitest:
	$(PYTHON) apitest/run_all.py --no-report

check-audit:
	$(PYTHON) scripts/audit_recheck.py --db $(AUDIT_DB) --out reports/audit-recheck.md --allow-empty

check-bench:
	$(PYTHON) scripts/bench.py --vus $(or $(VUS),20) --duration $(or $(DURATION),60)

check: check-security check-async check-apitest check-audit
