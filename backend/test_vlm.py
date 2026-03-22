#!/usr/bin/env python3
"""
Phase 5 VLM 视觉描述功能测试脚本

测试内容：
1. OpenAI VLM 初始化
2. 图像描述生成
3. 批量处理
"""

import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.vlm.openai_vlm import OpenAIVLM
from app.core.splitter import VideoSplitter
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_vlm_initialization():
    """测试 VLM 初始化"""
    print("\n" + "="*50)
    print("测试 1: OpenAI VLM 初始化")
    print("="*50)
    
    # 从环境变量读取 API Key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ 未设置 OPENAI_API_KEY 环境变量")
        print("   请设置: export OPENAI_API_KEY=your_api_key")
        return None
    
    try:
        vlm = OpenAIVLM(
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            api_key=api_key
        )
        info = vlm.get_model_info()
        print(f"✅ OpenAI VLM 初始化成功")
        print(f"   模型信息: {info}")
        return vlm
    except Exception as e:
        print(f"❌ OpenAI VLM 初始化失败: {e}")
        return None


def test_image_description(vlm: OpenAIVLM, frame_paths: list):
    """测试图像描述生成"""
    print("\n" + "="*50)
    print("测试 2: 图像描述生成")
    print("="*50)
    
    if not frame_paths:
        print("❌ 没有可用的图像文件")
        return None
    
    print(f"📸 使用 {len(frame_paths)} 张图像生成描述")
    
    try:
        description = vlm.generate_description(frame_paths)
        print(f"✅ 描述生成成功")
        print(f"   描述长度: {len(description)} 个字符")
        print(f"   描述内容: {description}")
        return description
    except Exception as e:
        print(f"❌ 描述生成失败: {e}")
        return None


def test_batch_processing(vlm: OpenAIVLM, splitter: VideoSplitter, video_path: str):
    """测试批量处理"""
    print("\n" + "="*50)
    print("测试 3: 批量处理（切分 + 抽帧 + VLM）")
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
        for i, clip in enumerate(clips[:2]):  # 只处理前 2 个片段
            print(f"\n处理片段 {i+1}/2...")
            
            # 抽帧
            frame_paths = splitter.extract_frames(clip.clip_path, n_frames=3)
            print(f"✅ 抽帧完成: {len(frame_paths)} 张")
            
            # 生成描述
            description = vlm.generate_description(frame_paths)
            results.append({
                "clip_id": i,
                "duration": clip.duration,
                "description_length": len(description),
                "description": description[:100] + "..." if len(description) > 100 else description,
            })
            
            print(f"✅ 片段 {i+1} 处理完成: {len(description)} 个字符")
        
        print(f"\n✅ 批量处理完成: {len(results)} 个片段")
        for result in results:
            print(f"   片段 {result['clip_id']}: {result['description_length']} 字符")
            print(f"   描述: {result['description']}")
        
    except Exception as e:
        print(f"❌ 批量处理失败: {e}")


def main():
    """主测试函数"""
    print("\n" + "="*50)
    print("LX SmartClip Phase 5 - VLM 视觉描述功能测试")
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
    
    # 测试 1: VLM 初始化
    vlm = test_vlm_initialization()
    if not vlm:
        return
    
    # 提取帧用于测试
    print("\n正在提取测试帧...")
    try:
        # 先切分视频
        clips = splitter.split_by_fixed(test_video, duration=10)
        if clips:
            # 从第一个片段抽帧
            frame_paths = splitter.extract_frames(clips[0].clip_path, n_frames=3)
            print(f"✅ 抽帧成功: {len(frame_paths)} 张")
        else:
            print("❌ 没有切分出片段")
            return
    except Exception as e:
        print(f"❌ 抽帧失败: {e}")
        return
    
    # 测试 2: 图像描述生成
    description = test_image_description(vlm, frame_paths)
    
    # 测试 3: 批量处理
    test_batch_processing(vlm, splitter, test_video)
    
    print("\n" + "="*50)
    print("✅ 所有测试完成！")
    print("="*50)


if __name__ == "__main__":
    main()
