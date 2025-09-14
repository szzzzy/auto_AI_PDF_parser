📚 auto_ai_pdf_parser — 智能作业/试卷处理器

📚 auto_ai_pdf_parser — Intelligent Homework/Test Processor

中文说明
English Description

auto_ai_pdf_parser 是一个基于 Python 的智能作业处理系统
auto_ai_pdf_parser is an intelligent homework processing system based on Python

能够自动监控文件夹、解析 PDF 文件并调用 AI 进行题目解答
It automatically monitors folders, parses PDF files, and uses AI to solve questions

⸻

🚀 主要功能 / Key Features

功能 / Feature	说明 / Description
📁 文件夹监控	自动监控指定文件夹（默认 D:\homework）中的 PDF 文件 / Automatically monitors specified folder (default: D:\homework) for PDF files
📄 PDF解析	使用 PyMuPDF 提取 PDF 中的文本和图片 / Extracts text and images from PDFs using PyMuPDF
🧠 题目识别	调用多模态 AI（Qwen）识别题目结构和大题小题关系 / Uses multimodal AI (Qwen) to identify question structure and relationships
🤖 自动答题	对每道大题一次性调用 AI，获取所有小题的答案和解析 / Calls AI once per major question to get answers for all subquestions
💾 保存结果	将结构化结果保存为 JSON 文件 / Saves structured results as JSON files
🔄 错误处理	完整的错误处理和日志记录系统 / Includes complete error handling and logging system


⸻

⚡ 快速开始 / Quick Start

# 1. 克隆项目 / Clone the project
git clone https://github.com/your-username/auto_ai_pdf_parser.git
cd auto_ai_pdf_parser

# 2. 创建虚拟环境并安装依赖 / Create virtual environment and install dependencies
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 3. 创建环境配置文件 / Create environment configuration file
# 编辑 .env 文件 / Edit .env file
QWEN_API=your_api_key_here
HOMEWORK_FOLDER=D:\homework

# 4. 运行程序 / Run the program
python homework_ai.py


⸻

⚠️ 注意事项 / Important Notes
	•	请不要将真实的 API 密钥提交到 GitHub / Do not commit real API keys to GitHub
	•	确保监控文件夹路径存在且有读写权限 / Ensure the monitoring folder path exists and has read/write permissions
	•	系统会自动处理 PDF 并保存结果到 results 文件夹 / The system automatically processes PDFs and saves results to the results folder

⸻

🛠 技术栈 / Technology Stack

技术 / Technology	用途 / Usage
Python	主编程语言 / Main programming language
PyMuPDF (fitz)	PDF 解析 / PDF parsing
Qwen-VL	多模态 AI 模型 / Multimodal AI model
Watchdog	文件系统监控 / File system monitoring
Pillow (PIL)	图像处理 / Image processing


⸻

📄 许可证 / License

MIT License - 详见 LICENSE 文件 / See LICENSE file for details

⸻

🔮 后续更新计划 / Future Updates
	•	⚡ 并行处理多道大题，提高整体处理速度 / Parallel processing of multiple major questions to speed up processing
	•	📝 支持更多文件格式（Word、扫描版 PDF） / Support more file formats (Word, scanned PDFs)
	•	⏱ 优化 AI 调用策略，减少重复请求和等待 / Optimize AI request strategy to reduce redundant calls and waiting time
	•	🖼 增加图像题目识别和解答功能 / Add support for image-based questions
	•	🎨 提供可视化界面，方便查看题目解析 / Provide GUI interface for easier viewing of answers

⸻