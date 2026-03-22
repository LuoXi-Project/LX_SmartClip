#!/usr/bin/env python3
"""
Phase 4 ASR 语音识别功能测试脚本

测试内容：
1. Whisper 模型加载
2. 音频转写
3. 批量处理
"""

import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.asr.whisper_asr import WhisperASR
from app.core.splitter import VideoSplitter
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_whisper_loading():
    """测试 Whisper 模型加载"""
    print("\n" + "="*50)
    print("测试 1: Whisper 模型加载")
    print("="*50)
    
    try:
        asr = WhisperASR(model_size="base", device="cpu")
        info = asr.get_model_info()
        print(f"✅ Whisper 模型加载成功")
        print(f"   模型信息: {info}")
        return asr
    except Exception as e:
        print(f"❌ Whisper 模型加载失败: {e}")
        return None


def test_audio_transcription(asr: WhisperASR, audio_path: str):
    """测试音频转写"""
    print("\n" + "="*50)
    print("测试 2: 音频转写")
    print("="*50)
    
    if not os.path.exists(audio_path):
        print(f"❌ 音频文件不存在: {audio_path}")
        return None
    
    try:
        text = asr.transcribe(audio_path)
        print(f"✅ 音频转写成功")
        print(f"   文本长度: {len(text)} 个字符")
        print(f"   转写内容: {text[:200]}...")
        return text
    except Exception as e:
        print(f"❌ 音频转写失败: {e}")
        return None


def test_batch_processing(asr: WhisperASR, splitter: VideoSplitter, video_path: str):
    """测试批量处理"""
    print("\n" + "="*50)
    print("测试 3: 批量处理（切分 + ASR）")
    print("="*50)
    
    if not os.path.exists(video_path):
        print(f"❌ 视频文件不存在: {video_path}")
        return
    
    try:
        # 切分视频
        print("正在切分视频...")
        clips = splitter.split_by_fixed(video_path, duration=10)
        print(f"✅ 切分完成: {len(clips)} 个片段")
        
        # 处理每个片段
        results = []
        for i, clip in enumerate(clips[:3]):  # 只处理前 3 个片段
            print(f"\n处理片段 {i+1}/3...")
            
            # 提取音频
            audio_path = splitter.extract_audio(clip.clip_path)
            
            # 转写音频
            text = asr.transcribe(audio_path)
            results.append({
                "clip_id": i,
                "duration": clip.duration,
                "text_length": len(text),
                "text": text[:100] + "..." if len(text) > 100 else text,
            })
            
            print(f"✅ 片段 {i+1} 处理完成: {len(text)} 个字符")
        
        print(f"\n✅ 批量处理完成: {len(results)} 个片段")
        for result in results:
            print(f"   片段 {result['clip_id']}: {result['text_length']} 字符")
            print(f"   内容: {result['text']}")
        
    except Exception as e:
        print(f"❌ 批量处理失败: {e}")


def main():
    """主测试函数"""
    print("\n" + "="*50)
    print("LX SmartClip Phase 4 - ASR 语音识别功能测试")
    print("="*50)
    
    # 检查测试视频
    test_video = "test.mp4"
    if not os.path.exists(test_video):
        print(f"\n❌ 测试视频不存在: {test_video}")
        print("   请在项目根目录放置一个 test.mp4 文件")
        return
    
    print(f"\n📹 测试视频: {test_video}")
    
    # 初始化
    splitter = VideoSplitter()
    
    # 测试 1: 模型加载
    asr = test_whisper_loading()
    if not asr:
        return
    
    # 提取音频用于测试
    print("\n正在提取音频...")
    try:
        audio_path = splitter.extract_audio(test_video)
        print(f"✅ 音频提取成功: {audio_path}")
    except Exception as e:
        print(f"❌ 音频提取失败: {e}")
        return
    
    # 测试 2: 音频转写
    text = test_audio_transcription(asr, audio_path)
    
    # 测试 3: 批量处理
    test_batch_processing(asr, splitter, test_video)
    
    print("\n" + "="*50)
    print("✅ 所有测试完成！")
    print("="*50)


if __name__ == "__main__":
    main()
