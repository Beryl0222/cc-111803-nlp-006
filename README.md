# 客服复合诉求的责任分派

本地文本工作区用于保存复合意图识别相关的合成记录，并提供基础规范化和词项查看能力。

## 环境

需要 Python 3.11 或更新版本。运行程序仅使用 Python 标准库。测试依赖固定为 pytest 8.3.4，可执行 `python -m pip install -r requirements-dev.txt` 安装。

## 运行

运行 `PYTHONPATH=src python -m nlp_support_case_routing.desk_cli` 查看人工圈定的单项诉求如何分派和读回账务回执。同一个产品可以由不同团队处理账务和账号。账号操作须有该账号的核验记录。

运行 `PYTHONPATH=src python -m nlp_support_case_routing.dialogue_cli` 查看整段客户会话的理解与分派结果。系统按话语识别修改、否定、引述和跨轮指代，结合订单、产品和身份核验生成诉求：指代有多个候选时进入待确认，由主管在候选中圈定；已交账务的退款收到撤回只能请账务停止，之后收到已执行回执则按已执行结果交给坐席协调；未交办的明确撤回直接关闭。坐席视图中的每项进度都能追到原话、确认和团队回执，主管更正对象后旧事项的交办与回执保持不动，新请求需独立确认。样例见 fixtures/dialogue.json。

从项目根目录执行 `PYTHONPATH=src python -m nlp_support_case_routing.cli ingest fixtures/records.json` 导入样例，随后执行 `PYTHONPATH=src python -m nlp_support_case_routing.cli list` 查看记录。工作数据写入 `var/records.json`。业务查询使用 fixtures/business.json 中的初始资料，约定见 fixtures/business-contract.md。执行 PYTHONPATH=src python -m nlp_support_case_routing.cli business 可查看当前业务目录结果。

样例为本地合成文本。记录包含来源、修订号和原文，当前工作区对空白做统一处理，并提供字符及英文词项切分。

## 测试

执行 `python -m pytest -q` 检查规范化、记录持久化和来源筛选。
