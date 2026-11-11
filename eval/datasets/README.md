# 评测数据集

`sample_eval.jsonl` 是**人工编写的合成示例**，不是通用科研基准，也不代表真实模型性能。

`user_eval_draft.jsonl` 是根据当前已上传 PDF 生成的 **AI 草稿**，包含 20 道
answerable 和 4 道 unanswerable 题。它还没有经过人工逐条确认，不能直接作为
正式评测结论；使用前必须核对问题、页码、来源文件和 answerable 标签。

## 运行示例前

1. 上传同目录的 `sample_experiment.pdf`，文件名必须是 `sample_experiment.pdf`。
2. 调用该文档的索引接口。
3. 再运行评测。

如果没有上传这个样例 PDF，answerable 样例的检索和引用指标会低，这是正常结果，不应解释为模型失败。

## JSONL 字段

- `id`：唯一，1–128 字符。
- `question`：非空，最多 2000 字符。
- `answerable`：人工确认是否应回答。
- `document_ids`：可选，最多 50 个文档 ID。
- `expected_sources`：answerable=true 时至少 1 条；每条含
  `original_filename`、`page_number`，可选 `document_id`。
- `expected_answer_keywords`：可选弱指标标签，最多 20 个。
- `notes`：人工备注，默认不写入评测报告。

不要用模型生成标签充当“标准答案”。评测结果只对当前数据集、知识库、模型和配置有效。
