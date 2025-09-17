# 小说续写智能助手

基于AI的智能小说续写工具，支持长文本自动总结与续写功能。

## 功能特点

- 🤖 **智能续写**：基于先进的AI模型进行小说续写
- 📏 **自动总结**：超过100k字符的长文本自动总结后再续写
- 🌐 **Web界面**：美观易用的网页界面，支持流式输出
- 📁 **文件支持**：支持直接文本输入和文件上传（.txt、.md格式）
- ⚙️ **自定义要求**：可添加额外的写作要求和字数限制
- 🔄 **多种续写模式**：
  - **继续续写**：基于当前内容继续延伸
  - **重新续写**：重新生成最后一段内容
  - **新任务**：清除所有上下文，开始新的创作
- 💾 **结果保存**：可将续写结果保存为TXT文件

## 安装和设置

### 1. 安装依赖
```bash
pip install flask werkzeug qwen-agent
```

### 2. 配置文件
项目使用了分离的配置结构：

#### config.json - 模型和应用配置
包含两个独立的AI模型配置：
- **summary_bot**: 用于长文本总结
- **writing_bot**: 用于小说续写

#### prompts/文件夹 - AI提示词
- `summary_instruction.txt`: 总结模型的系统提示词
- `writing_instruction.txt`: 写作模型的系统提示词

你可以根据需要修改这些提示词文件来调整AI的行为。

### 3. 运行程序
```bash
python app.py
```

### 4. 访问Web界面
在浏览器中打开：
```
http://localhost:5000
```

## 使用说明

### 作业流程
1. **输入内容**：直接输入或上传小说文件
2. **设置参数**：配置字数限制和额外要求
3. **开始续写**：点击“开始续写”按钮
4. **多轮操作**：使用“继续续写”、“重新续写”或“新任务”
5. **保存结果**：将续写结果保存为TXT文件

### 文本输入方式
1. **直接输入**：在文本框中粘贴小说内容
2. **文件上传**：支持 `.txt` 和 `.md` 格式的文件

### 处理逻辑
- **文本长度 ≤ 100k字符**：直接进行续写
- **文本长度 > 100k字符**：先进行智能总结，再基于总结进行续写

### 续写模式
- **继续续写**：在当前内容基础上继续延伸故事
- **重新续写**：重新生成最后一段内容，探索不同的发展方向
- **新任务**：清除所有上下文，开始全新的创作任务

### 自定义选项
- **字数限制**：100-10000字，默认1000字
- **额外要求**：例如“增加更多对话”、“加强悬疑氛围”等

## 项目结构

```
HLNovel_Writing_Agent/
├── app.py                    # 主程序文件
├── config.json              # 模型和应用配置
├── prompts/                 # AI提示词文件夹
│   ├── summary_instruction.txt   # 总结模型提示词
│   └── writing_instruction.txt   # 写作模型提示词
├── templates/
│   └── index.html           # Web界面模板
├── uploads/                 # 文件上传目录
├── requirements.txt         # 依赖项列表
└── README.md               # 说明文档
```

## 配置说明

### AI模型配置 (config.json)
项目使用两个分离的AI模型：

```json
{
  "llm_config": {
    "summary_bot": {
      "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
      "model_server": "https://api.siliconflow.cn/v1",
      "api_key": "your_api_key_here",
      "generate_cfg": {
        "top_p": 0.9,
        "temperature": 0.3,
        "max_tokens": 256000
      }
    },
    "writing_bot": {
      "model": "deepseek/deepseek-chat-v3.1:free",
      "model_server": "https://openrouter.ai/api/v1",
      "api_key": "your_api_key_here",
      "generate_cfg": {
        "top_p": 0.8,
        "temperature": 0.7,
        "max_tokens": 32000
      }
    }
  },
  "app_config": {
    "text_length_threshold": 100000,
    "max_file_size_mb": 50,
    "upload_folder": "uploads",
    "host": "0.0.0.0",
    "port": 5000,
    "debug": false
  }
}
```

### AI提示词配置 (prompts/)
你可以通过修改prompts文件夹中的文件来调整AI的行为：

- **summary_instruction.txt**: 总结模型的系统提示词，控制如何总结长文本
- **writing_instruction.txt**: 写作模型的系统提示词，控制续写风格和质量

### 服务器配置
- 端口：默认5000
- 最大文件大小：50MB
- 上传文件夹：uploads/

## 故障排除

### 1. 依赖安装错误
```bash
pip install flask werkzeug qwen-agent
```

### 2. 配置文件错误
- 确保 `config.json` 文件存在且格式正确
- 确保 `prompts/` 文件夹存在
- 检查 `prompts/summary_instruction.txt` 和 `prompts/writing_instruction.txt` 文件是否存在

### 3. AI模型连接失败
- 检查API密钥是否正确
- 确认模型服务地址可访问
- 查看网络连接和防火墙设置

### 4. 文件上传失败
- 检查文件格式（仅支持.txt和.md）
- 确保文件大小不超过50MB
- 检查文件编码（建议使用UTF-8）

### 5. 流式输出错误
- 检查浏览器控制台是否有JavaScript错误
- 尝试刷新页面或清除浏览器缓存

## 技术栈

- **后端**：Python + Flask
- **前端**：HTML + CSS + JavaScript
- **AI模型**：Qwen Agent（支持多个云服务商）
- **文件处理**：Werkzeug
- **流式输出**：Server-Sent Events (SSE)

## 开发者说明

### 核心组件

1. **总结智能体 (summary_bot)**：负责长文本的智能总结
2. **写作智能体 (writing_bot)**：负责小说续写
3. **Flask服务器**：处理Web请求和文件上传
4. **流式输出系统**：实时显示AI生成内容
5. **会话管理**：支持多轮续写和上下文管理

### API接口

- `GET /`：返回主页面
- `POST /process`：处理文本续写请求
- `GET /stream/<session_id>`：流式输出初次续写
- `GET /continue/<session_id>`：流式输出继续续写
- `GET /restart/<session_id>`：流式输出重新续写
- `POST /clear/<session_id>`：清除会话数据

### 特色功能

- **实时流式输出**：使用SSE技术实现打字机效果
- **分段管理**：每次续写的内容独立存储，支持精确回退
- **参数实时更新**：每次操作都会读取最新的字数限制和要求
- **上下文管理**：支持清除所有上下文，开始新任务

### 扩展建议

- 添加更多文件格式支持
- 实现续写历史记录
- 添加用户认证系统
- 支持批量文件处理
- 添加续写风格选择
- 实现多语言支持

## 许可证

本项目仅供学习和研究使用。