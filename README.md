# 小说续写智能助手

基于AI的智能小说续写工具，支持长文本自动总结与续写功能。

## 功能特点

- 🤖 **智能续写**：基于先进的AI模型进行小说续写
- 📏 **自动总结**：超过100k字符的长文本自动总结后再续写
- 🌐 **Web界面**：美观易用的网页界面
- 📁 **文件支持**：支持直接文本输入和文件上传
- ⚙️ **自定义要求**：可添加额外的写作要求

## 安装和设置

### 1. 安装依赖
```bash
pip install flask werkzeug qwen-agent
```

### 2. 启动本地LLM服务
确保您已经启动了本地LLM服务，默认地址为：
```
http://localhost:8000/v1
```

如果您的服务地址不同，请修改 `agent.py` 中的 `llm_cfg` 配置。

### 3. 运行程序
```bash
python agent.py
```

### 4. 访问Web界面
在浏览器中打开：
```
http://localhost:5000
```

## 使用说明

### 文本输入方式
1. **直接输入**：在文本框中粘贴小说内容
2. **文件上传**：支持 `.txt` 和 `.md` 格式的文件

### 处理逻辑
- **文本长度 ≤ 100k字符**：直接进行续写
- **文本长度 > 100k字符**：先进行智能总结，再基于总结进行续写

### 额外要求
可以在"额外写作要求"文本框中输入特殊要求，例如：
- 增加更多对话
- 加强悬疑氛围  
- 重点描写人物心理
- 推进主线剧情

## 项目结构

```
HLNovel_Writing_Agent/
├── agent.py              # 主程序文件
├── templates/
│   └── index.html        # Web界面模板
├── requirements.txt      # 依赖项列表
├── test_functionality.py # 功能测试脚本
└── README.md            # 说明文档
```

## 配置说明

在 `agent.py` 中可以修改以下配置：

### LLM配置
```python
llm_cfg = {
    'model': 'Qwen2.5-7B-Instruct',
    'model_server': 'http://localhost:8000/v1',
    'api_key': 'EMPTY',
    'generate_cfg': {
        'top_p': 0.8
    }
}
```

### 服务器配置
- 端口：默认5000
- 最大文件大小：50MB
- 上传文件夹：uploads/

## 故障排除

### 1. Flask导入错误
```bash
pip install flask
```

### 2. qwen-agent导入错误
```bash
pip install qwen-agent
```

### 3. LLM服务连接失败
- 确保本地LLM服务正在运行
- 检查服务地址和端口是否正确
- 查看防火墙设置

### 4. 文件上传失败
- 检查文件格式（仅支持.txt和.md）
- 确保文件大小不超过50MB
- 检查文件编码（建议使用UTF-8）

## 技术栈

- **后端**：Python + Flask
- **前端**：HTML + CSS + JavaScript
- **AI模型**：Qwen Agent
- **文件处理**：Werkzeug

## 开发者说明

### 核心组件

1. **总结智能体 (summary_bot)**：负责长文本的智能总结
2. **写作智能体 (writing_bot)**：负责小说续写
3. **Flask服务器**：处理Web请求和文件上传
4. **文本处理逻辑**：判断文本长度并选择处理方式

### API接口

- `GET /`：返回主页面
- `POST /process`：处理文本续写请求

### 扩展建议

- 添加更多文件格式支持
- 实现续写历史记录
- 添加用户认证系统
- 支持批量文件处理
- 添加续写风格选择

## 许可证

本项目仅供学习和研究使用。