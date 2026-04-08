# Replica 质量评估

用于验证复刻模板是否达到“短视频/影视解说/场景剧情”三类稳定可用。

## 数据格式

输入为 JSONL，每行一个样本：

```json
{
  "id": "case_001",
  "replica_type": "film_commentary",
  "expected_min_chapters": 4,
  "template_guide": "......",
  "template_json": {
    "structure": ["opening", "setup", "conflict", "climax", "cta"],
    "chapter_plan": [{ "chapter": "开场" }],
    "transition_patterns": ["承接", "转折"]
  }
}
```

## 运行方式

```bash
python scripts/replica_quality_eval.py --input data/replica_eval_samples.jsonl --output data/replica_eval_report.json
```

## 评估维度

- 结构完整率：`structure` 是否足够完整（>=5）
- 章节覆盖率：`chapter_plan` 数量是否达到预期
- 过渡连贯性：`transition_patterns` 是否存在且>=2
- 可复用性：`template_guide` 是否具备足够执行信息

总分为四项均值，低于 `0.7` 视为失败样本。

## 验收建议

- 三类 `replica_type` 的均分均 >= 0.75
- 失败样本率 <= 15%
- `film_commentary` 均分不低于 `short_video` 均分 - 0.05
