from __future__ import annotations

"""
轻量自检（不依赖数据库/外部服务）：
- 生成一个 V0 timeline
- 编译为 Plan
- 确保 Pydantic 校验能通过

运行方式（示例）：
python -m app.core.auto_edit_v2._selftest
"""

from app.core.auto_edit_v2.plan_compile import (
    build_v0_dsl_from_request,
    build_v0_timeline_from_context,
    compile_timeline_to_plan,
)
from app.core.auto_edit_v2.merge_rank import assign_tiers_and_rank, merge_batches
from app.core.auto_edit_v2.arrange import arrange_timeline
from app.models.auto_edit_timeline import ClipEvent, ClipEventsBatch
from app.models.auto_edit import AutoEditPlanResponse


def main() -> None:
    context = "\n".join(
        [
            "视频1：...",
            "[clip_id=CLIP_A] asr=你好，这里是开场。",
            "[clip_id=CLIP_B] vlm=展示产品外观。",
            "[clip_id=CLIP_C] asr=最后关注点赞。",
        ]
    )
    dsl = build_v0_dsl_from_request("做个快节奏短视频", "voiceover", 30)
    timeline = build_v0_timeline_from_context(context=context, dsl=dsl, mode="voiceover")
    plan = compile_timeline_to_plan(
        timeline=timeline,
        dsl=dsl,
        plan_id="testplan",
        title="test",
        summary="test",
        mode="voiceover",
        allow_cross_video=True,
    )
    res = AutoEditPlanResponse(plans=[plan])
    assert res.plans and res.plans[0].segments, "Plan 应包含 segments"
    print("OK: compiled Plan segments =", len(res.plans[0].segments))

    # V1 pipeline selftest：mock batches -> merge/tier -> arrange -> compile
    b1 = ClipEventsBatch(
        batch_id="b_001",
        events=[
            ClipEvent(
                event_id="e1",
                clip_id="CLIP_A",
                text="开场一句话抓住注意力。",
                source="asr",
                role="hook",
                beat="setup",
                scores={"local_score": 0.9, "relevance": 0.9, "clarity": 0.8, "emotion": 0.2},
                tags=["开场", "抓人"],
            ),
            ClipEvent(
                event_id="e2",
                clip_id="CLIP_B",
                text="展示产品外观与关键细节。",
                source="vlm",
                role="highlight",
                beat="demo",
                scores={"local_score": 0.7, "relevance": 0.75, "clarity": 0.7, "emotion": 0.1},
                tags=["外观", "细节"],
            ),
        ],
    )
    b2 = ClipEventsBatch(
        batch_id="b_002",
        events=[
            ClipEvent(
                event_id="e3",
                clip_id="CLIP_C",
                text="最后引导关注点赞评论。",
                source="asr",
                role="cta",
                beat="payoff",
                scores={"local_score": 0.6, "relevance": 0.65, "clarity": 0.7, "emotion": 0.1},
                tags=["结尾", "引导"],
            )
        ],
    )
    merged = merge_batches([b1, b2])
    pool = assign_tiers_and_rank(merged)
    timeline2 = arrange_timeline(pool=pool, dsl=dsl, mode="voiceover", target_duration_sec=30)
    plan2 = compile_timeline_to_plan(
        timeline=timeline2,
        dsl=dsl,
        plan_id="testplan2",
        title="test2",
        summary="test2",
        mode="voiceover",
        allow_cross_video=True,
    )
    res2 = AutoEditPlanResponse(plans=[plan2])
    assert res2.plans[0].segments, "V1 pipeline 编译后应有 segments"
    print("OK: v1 pipeline segments =", len(res2.plans[0].segments))


if __name__ == "__main__":
    main()

