#!/usr/bin/env python3
"""
Phase 3 视频切分功能测试脚本

测试内容：
1. 音频提取
2. 固定时长切分
3. 镜头识别切分
4. 自动抽帧
"""

import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.splitter import VideoSplitter
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_audio_extraction(splitter: VideoSplitter, video_path: str):
    """测试音频提取"""
    print("\n" + "="*50)
    print("测试 1: 音频提取")
    print("="*50)
    
    try:
        audio_path = splitter.extract_audio(video_path)
        print(f"✅ 音频提取成功: {audio_path}")
        print(f"   文件大小: {os.path.getsize(audio_path) / 1024 / 1024:.2f} MB")
        return audio_path
    except Exception as e:
        print(f"❌ 音频提取失败: {e}")
        return None


def test_fixed_split(splitter: VideoSplitter, video_path: str, duration: float = 10):
    """测试固定时长切分"""
    print("\n" + "="*50)
    print(f"测试 2: 固定时长切分 ({duration}s)")
    print("="*50)
    
    try:
        clips = splitter.split_by_fixed(video_path, duration)
        print(f"✅ 固定时长切分成功: {len(clips)} 个片段")
        for i, clip in enumerate(clips):
            print(f"   片段 {i+1}: {clip.start_time:.2f}s - {clip.end_time:.2f}s ({clip.duration:.2f}s)")
            print(f"            {clip.clip_path}")
        return clips
    except Exception as e:
        print(f"❌ 固定时长切分失败: {e}")
        return None


def test_scene_split(splitter: VideoSplitter, video_path: str, threshold: float = 0.4):
    """测试镜头识别切分"""
    print("\n" + "="*50)
    print(f"测试 3: 镜头识别切分 (阈值={threshold})")
    print("="*50)
    
    try:
        clips = splitter.split_by_scene(video_path, threshold)
        print(f"✅ 镜头识别切分成功: {len(clips)} 个片段")
        for i, clip in enumerate(clips):
            print(f"   片段 {i+1}: {clip.start_time:.2f}s - {clip.end_time:.2f}s ({clip.duration:.2f}s)")
            print(f"            {clip.clip_path}")
        return clips
    except Exception as e:
        print(f"❌ 镜头识别切分失败: {e}")
        return None


def test_frame_extraction(splitter: VideoSplitter, clips, n_frames: int = 3):
    """测试抽帧"""
    print("\n" + "="*50)
    print(f"测试 4: 自动抽帧 ({n_frames} 帧/片段)")
    print("="*50)
    
    if not clips:
        print("❌ 没有片段可用于抽帧")
        return
    
    try:
        for i, clip in enumerate(clips[:3]):  # 只测试前 3 个片段
            frame_paths = splitter.extract_frames(clip.clip_path, n_frames)
            print(f"✅ 片段 {i+1} 抽帧成功: {len(frame_paths)} 帧")
            for j, frame_path in enumerate(frame_paths):
                print(f"   帧 {j+1}: {frame_path}")
    except Exception as e:
        print(f"❌ 抽帧失败: {e}")


def main():
    """主测试函数"""
    print("\n" + "="*50)
    print("LX SmartClip Phase 3 - 视频切分功能测试")
    print("="*50)
    
    # 检查测试视频
    test_video = "test.mp4"
    if not os.path.exists(test_video):
        print(f"\n❌ 测试视频不存在: {test_video}")
        print("   请在项目根目录放置一个 test.mp4 文件")
        print("   或修改 test_video 变量指向你的视频文件")
        return
    
    print(f"\n📹 测试视频: {test_video}")
    print(f"   文件大小: {os.path.getsize(test_video) / 1024 / 1024:.2f} MB")
    
    # 初始化切分器
    splitter = VideoSplitter()
    
    # 运行测试
    print("\n开始测试...")
    
    # 测试 1: 音频提取
    audio_path = test_audio_extraction(splitter, test_video)
    
    # 测试 2: 固定时长切分
    fixed_clips = test_fixed_split(splitter, test_video, duration=10)
    
    # 测试 3: 镜头识别切分
    scene_clips = test_scene_split(splitter, test_video, threshold=0.4)
    
    # 测试 4: 抽帧
    if fixed_clips:
        test_frame_extraction(splitter, fixed_clips, n_frames=3)
    
    print("\n" + "="*50)
    print("✅ 所有测试完成！")
    print("="*50)
    print("\n生成的文件位置:")
    print(f"  音频: {splitter.audio_dir}")
    print(f"  片段: {splitter.clips_dir}")
    print(f"  帧: {splitter.frames_dir}")


if __name__ == "__main__":
    main()
