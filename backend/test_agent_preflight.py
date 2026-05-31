import asyncio

from app.agent.intent_preflight import run_intent_preflight, search_videos_by_name


async def main() -> None:
    rows = await search_videos_by_name("洁柔", limit=5)
    print("search 洁柔:", len(rows), [r.get("name") for r in rows])

    r1 = await run_intent_preflight(
        "选洁柔面巾纸的3个视频，做30秒口播方案",
        selected_video_ids=[],
    )
    print("preflight1:", r1)

    r2 = await run_intent_preflight(
        "洁柔面巾纸的3个视频",
        selected_video_ids=[],
    )
    print("preflight2:", r2)


if __name__ == "__main__":
    asyncio.run(main())
