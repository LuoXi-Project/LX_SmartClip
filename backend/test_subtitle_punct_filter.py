# -*- coding: utf-8 -*-
"""临时验证脚本：字幕标点过滤规则（纯标点条/头尾标点/句中标点保留）。"""
import sys

from app.core.subtitle.timeline import (
    _text_to_subtitle_chunks,
    rule_timeline_equal_units,
    rule_timeline_weighted_chars,
    sanitize_subtitle_entries,
    strip_subtitle_edge_punctuation,
)
from app.core.subtitle.ass_builder import wrap_text_for_ass_display
from app.core.subtitle.srt import build_srt, parse_srt

FAIL = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")
    if not ok:
        FAIL.append(name)


class Seg:
    def __init__(self, text, clip_id="c1"):
        self.copy_text = text
        self.clip_id = clip_id


# --- 1. 头尾标点剥离 ---
check("尾部句号", strip_subtitle_edge_punctuation("今天，我们聊聊。"), "今天，我们聊聊")
check("句中逗号保留", strip_subtitle_edge_punctuation("今天，我们聊聊"), "今天，我们聊聊")
check("小数点保留", strip_subtitle_edge_punctuation("涨了3.14个百分点"), "涨了3.14个百分点")
check("英文撇号保留", strip_subtitle_edge_punctuation("don't stop"), "don't stop")
check("行首省略号", strip_subtitle_edge_punctuation("……好家伙"), "好家伙")
check("行首逗号", strip_subtitle_edge_punctuation("，然后他走了"), "然后他走了")
check("纯标点条", strip_subtitle_edge_punctuation("？？？"), "")
check("纯省略号", strip_subtitle_edge_punctuation("……"), "")
check("混合头尾", strip_subtitle_edge_punctuation("“真的吗？！”"), "真的吗")
check("头尾空白", strip_subtitle_edge_punctuation("  你好  "), "你好")
check("连字符单词保留", strip_subtitle_edge_punctuation("state-of-the-art"), "state-of-the-art")
check("markdown星号", strip_subtitle_edge_punctuation("**重点**"), "重点")

# --- 2. 切条：连续标点不产生纯标点条 ---
chunks = _text_to_subtitle_chunks("真的假的？？？下一句。", 20)
check("连续问号切条", chunks, ["真的假的", "下一句"])

chunks = _text_to_subtitle_chunks("好家伙。。。。", 20)
check("连续句号切条", chunks, ["好家伙"])

chunks = _text_to_subtitle_chunks("……先卖个关子", 20)
check("行首省略号切条", chunks, ["先卖个关子"])

# 强切场景：长句 + 标点密集，确认无标点打头的条
long_text = "这是一段特别长的文案需要在标点处强行切断看看会不会出现标点打头的情况，，，以及尾部悬挂的情况。。。"
chunks = _text_to_subtitle_chunks(long_text, 10, fine_grain_split=True)
print("强切条目:", chunks)
for c in chunks:
    if not c or c != strip_subtitle_edge_punctuation(c):
        FAIL.append(f"强切条未清理: {c!r}")
        print(f"FAIL 强切条未清理: {c!r}")

# --- 3. 加权时间轴：纯标点段不产生条目、时长分给真实文本 ---
entries = rule_timeline_weighted_chars(
    [Seg("真的假的？？？"), Seg("……")], [3.0, 2.0], 20
)
check("加权法条目文本", [e["text"] for e in entries], ["真的假的"])
check("加权法覆盖整段", (entries[0]["start"], entries[0]["end"]), (0.0, 3.0))

# --- 4. 原声导出等分时间轴 ---
entries = rule_timeline_equal_units([Seg("好家伙？？？"), Seg("。。。")], [2.0, 1.0], 20)
check("等分法条目文本", [e["text"] for e in entries], ["好家伙"])
check("等分法时长铺满", (entries[0]["start"], entries[0]["end"]), (0.0, 2.0))

# --- 5. 烧录兜底：手工编辑/历史 SRT ---
srt = build_srt([
    {"start": 0.0, "end": 1.0, "text": "，标点开头"},
    {"start": 1.0, "end": 2.0, "text": "？？？"},
    {"start": 2.0, "end": 3.0, "text": "正常一句，带逗号。"},
])
entries = sanitize_subtitle_entries(parse_srt(srt))
check("SRT兜底清理", [e["text"] for e in entries], ["标点开头", "正常一句，带逗号"])
check("SRT兜底时间不变", [(e["start"], e["end"]) for e in entries], [(0.0, 1.0), (2.0, 3.0)])

# --- 6. ASS 显示层纵深防御 ---
check("ASS折行清理", wrap_text_for_ass_display("……好家伙？？？？？？", 20), "好家伙")
check("ASS句中保留", wrap_text_for_ass_display("今天，我们聊聊。", 20), "今天，我们聊聊")
check("ASS纯标点行为空", wrap_text_for_ass_display("……", 20), "")

print()
if FAIL:
    print(f"共 {len(FAIL)} 项失败: {FAIL}")
    sys.exit(1)
print("全部通过")
