"""subtitle.py — SRT字幕生成 & 烧录"""
from __future__ import annotations
import io, json, logging, os, re, subprocess, tempfile, urllib.request as _urllib
from typing import List, Optional
from urllib.parse import quote
import aiosqlite, httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app.db.database import DB_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subtitle", tags=["subtitle"])
TTS_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "tts_audio"))
os.makedirs(os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "subtitles")), exist_ok=True)

# SECTION: helpers
def _get_proxy():
    p = _urllib.getproxies(); return p.get("https") or p.get("http") or None
async def _read_cfg(db, key, default=""):
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as c:
        row = await c.fetchone()
    return row[0] if row else default
def _probe_audio_duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",path], capture_output=True, timeout=10)
        out = r.stdout.decode().strip(); return float(out) if out else 0.0
    except Exception as e:
        logger.warning("ffprobe failed %s: %s", path, e); return 0.0
def _srt_time(s: float) -> str:
    ms=int(round(s*1000)); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); sec,ms=divmod(ms,1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
def _build_srt(entries: list) -> str:
    out=[]
    for i,e in enumerate(entries,1):
        out+=[str(i), f"{_srt_time(e['start'])} --> {_srt_time(e['end'])}", e["text"].strip(), ""]
    return "\n".join(out)
def _parse_srt(srt: str) -> list:
    entries=[]
    for block in re.split(r"\n\s*\n", srt.strip()):
        ls=block.strip().splitlines()
        if len(ls)<3: continue
        m=re.match(r"(\d+):(\d+):(\d+)[,\.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,\.](\d+)",ls[1].strip())
        if not m: continue
        def ts(h,mi,s,ms): return int(h)*3600+int(mi)*60+int(s)+int(ms)/1000
        entries.append({"start":ts(*m.group(1,2,3,4)),"end":ts(*m.group(5,6,7,8)),"text":" ".join(ls[2:])})
    return entries

# SECTION: schemas
class SubtitleSegmentInput(BaseModel):
    copy_text: str; clip_id: str; tts_filename: Optional[str]=None
class SubtitleStyle(BaseModel):
    font_name: str="Arial"; font_size: int=24; font_color: str="#FFFFFF"
    outline_color: str="#000000"; outline_width: float=2.0; shadow: float=1.0
    bold: bool=False; italic: bool=False; position: str="bottom"
    margin_v: int=20; background: bool=False; max_chars_per_line: int=20
class GenerateSRTRequest(BaseModel):
    segments: List[SubtitleSegmentInput]; style: Optional[SubtitleStyle]=None
    use_tts_timing: bool=True
class SRTEntry(BaseModel):
    index: int; start: float; end: float; text: str; clip_id: str
class GenerateSRTResponse(BaseModel):
    srt_content: str; entries: List[SRTEntry]; total_duration: float; timing_source: str
class BurnSubtitleRequest(BaseModel):
    segments: List[SubtitleSegmentInput]; srt_content: str
    style: SubtitleStyle=Field(default_factory=SubtitleStyle); project_name: Optional[str]="smartclip_subtitled"

# SECTION: duration resolution
def _resolve_durations(segments, clip_durations, use_tts):
    durs=[]; srcs=[]
    for seg in segments:
        if use_tts and seg.tts_filename:
            p=os.path.join(TTS_AUDIO_DIR, os.path.basename(seg.tts_filename))
            d=_probe_audio_duration(p)
            if d>0:
                durs.append(d); srcs.append("tts")
                logger.info("字幕时长[TTS] %s=%.3fs", seg.tts_filename, d); continue
        durs.append(clip_durations.get(seg.clip_id, 5.0)); srcs.append("clip")
    return durs, (srcs[0] if len(set(srcs))==1 else "mixed")

# SECTION: rule-based timeline
def _rule_timeline(segments, durations, max_chars=20):
    entries=[]; t=0.0
    for seg,dur in zip(segments,durations):
        text=seg.copy_text.strip()
        if not text: t+=dur; continue
        chunks=[text[i:i+max_chars] for i in range(0,len(text),max_chars)]
        cd=dur/len(chunks); ss=t
        for ci,chunk in enumerate(chunks):
            cs=ss+ci*cd; ce=min(cs+max(cd-0.05,0.3),ss+dur-0.05)
            entries.append({"clip_id":seg.clip_id,"start":round(cs,3),"end":round(ce,3),"text":chunk})
        t+=dur
    return entries

# SECTION: LLM timeline
SYS_PROMPT="""你是专业的视频字幕时间轴生成器。根据文案和时长生成字幕时间轴，时间全局连续累加。
规则: 1.不超出片段时长 2.超20字拆多条每条<=20字 3.每条0.3-6秒条间0.05秒 4.输出JSON:{"entries":[{"clip_id":"...","start":0.0,"end":2.5,"text":"..."}]} 5.只输出JSON"""
async def _llm_timeline(segments, durations, base_url, api_key, model):
    info=[]; cum=0.0
    for seg,dur in zip(segments,durations):
        info.append(f'clip_id={seg.clip_id} start={cum:.3f}s dur={dur:.3f}s text="{seg.copy_text}"'); cum+=dur
    body={"model":model,"messages":[{"role":"system","content":SYS_PROMPT},{"role":"user","content":"生成时间轴:\n"+"\n".join(info)}],"temperature":0.2,"max_tokens":4096}
    async with httpx.AsyncClient(timeout=60,proxy=_get_proxy()) as c:
        r=await c.post(base_url.rstrip("/")+"/chat/completions",headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},json=body)
    if r.status_code!=200: raise RuntimeError(f"LLM {r.status_code}: {r.text[:200]}")
    raw=r.json()["choices"][0]["message"]["content"]
    try:
        p=json.loads(raw)
        entries=p.get("entries",[]) if isinstance(p,dict) else p
        if not entries and isinstance(p,dict): entries=next((v for v in p.values() if isinstance(v,list)),[])
    except json.JSONDecodeError:
        m2=re.search(r'\[.*\]',raw,re.DOTALL); entries=json.loads(m2.group()) if m2 else []
    return entries

# SECTION: route generate
@router.post("/generate", response_model=GenerateSRTResponse)
async def generate_srt(req: GenerateSRTRequest):
    """生成SRT时间轴，TTS音频时长优先于视频片段时长"""
    if not req.segments: raise HTTPException(400, "segments不能为空")
    ids=[s.clip_id for s in req.segments]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        bu=await _read_cfg(db,"vlm_base_url"); ak=await _read_cfg(db,"vlm_api_key")
        model=await _read_cfg(db,"llm_model") or await _read_cfg(db,"vlm_model")
        async with db.execute(f"SELECT id,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})",ids) as cur:
            rows=await cur.fetchall()
    clip_dur={r["id"]:float(r["duration"] or 5.0) for r in rows}
    max_chars=req.style.max_chars_per_line if req.style else 20
    durs,src=_resolve_durations(req.segments,clip_dur,req.use_tts_timing)
    raw_e=[]
    if bu and ak and model:
        try: raw_e=await _llm_timeline(req.segments,durs,bu,ak,model)
        except Exception as e: logger.warning("LLM失败降级: %s",e); raw_e=_rule_timeline(req.segments,durs,max_chars)
    else: raw_e=_rule_timeline(req.segments,durs,max_chars)
    out=[SRTEntry(index=i,start=float(e.get("start",0)),end=float(e.get("end",1)),text=str(e.get("text","")),clip_id=str(e.get("clip_id",""))) for i,e in enumerate(raw_e,1)]
    srt=_build_srt([{"start":e.start,"end":e.end,"text":e.text} for e in out])
    return GenerateSRTResponse(srt_content=srt,entries=out,total_duration=max((e.end for e in out),default=0.0),timing_source=src)

# SECTION: ASS builder
def _hex_bgr(c):
    h=c.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}" if len(h)==6 else "&H00FFFFFF"
def _build_ass(srt_entries, style: SubtitleStyle, vh=720):
    al={"bottom":2,"center":5,"top":8}.get(style.position,2)
    mb=style.margin_v if style.position=="bottom" else 20
    bv=-1 if style.bold else 0; iv=-1 if style.italic else 0
    bc="&H80000000" if style.background else "&H00000000"
    header=(f"[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: {vh}\nScaledBorderAndShadow: yes\n\n"
            f"[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{style.font_name},{style.font_size},{_hex_bgr(style.font_color)},&H00FFFFFF,{_hex_bgr(style.outline_color)},{bc},{bv},{iv},0,0,100,100,0,0,1,{style.outline_width},{style.shadow},{al},10,10,{mb},1\n\n"
            f"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    def at(s):
        cs=int(round(s*100)); h,cs=divmod(cs,360000); mi,cs=divmod(cs,6000); sec,cs=divmod(cs,100)
        return f"{h}:{mi:02d}:{sec:02d}.{cs:02d}"
    events="".join(f"Dialogue: 0,{at(e['start'])},{at(e['end'])},Default,,0,0,0,,{e['text'].replace(chr(10),chr(92)+'N')}\n" for e in srt_entries)
    return header+events

# SECTION: route burn
@router.post("/burn")
async def burn_subtitle(req: BurnSubtitleRequest):
    """合并视频+替换TTS音轨+硬烧ASS字幕，返回MP4"""
    if not req.segments: raise HTTPException(400,"segments不能为空")
    ids=[s.clip_id for s in req.segments]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        async with db.execute(f"SELECT id,clip_path,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})",ids) as cur:
            rows=await cur.fetchall()
    clip_map={r["id"]:{"path":r["clip_path"],"dur":float(r["duration"] or 5)} for r in rows}
    srt_e=_parse_srt(req.srt_content)
    with tempfile.TemporaryDirectory() as tmp:
        segs=[]
        for i,seg in enumerate(req.segments):
            info=clip_map.get(seg.clip_id)
            if not info or not os.path.isfile(info["path"] or ""): raise HTTPException(404,f"片段不存在:{seg.clip_id}")
            out=os.path.join(tmp,f"seg_{i:03d}.mp4")
            tts_ok=seg.tts_filename and os.path.isfile(os.path.join(TTS_AUDIO_DIR,os.path.basename(seg.tts_filename)))
            if tts_ok:
                tp=os.path.join(TTS_AUDIO_DIR,os.path.basename(seg.tts_filename))
                cmd=["ffmpeg","-y","-i",info["path"],"-i",tp,"-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","fast","-crf","23","-c:a","aac","-shortest",out]
            else:
                cmd=["ffmpeg","-y","-i",info["path"],"-c:v","libx264","-preset","fast","-crf","23","-c:a","aac",out]
            p=subprocess.run(cmd,capture_output=True,timeout=180)
            if p.returncode!=0: raise HTTPException(500,f"ffmpeg段{i+1}失败:{p.stderr.decode(errors='replace')[-300:]}")
            segs.append(out)
        if len(segs)==1:
            merged=segs[0]
        else:
            cl=os.path.join(tmp,"concat.txt")
            open(cl,"w").write("".join(f"file '{s}'\n" for s in segs))
            merged=os.path.join(tmp,"merged.mp4")
            
            p=subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',cl,'-c','copy',merged],capture_output=True,timeout=300)
            if p.returncode!=0: raise HTTPException(500,'concat failed: '+p.stderr.decode(errors='replace')[-200:])
        ass_content=_build_ass(srt_e,req.style)
        ass_path=os.path.join(tmp,'sub.ass')
        with open(ass_path,'w',encoding='utf-8') as f: f.write(ass_content)
        final=os.path.join(tmp,'final.mp4')
        ass_esc=ass_path.replace(chr(92),'/').replace(':',chr(92)+':')
        p=subprocess.run(['ffmpeg','-y','-i',merged,'-vf','ass='+ass_esc,'-c:v','libx264','-preset','fast','-crf','23','-c:a','aac',final],capture_output=True,timeout=600)
        if p.returncode!=0: raise HTTPException(500,'burn failed: '+p.stderr.decode(errors='replace')[-400:])
        data=open(final,'rb').read()
    name=req.project_name+'.mp4'
    return StreamingResponse(
        io.BytesIO(data),media_type='video/mp4',
        headers={'Content-Disposition':'attachment; filename=smartclip_subtitled.mp4'},
    )
