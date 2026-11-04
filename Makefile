# CampusClaw 第 8 课一键检查入口
# 用法：make check-security / make check-async / make check
# Windows 若无 GNU make，等价入口：pwsh -File scripts/check-all.ps1

PYTHON ?= python
EVIDENCE := reports/evidence

.PHONY: help check check-security check-async check-apitest

help:
	@echo make check-security  SEC-05 密钥扫描 + SEC-06 依赖基线
	@echo make check-async     第 8 课三条判据复现
	@echo make check           以上两项一起跑
	@echo make check-apitest   既有接口回归套件

check-security:
	$(PYTHON) scripts/check_security.py --out $(EVIDENCE)/security-baseline.json

check-async:
	$(PYTHON) scripts/acceptance_async.py --out $(EVIDENCE)/async-acceptance.json

check-apitest:
	$(PYTHON) apitest/run_all.py --no-report

check: check-security check-async
