# 评测报告

实际运行报告写入 `DATA_DIR/evaluations/`（默认 `data/evaluations/`）：

- `eval-*.json`：机器可读安全报告
- `eval-*.md`：人工查看报告

报告不包含完整问题、完整回答、Prompt、文档全文、API Key 或绝对路径。
默认只保存 `case_id`、指标计数和配置快照；开启 `EVALUATION_SAVE_DETAILS=true`
时也只保存截断的问题/回答前缀。
