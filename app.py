#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小说续写Web应用
基于Flask和Qwen Agent的智能小说续写系统
"""

import os
import json
import traceback
from flask import Flask, request, render_template, jsonify, Response, session
from werkzeug.utils import secure_filename
import uuid
import time

# 导入qwen_agent
from qwen_agent.agents import Assistant

# 用于存储会话数据的内存字典（生产环境建议使用Redis等）
session_storage = {}

# 读取配置文件
def load_config():
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件 {config_path} 不存在，请确保config.json文件存在")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"配置文件格式错误: {e}")
    
    # 验证必需的配置项
    required_keys = ['llm_config', 'instructions', 'app_config']
    for key in required_keys:
        if key not in config:
            raise KeyError(f"配置文件缺少必需项: {key}")
    
    # 验证llm_config结构
    llm_config = config['llm_config']
    if 'summary_bot' not in llm_config:
        raise KeyError("配置文件缺少 llm_config.summary_bot 配置")
    if 'writing_bot' not in llm_config:
        raise KeyError("配置文件缺少 llm_config.writing_bot 配置")
    
    # 验证每个bot的必需配置
    for bot_name in ['summary_bot', 'writing_bot']:
        bot_config = llm_config[bot_name]
        required_bot_keys = ['model', 'model_server', 'api_key', 'generate_cfg']
        for key in required_bot_keys:
            if key not in bot_config:
                raise KeyError(f"配置文件缺少 llm_config.{bot_name}.{key} 配置")
    
    return config



# 加载配置
try:
    config = load_config()
    summary_llm_cfg = config['llm_config']['summary_bot']
    writing_llm_cfg = config['llm_config']['writing_bot']
    summary_instruction = config['instructions']['summary_instruction']
    writing_instruction = config['instructions']['writing_instruction']
    app_config = config['app_config']
    
    print(f"✓ 配置加载成功")
    print(f"  总结模型: {summary_llm_cfg['model']} (top_p: {summary_llm_cfg['generate_cfg']['top_p']})")
    print(f"  写作模型: {writing_llm_cfg['model']} (top_p: {writing_llm_cfg['generate_cfg']['top_p']})")
    print(f"  服务器: {summary_llm_cfg['model_server']}")
    print(f"  文本长度阈值: {app_config['text_length_threshold']}")
except Exception as e:
    print(f"❌ 配置加载失败: {e}")
    print("请确保 config.json 文件存在且格式正确")
    exit(1)

# 创建智能体
try:
    summary_bot = Assistant(llm=summary_llm_cfg, system_message=summary_instruction)
    writing_bot = Assistant(llm=writing_llm_cfg, system_message=writing_instruction)
    print("✓ AI智能体初始化成功")
except Exception as e:
    print(f"❌ AI智能体初始化失败: {e}")
    print("请检查配置是否正确以及qwen-agent是否正确安装")
    exit(1)

# 创建Flask应用
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = app_config['max_file_size_mb'] * 1024 * 1024  # 转换为字节
app.config['UPLOAD_FOLDER'] = app_config['upload_folder']
app.secret_key = 'novel_writing_agent_secret_key_2024'  # 用于session管理

# 确保上传文件夹存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def count_chinese_chars(text):
    """计算文本中的字符数（主要针对中文）"""
    return len(text.strip())



def typewriter_print_streaming(response, current_text=""):
    """流式输出打字机效果"""
    if isinstance(response, list):
        for msg in response:
            if isinstance(msg, dict) and 'content' in msg:
                new_content = msg['content']
                # 只输出新增的部分
                if new_content.startswith(current_text):
                    yield new_content[len(current_text):]
                else:
                    yield new_content
                current_text = new_content
    elif isinstance(response, dict) and 'content' in response:
        new_content = response['content']
        if new_content.startswith(current_text):
            yield new_content[len(current_text):]
        else:
            yield new_content

def call_agent_safely(agent, text):
    """调用AI智能体"""
    messages = [{'role': 'user', 'content': text}]
    
    # 调用智能体
    response_content = ""
    for response in agent.run(messages=messages):
        if isinstance(response, list):
            for msg in response:
                if isinstance(msg, dict) and 'content' in msg:
                    response_content = msg['content']
                    break
        elif isinstance(response, dict) and 'content' in response:
            response_content = response['content']
            break
    
    return response_content if response_content else "响应为空，请重试"

def call_agent_streaming(agent, text):
    """流式调用AI智能体"""
    messages = [{'role': 'user', 'content': text}]
    
    current_text = ""
    for response in agent.run(messages=messages):
        for chunk in typewriter_print_streaming(response, current_text):
            if chunk:  # 只输出非空内容
                current_text += chunk
                yield chunk
        
        # 更新当前文本状态
        if isinstance(response, list):
            for msg in response:
                if isinstance(msg, dict) and 'content' in msg:
                    current_text = msg['content']
                    break
        elif isinstance(response, dict) and 'content' in response:
            current_text = response['content']

def process_novel_text(text, additional_requirements=""):
    """处理小说文本的主要逻辑"""
    text_length = count_chinese_chars(text)
    
    try:
        # 如果文本长度超过阈值，先进行总结
        if text_length > app_config['text_length_threshold']:
            print(f"文本长度: {text_length}，超过{app_config['text_length_threshold']}，先进行总结...")
            
            summary_text = call_agent_safely(summary_bot, text)
            
            # 将总结内容和额外要求一起发送给写作智能体
            writing_input = f"根据以下小说总结进行续写：\n\n{summary_text}"
            if additional_requirements:
                writing_input += f"\n\n额外写作要求：{additional_requirements}"
        else:
            print(f"文本长度: {text_length}，直接进行续写...")
            # 直接使用写作智能体
            writing_input = f"请基于以下小说内容进行续写：\n\n{text}"
            if additional_requirements:
                writing_input += f"\n\n额外写作要求：{additional_requirements}"
        
        # 使用写作智能体进行续写
        result = call_agent_safely(writing_bot, writing_input)
        
        return {
            'success': True,
            'result': result,
            'text_length': text_length,
            'used_summary': text_length > app_config['text_length_threshold']
        }
        
    except Exception as e:
        print(f"处理过程中出现错误: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return {
            'success': False,
            'error': f'处理过程中出现错误: {str(e)}',
            'text_length': text_length
        }

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/debug/sessions')
def debug_sessions():
    """调试用的会话查看接口"""
    return jsonify({
        'active_sessions': list(session_storage.keys()),
        'session_count': len(session_storage)
    })

@app.route('/process', methods=['POST'])
def process_text():
    """处理文本续写请求"""
    try:
        # 获取文本内容
        text_content = ""
        additional_requirements = request.form.get('requirements', '')
        
        # 检查是否有直接输入的文本
        if 'text_input' in request.form and request.form['text_input'].strip():
            text_content = request.form['text_input']
        
        # 检查是否有上传的文件
        elif 'file' in request.files:
            file = request.files['file']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                # 读取文件内容
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                except UnicodeDecodeError:
                    # 尝试其他编码
                    try:
                        with open(filepath, 'r', encoding='gbk') as f:
                            text_content = f.read()
                    except UnicodeDecodeError:
                        return jsonify({
                            'success': False,
                            'error': '文件编码不支持，请使用UTF-8或GBK编码的文本文件'
                        })
                finally:
                    # 删除临时文件
                    if os.path.exists(filepath):
                        os.remove(filepath)
        
        if not text_content.strip():
            return jsonify({
                'success': False,
                'error': '请输入文本内容或上传文件'
            })
        
        # 存储原始文本到session中以便续写操作
        session_id = str(uuid.uuid4())
        session_storage[session_id] = {
            'original_text': text_content,
            'additional_requirements': additional_requirements,
            'generated_segments': [],  # 存储多个续写段落
            'text_length': count_chinese_chars(text_content)
        }
        
        # 返回基本信息和会话ID
        return jsonify({
            'success': True,
            'session_id': session_id,
            'text_length': session_storage[session_id]['text_length'],
            'used_summary': session_storage[session_id]['text_length'] > app_config['text_length_threshold']
        })
        
    except Exception as e:
        print(f"请求处理错误: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'处理过程中出现错误: {str(e)}'
        })

@app.route('/stream/<session_id>')
def stream_writing(session_id):
    """流式输出续写内容"""
    if session_id not in session_storage:
        return Response("session not found", status=404)
    
    session_data = session_storage[session_id]
    
    def generate():
        try:
            text_content = session_data['original_text']
            additional_requirements = session_data['additional_requirements']
            word_limit = session_data.get('word_limit', '1000')
            text_length = session_data['text_length']
            
            # 根据文本长度决定处理方式
            if text_length > app_config['text_length_threshold']:
                print(f"文本长度: {text_length}，超过{app_config['text_length_threshold']}，先进行总结...")
                
                # 先发送状态信息
                yield f"data: {json.dumps({'type': 'status', 'content': '正在进行智能总结...'})}\n\n"
                
                summary_text = call_agent_safely(summary_bot, text_content)
                
                yield f"data: {json.dumps({'type': 'status', 'content': '总结完成，开始续写...'})}\n\n"
                
                # 将总结内容和额外要求一起发送给写作智能体
                writing_input = f"根据以下小说总结进行续写：\n\n{summary_text}"
                if additional_requirements:
                    writing_input += f"\n\n额外写作要求：{additional_requirements}"
                writing_input += f"\n\n期望续写字数为：{word_limit}字"
            else:
                print(f"文本长度: {text_length}，直接进行续写...")
                yield f"data: {json.dumps({'type': 'status', 'content': '正在生成续写内容...'})}\n\n"
                
                # 直接使用写作智能体
                writing_input = f"请基于以下小说内容进行续写：\n\n{text_content}"
                if additional_requirements:
                    writing_input += f"\n\n额外写作要求：{additional_requirements}"
                writing_input += f"\n\n期望续写字数为：{word_limit}字"
            
            # 流式输出续写结果
            current_segment = ""
            for chunk in call_agent_streaming(writing_bot, writing_input):
                current_segment += chunk
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                time.sleep(0.01)  # 小延迟模拟打字效果
            
            # 添加分割线
            separator = "\n" + "-" * 50 + "\n"
            yield f"data: {json.dumps({'type': 'content', 'content': separator})}\n\n"
            
            # 保存当前段落
            session_data['generated_segments'].append(current_segment)
            
            # 发送完成信号
            yield f"data: {json.dumps({'type': 'complete', 'content': '续写完成'})}\n\n"
            
        except Exception as e:
            error_msg = f'处理过程中出现错误: {str(e)}'
            print(f"流式输出错误: {e}")
            print(f"错误详情: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Cache-Control'
    })

@app.route('/continue/<session_id>')
def continue_writing(session_id):
    """继续续写功能"""
    if session_id not in session_storage:
        return Response("session not found", status=404)
    
    # 在请求上下文中获取URL参数
    session_data = session_storage[session_id]
    word_limit = request.args.get('word_limit', session_data.get('word_limit', '1000'))
    additional_requirements = request.args.get('requirements', session_data.get('additional_requirements', ''))
    
    def generate():
        try:
            # 更新会话中的信息
            session_data['word_limit'] = word_limit
            session_data['additional_requirements'] = additional_requirements
            
            # 获取当前已生成的内容
            all_generated_content = '\n'.join(session_data['generated_segments'])
            original_text = session_data['original_text']
            
            # 构建继续续写的输入
            continue_input = f"以下是之前的小说内容和已续写部分：\n\n原文：\n{original_text}\n\n已续写内容：\n{all_generated_content}\n\n请继续续写。"
            if additional_requirements:
                continue_input += f"\n\n额外要求：{additional_requirements}"
            continue_input += f"\n\n期望续写字数为：{word_limit}字"
            
            yield f"data: {json.dumps({'type': 'status', 'content': '正在继续续写...'})}\n\n"
            
            # 流式输出继续续写的结果
            current_segment = ""
            for chunk in call_agent_streaming(writing_bot, continue_input):
                current_segment += chunk
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                time.sleep(0.01)
            
            # 添加分割线
            separator = "\n" + "-" * 50 + "\n"
            yield f"data: {json.dumps({'type': 'content', 'content': separator})}\n\n"
            
            # 保存当前段落
            session_data['generated_segments'].append(current_segment)
            
            yield f"data: {json.dumps({'type': 'complete', 'content': '继续续写完成'})}\n\n"
            
        except Exception as e:
            error_msg = f'继续续写过程中出现错误: {str(e)}'
            print(f"继续续写错误: {e}")
            print(f"错误详情: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Cache-Control'
    })

@app.route('/restart/<session_id>')
def restart_writing(session_id):
    """重新续写功能"""
    if session_id not in session_storage:
        return Response("session not found", status=404)
    
    # 回退最后一个续写段落（如果有的话）
    if session_storage[session_id]['generated_segments']:
        session_storage[session_id]['generated_segments'].pop()
    
    # 在请求上下文中获取URL参数
    session_data = session_storage[session_id]
    word_limit = request.args.get('word_limit', session_data.get('word_limit', '1000'))
    additional_requirements = request.args.get('requirements', session_data.get('additional_requirements', ''))
    
    def generate():
        try:
            text_content = session_data['original_text']
            text_length = session_data['text_length']
            
            # 更新会话中的信息
            session_data['word_limit'] = word_limit
            session_data['additional_requirements'] = additional_requirements
            
            # 获取当前所有续写段落作为上下文
            all_generated_content = '\n'.join(session_data['generated_segments'])
            
            # 根据文本长度决定处理方式
            if text_length > app_config['text_length_threshold']:
                yield f"data: {json.dumps({'type': 'status', 'content': '正在重新进行智能总结...'})}\n\n"
                
                # 如果有续写内容，包含在总结中
                if all_generated_content:
                    full_content = text_content + "\n\n" + all_generated_content
                    summary_text = call_agent_safely(summary_bot, full_content)
                else:
                    summary_text = call_agent_safely(summary_bot, text_content)
                
                yield f"data: {json.dumps({'type': 'status', 'content': '总结完成，开始重新续写...'})}\n\n"
                
                writing_input = f"根据以下小说总结进行续写：\n\n{summary_text}"
                if additional_requirements:
                    writing_input += f"\n\n额外写作要求：{additional_requirements}"
                writing_input += f"\n\n期望续写字数为：{word_limit}字"
            else:
                yield f"data: {json.dumps({'type': 'status', 'content': '正在重新生成续写内容...'})}\n\n"
                
                # 如果有续写内容，包含在输入中
                if all_generated_content:
                    writing_input = f"请基于以下小说内容进行重新续写：\n\n原文：\n{text_content}\n\n已有续写：\n{all_generated_content}\n\n请重新续写最后一部分。"
                else:
                    writing_input = f"请基于以下小说内容进行续写：\n\n{text_content}"
                if additional_requirements:
                    writing_input += f"\n\n额外写作要求：{additional_requirements}"
                writing_input += f"\n\n期望续写字数为：{word_limit}字"
            
            # 流式输出新的续写结果
            current_segment = ""
            for chunk in call_agent_streaming(writing_bot, writing_input):
                current_segment += chunk
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                time.sleep(0.01)
            
            # 添加分割线
            separator = "\n" + "-" * 50 + "\n"
            yield f"data: {json.dumps({'type': 'content', 'content': separator})}\n\n"
            
            # 保存当前段落
            session_data['generated_segments'].append(current_segment)
            
            yield f"data: {json.dumps({'type': 'complete', 'content': '重新续写完成'})}\n\n"
            
        except Exception as e:
            error_msg = f'重新续写过程中出现错误: {str(e)}'
            print(f"重新续写错误: {e}")
            print(f"错误详情: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Cache-Control'
    })

@app.route('/clear/<session_id>', methods=['POST'])
def clear_session(session_id):
    """清除会话数据"""
    if session_id in session_storage:
        del session_storage[session_id]
        return jsonify({'success': True, 'message': '会话已清除'})
    else:
        return jsonify({'success': False, 'message': '会话不存在'})

if __name__ == '__main__':
    print("🚀 小说续写服务启动中...")
    print("🌐 请在浏览器中访问: http://{}:{}".format(app_config['host'], app_config['port']))
    print("📝 支持功能：")
    print("   • 文本直接输入和文件上传")
    print("   • 自动判断文本长度（{}字符阈值）".format(app_config['text_length_threshold']))
    print("   • 长文本智能总结后续写")
    print("   • 短文本直接续写")
    print("   • 自定义写作要求")
    print("   • 保存续写结果为TXT文件")
    print("\n" + "="*50)
    
    app.run(debug=app_config['debug'], host=app_config['host'], port=app_config['port'])