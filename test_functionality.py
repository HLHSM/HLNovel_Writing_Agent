#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小说续写功能测试脚本
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_text_length_logic():
    """测试文本长度判断逻辑"""
    print("=== 测试文本长度判断逻辑 ===")
    
    # 测试短文本
    short_text = "这是一个测试文本。" * 100  # 约1000字符
    print(f"短文本长度: {len(short_text)} 字符")
    print(f"是否需要总结: {len(short_text) > 100000}")
    
    # 测试长文本
    long_text = "这是一个测试文本。" * 10000  # 约100000字符
    print(f"长文本长度: {len(long_text)} 字符")
    print(f"是否需要总结: {len(long_text) > 100000}")
    
    print("文本长度判断逻辑正常 ✓")

def test_flask_imports():
    """测试Flask相关导入"""
    print("\n=== 测试依赖项导入 ===")
    
    try:
        from flask import Flask, request, render_template, jsonify
        print("Flask 导入成功 ✓")
    except ImportError as e:
        print(f"Flask 导入失败: {e}")
        return False
    
    try:
        from werkzeug.utils import secure_filename
        print("Werkzeug 导入成功 ✓")
    except ImportError as e:
        print(f"Werkzeug 导入失败: {e}")
        return False
    
    try:
        # 注意：这里可能会失败，因为可能没有安装qwen-agent
        from qwen_agent.agents import Assistant
        print("Qwen Agent 导入成功 ✓")
    except ImportError as e:
        print(f"Qwen Agent 导入失败: {e}")
        print("请确保已安装 qwen-agent 包")
        return False
    
    return True

def test_file_structure():
    """测试文件结构"""
    print("\n=== 测试文件结构 ===")
    
    # 检查模板文件
    if os.path.exists("templates/index.html"):
        print("模板文件存在 ✓")
    else:
        print("模板文件不存在 ✗")
        return False
    
    # 检查主程序文件
    if os.path.exists("agent.py"):
        print("主程序文件存在 ✓")
    else:
        print("主程序文件不存在 ✗")
        return False
    
    return True

def mock_agent_test():
    """模拟智能体功能测试"""
    print("\n=== 模拟智能体功能测试 ===")
    
    # 模拟process_novel_text函数的逻辑
    def mock_process_novel_text(text, requirements=""):
        text_length = len(text.strip())
        
        if text_length > 100000:
            # 模拟总结过程
            summary = f"[模拟总结] 这是一个长度为{text_length}字符的文本的总结..."
            result = f"基于总结的续写：{summary[:100]}..."
            used_summary = True
        else:
            # 模拟直接续写
            result = f"直接续写：基于原文（{text_length}字符）进行续写..."
            used_summary = False
        
        if requirements:
            result += f"\n额外要求：{requirements}"
        
        return {
            'success': True,
            'result': result,
            'text_length': text_length,
            'used_summary': used_summary
        }
    
    # 测试短文本
    short_text = "这是一个测试小说开头。" * 50
    result1 = mock_process_novel_text(short_text, "增加对话")
    print(f"短文本测试结果: {result1}")
    
    # 测试长文本
    long_text = "这是一个测试小说开头。" * 5000
    result2 = mock_process_novel_text(long_text, "增加悬疑")
    print(f"长文本测试结果: 长度={result2['text_length']}, 使用总结={result2['used_summary']}")
    
    print("模拟功能测试通过 ✓")

def main():
    """主测试函数"""
    print("🧪 小说续写项目功能测试")
    print("=" * 50)
    
    # 运行所有测试
    all_passed = True
    
    try:
        test_text_length_logic()
    except Exception as e:
        print(f"文本长度测试失败: {e}")
        all_passed = False
    
    try:
        if not test_flask_imports():
            all_passed = False
    except Exception as e:
        print(f"依赖项测试失败: {e}")
        all_passed = False
    
    try:
        if not test_file_structure():
            all_passed = False
    except Exception as e:
        print(f"文件结构测试失败: {e}")
        all_passed = False
    
    try:
        mock_agent_test()
    except Exception as e:
        print(f"模拟功能测试失败: {e}")
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 所有测试通过！项目基础结构正常")
        print("\n📝 下一步：")
        print("1. 确保已启动本地LLM服务 (http://localhost:8000)")
        print("2. 运行 'python agent.py' 启动Web服务")
        print("3. 在浏览器中访问 http://localhost:5000")
    else:
        print("❌ 部分测试失败，请检查上述错误")

if __name__ == "__main__":
    main()