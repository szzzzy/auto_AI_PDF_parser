import os
import time
import json
import re
import logging
import base64
from datetime import datetime
from pathlib import Path
from io import BytesIO
from dataclasses import dataclass
from typing import List, Tuple, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import fitz  # PyMuPDF
from PIL import Image
from openai import OpenAI

# ================== 配置 ==================
class Config:
    # 文件夹设置
    HOMEWORK_FOLDER = r"D:\homework"  # 主监控文件夹路径
    RESULTS_FOLDER = "results"  # 处理结果保存文件夹
    PROCESSING_FOLDER = "processing"  # 处理中文件暂存文件夹

    # API设置
    MODEL = "qwen-vl-max"  # 使用的AI模型名称（支持多模态）
    TEMPERATURE = 0.3  # AI生成内容的随机性控制
    API_RETRY_TIMES = 3  # API调用失败重试次数
    API_RETRY_DELAY = 2  # API重试间隔时间（秒）

    # 图片设置
    IMAGE_MAX_SIZE = (512, 512)  # 图片最大尺寸限制
    IMAGE_QUALITY = 80  # 图片压缩质量（0-100）

    # 支持的文件格式
    SUPPORTED_FORMATS = ['.pdf']  # 系统支持处理的文件格式

# ================== 数据结构 ==================
@dataclass
class PageElement:
    """页面元素数据类，用于存储PDF中的文本和图片元素"""
    type: str  # 元素类型："text" | "image" | "page_image"
    content: str  # 内容：文本内容 or base64编码的图片
    bbox: Tuple[float, float, float, float]  # 元素边界框位置坐标
    page_num: int  # 元素所在页码
    center_y: float = 0  # 元素中心Y坐标，用于排序
    
    def __post_init__(self):
        # 初始化后自动计算元素的中心Y坐标
        self.center_y = (self.bbox[1] + self.bbox[3]) / 2

class Question:
    """题目类，用于存储识别出的题目信息"""
    def __init__(self, question_id, text, images=None, page_nums=None, elements=None):
        self.id = question_id  # 题目编号
        self.text = text  # 题目文本内容
        self.images = images or []  # 题目相关图片列表
        self.page_nums = page_nums or []  # 题目所在页码列表
        self.related_elements = elements or []  # 题目相关元素列表

# ================== 系统初始化 ==================
def setup_directories():
    """创建必要的文件夹结构"""
    base_path = Path(Config.HOMEWORK_FOLDER)
    results_path = base_path / Config.RESULTS_FOLDER
    processing_path = base_path / Config.PROCESSING_FOLDER

    # 确保所有需要的文件夹都存在
    for path in [base_path, results_path, processing_path]:
        path.mkdir(parents=True, exist_ok=True)

    print(f"📁 文件夹结构:")
    print(f"   主目录: {base_path}")
    print(f"   结果目录: {results_path}")
    print(f"   处理目录: {processing_path}")

def setup_logging():
    """设置日志记录系统"""
    log_path = Path(Config.HOMEWORK_FOLDER) / "homework_system.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),  # 文件日志
            logging.StreamHandler()  # 控制台日志
        ]
    )
    return logging.getLogger("SmartHomeworkLogger")

def init_client(logger):
    """初始化AI API客户端"""
    QWEN_API = os.getenv("QWEN_API")
    if not QWEN_API:
        raise ValueError("❌ 请设置环境变量 QWEN_API")
    logger.info("Qwen客户端初始化成功")
    # 创建OpenAI兼容客户端，指向阿里云DashScope服务
    return OpenAI(api_key=QWEN_API, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

# ================== 智能作业处理器 ==================
class SmartHomeworkProcessor:
    """智能作业处理核心类，负责PDF解析和AI交互（已改：按整道题分组后再调用API）"""
    def __init__(self, logger):
        self.logger = logger
        self.client = init_client(logger)

    # ----------- 压缩图片（保持不变） -----------
    def compress_image(self, img: Image.Image) -> Image.Image:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.thumbnail(Config.IMAGE_MAX_SIZE, Image.Resampling.LANCZOS)
        return img

    # ----------- 提取PDF元素（保持不变） -----------
    def extract_page_elements(self, pdf_path: str) -> List[PageElement]:
        self.logger.info("🔍 开始提取PDF元素...")
        all_elements: List[PageElement] = []
        try:
            doc = fitz.open(pdf_path)
            for page_num in range(doc.page_count):
                page = doc[page_num]
                self.logger.info(f"=== 处理第 {page_num + 1} 页 ===")
                text_dict = page.get_text("dict")
                page_text_parts = []
                for block in text_dict.get("blocks", []):
                    if "lines" in block:
                        block_text = ""
                        for line in block["lines"]:
                            for span in line.get("spans", []):
                                block_text += span.get("text", "")
                            block_text += "\n"
                        if block_text.strip():
                            page_text_parts.append(block_text.strip())
                if not page_text_parts:
                    simple_text = page.get_text("text")
                    if simple_text.strip():
                        page_text_parts.append(simple_text.strip())
                if not page_text_parts:
                    blocks = page.get_text("blocks")
                    for block in blocks:
                        if len(block) >= 5 and block[4].strip():
                            page_text_parts.append(block[4].strip())
                if page_text_parts:
                    full_text = "\n\n".join(page_text_parts)
                    all_elements.append(PageElement("text", full_text, (0,0,page.rect.width,page.rect.height), page_num+1))
                    self.logger.info(f"📝 文本长度: {len(full_text)} 字符")
                else:
                    self.logger.warning("⚠️ 本页未提取到文本内容")

                images = page.get_images(full=True)
                self.logger.info(f"🖼️ 发现 {len(images)} 个嵌入图片")
                for img_index, img in enumerate(images):
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        img_data = base_image["image"]
                        pil_img = Image.open(BytesIO(img_data))
                        pil_img = self.compress_image(pil_img)
                        buffered = BytesIO()
                        pil_img.save(buffered, format="JPEG", quality=Config.IMAGE_QUALITY)
                        img_base64 = base64.b64encode(buffered.getvalue()).decode()
                        all_elements.append(PageElement("image", img_base64, (0,0,pil_img.size[0], pil_img.size[1]), page_num+1))
                    except Exception as e:
                        self.logger.warning(f"❌ 图片 {img_index+1} 处理失败: {e}")

                if not images:
                    try:
                        mat = fitz.Matrix(2.0, 2.0)
                        pix = page.get_pixmap(matrix=mat)
                        img_data = pix.tobytes("png")
                        pil_img = Image.open(BytesIO(img_data))
                        pil_img = self.compress_image(pil_img)
                        buffered = BytesIO()
                        pil_img.save(buffered, format="JPEG", quality=Config.IMAGE_QUALITY)
                        img_base64 = base64.b64encode(buffered.getvalue()).decode()
                        all_elements.append(PageElement("page_image", img_base64, (0,0,pil_img.size[0], pil_img.size[1]), page_num+1))
                        self.logger.info(f"📄 页面截图已添加 (页 {page_num+1})")
                    except Exception as e:
                        self.logger.warning(f"❌ 页面截图失败: {e}")

            doc.close()
            self.logger.info(f"✅ 提取完成，共 {len(all_elements)} 个元素")
            return all_elements
        except Exception as e:
            self.logger.error(f"PDF提取失败: {e}")
            return []

    # ----------- 安全API调用（保持不变） -----------
    def safe_api_call(self, messages):
        for attempt in range(Config.API_RETRY_TIMES):
            try:
                response = self.client.chat.completions.create(
                    model=Config.MODEL,
                    messages=messages,
                    temperature=Config.TEMPERATURE
                )
                return response.choices[0].message.content
            except Exception as e:
                self.logger.warning(f"API调用失败 (尝试{attempt+1}): {e}")
                if attempt < Config.API_RETRY_TIMES - 1:
                    time.sleep(Config.API_RETRY_DELAY)
        return f"❌ API调用最终失败"

    # ----------- 构建多模态消息（保持不变） -----------
    def build_multimodal_content(self, elements):
        content = []
        for element in elements:
            if element.type == "text":
                content.append({"type": "text", "text": element.content})
            elif element.type in ["image", "page_image"]:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{element.content}"
                    }
                })
        return content

    # ----------- 识别题目结构（改进：要求以“题目(problem) -> subquestions”输出） -----------
    def identify_questions_structure(self, elements):
        """
        请求模型以每道大题为单位返回 JSON：
        {
          "problems": [
            {
              "id": "1",
              "text": "本题干文本（如有）",
              "related_elements": [0,2],           # 可选：元素索引（相对于 elements 列表）
              "pages": [1,2],
              "subquestions": [
                {"id":"1(a)","text":"小问文本","related_elements":[3],"pages":[1]},
                ...
              ]
            },
            ...
          ]
        }
        如果模型未按该格式返回，会退到后面的 group_questions_by_prefix() 兜底。
        """
        self.logger.info("🧠 开始识别题目结构（按整道题分组请求模型返回 problems）...")
        elements.sort(key=lambda x: (x.page_num, x.center_y))
        content = self.build_multimodal_content(elements)
        system_prompt = (
            "你是专业的试卷结构分析专家。"
            "请以“整道题（problem）”为单位识别，保留每道题的题干（text）、子题（subquestions）和每个项对应的 page 与 related_elements（可用元素索引）。"
            "严格返回 JSON，格式如下："
            '{"problems":[{"id":"1","text":"题干（可为空）","related_elements":[0,1],"pages":[1],"subquestions":[{"id":"1(a)","text":"小问文本","related_elements":[2],"pages":[1]}]}]}'
            "只返回 JSON，不要多余说明。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ]
        result = self.safe_api_call(messages)
        # 解析 JSON（支持模型包裹 ```json ... ``` 的情况）
        try:
            if not result or result.startswith("❌"):
                raise ValueError("无效返回")
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0].strip()
            else:
                # 尝试直接找到首个 { 到末尾的 } 的内容
                json_candidate = result[result.find("{"): result.rfind("}")+1]
                json_str = json_candidate.strip()
            parsed = json.loads(json_str)
            problems = parsed.get("problems") or []
            self.logger.info(f"✅ AI按题目分组识别到 {len(problems)} 道题")
            # 如果格式是旧的 questions（向后兼容），将其转换为 problems（每题作为单个 subquestion）
            if not problems and isinstance(parsed.get("questions"), list):
                questions = parsed.get("questions")
                problems = self.group_questions_by_prefix(questions)
            return problems
        except Exception as e:
            self.logger.warning(f"AI 返回解析失败或非期望格式: {e}. 采用正则兜底并合并为 problems。")
            # 兜底：先用旧的 questions 正则方法识别小问，再按前缀合并为 problems
            questions = self.parse_questions_regex(elements)
            problems = self.group_questions_by_prefix(questions)
            return problems

    # ----------- 备用正则识别（保留并返回 questions 列表） -----------
    def parse_questions_regex(self, elements):
        questions = []
        text_content = ""
        for element in elements:
            if element.type == "text":
                text_content += f"{element.content}\n"
        lines = text_content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            patterns = [
                r'^(\d+)\s*[.、。)]',
                r'^第\s*(\d+)\s*题',
                r'^题\s*(\d+)',
                r'^([0-9]+[a-zA-Z]?)\s*[.、\)]'  # 兼容 1a, 2b 等
            ]
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    questions.append({
                        "id": match.group(1),
                        "text": line,
                        "related_elements": [],
                        "pages": [1]
                    })
                    break
        self.logger.info(f"正则匹配识别到 {len(questions)} 个小问（questions）")
        return questions

    # ----------- 将小问按“编号前缀”合并为整道题（兜底方案） -----------
    def group_questions_by_prefix(self, questions):
        """
        把 questions 列表按 id 的数字前缀合并为 problems。
        例如: 1, 1a, 1(b) -> 合并为 problem id '1'，其 subquestions 列表包含这些小问。
        如果问题 id 不带前缀，则按顺序单独成题。
        """
        problems = []
        current = None

        def extract_prefix(qid):
            # 提取领先的数字部分作为题号前缀
            m = re.match(r'(\d+)', str(qid))
            return m.group(1) if m else str(qid)

        for q in questions:
            pid = extract_prefix(q.get("id", ""))
            if current is None or current["id"] != pid:
                # 新题开始
                current = {"id": pid, "text": "", "related_elements": [], "pages": [], "subquestions": []}
                problems.append(current)
            # append subquestion
            sub = {
                "id": q.get("id", ""),
                "text": q.get("text", ""),
                "related_elements": q.get("related_elements", []),
                "pages": q.get("pages", [])
            }
            current["subquestions"].append(sub)
        self.logger.info(f"合并后得到 {len(problems)} 道 problems（每道题含 subquestions）")
        return problems

    # ----------- 匹配题目与元素（改造：支持 problems 结构） -----------
    def match_questions_with_elements(self, problems_info, elements):
        """
        输入 problems_info（每项含 subquestions），为每个 problem/subquestion 分配实际的 PageElement 对象。
        返回 Problem 对象列表（内含 Question 对象作为 subquestions）。
        """
        self.logger.info("🎯 开始精确匹配 problems 与页面元素...")
        matched_problems = []
        for p_idx, prob in enumerate(problems_info):
            prob_id = prob.get("id", f"p{p_idx}")
            self.logger.info(f"处理大题 {prob_id}")
            # 整道题可能有自己的 related_elements 指定（索引）
            prob_related_elements = []
            for idx in prob.get("related_elements", []):
                if 0 <= idx < len(elements):
                    prob_related_elements.append(elements[idx])
            # match subquestions
            subquestions_objs = []
            for sub in prob.get("subquestions", []):
                # 根据AI给出的相关元素索引映射
                related = []
                for idx in sub.get("related_elements", []):
                    if 0 <= idx < len(elements):
                        related.append(elements[idx])
                # 如果没有索引，进行智能推断（以 subquestion 文本 与 页码为依据）
                if not related:
                    related = self.smart_infer_elements(sub, elements)
                # 图片抽取
                question_images = [e.content for e in related if e.type in ["image", "page_image"]]
                q_obj = Question(
                    question_id=sub.get("id", ""),
                    text=sub.get("text", ""),
                    images=question_images,
                    page_nums=sub.get("pages", []),
                    elements=related
                )
                subquestions_objs.append(q_obj)
                self.logger.info(f"  小问 {q_obj.id} 匹配到 {len(question_images)} 张图")
            # 整题的 related elements 合并子题的 elements（用于整题级别的图片）
            combined_elements = prob_related_elements[:]
            for sq in subquestions_objs:
                for e in sq.related_elements if hasattr(sq, "related_elements") else sq.related_elements:
                    if e not in combined_elements:
                        combined_elements.append(e)
            # 整题对象（用 Question 来简单表示整题 / 但保持 subquestions 列表）
            problem_obj = {
                "id": prob_id,
                "text": prob.get("text", ""),
                "pages": prob.get("pages", []),
                "related_elements": combined_elements,
                "subquestions": subquestions_objs
            }
            matched_problems.append(problem_obj)
            self.logger.info(f"大题 {prob_id} 包含 {len(subquestions_objs)} 个小问，整题相关元素 {len(combined_elements)} 个")
        return matched_problems

    def smart_infer_elements(self, question_info, elements):
        """
        当 AI 未提供元素索引时的启发式推断。
        question_info 可以是 dict（含 text & pages）或 Question 对象。
        """
        if isinstance(question_info, Question):
            question_text = question_info.text
            question_pages = question_info.page_nums or [1]
        else:
            question_text = question_info.get("text", "")
            question_pages = question_info.get("pages", [1])

        page_range = set()
        for p in question_pages:
            if isinstance(p, int):
                page_range.update([p-1, p, p+1])
            else:
                try:
                    page_range.update([int(p)-1, int(p), int(p)+1])
                except:
                    page_range.update([p])
        # 筛选候选元素
        candidate_elements = [e for e in elements if e.page_num in page_range]
        related = []
        for element in candidate_elements:
            if element.type in ["image", "page_image"]:
                related.append(element)
            elif element.type == "text" and question_text and question_text.strip() and question_text in element.content:
                related.append(element)
        return related or candidate_elements[:3]

    # ----------- 解答题目（改造：按每道大题只调用一次API） -----------
# ----------- 解答题目（改造：按每道大题只调用一次API，并把题干写入结果） -----------
    def answer_questions(self, problems):
            """
            problems: matched_problems 列表（每项含 subquestions: list[Question]）
            对每道大题仅调用一次 AI，让模型返回针对每个小问的答案列表（JSON）。
            返回结果为每道题的 subanswers（与 subquestions 一一对应），并在每道题结果中加入 problem_text 字段。
            现在额外在每个小回答条目中包含 sub_text（小题题目文本）和 sub_images（小题相关图片列表）。
            """
            self.logger.info("💡 开始解答 problems（每道题调用一次 AI）...")
            all_results = []
            for prob in problems:
                prob_id = prob.get("id")
                prob_text = prob.get("text", "") or ""  # 题干文本（如果为空则仍为 ""）
                subqs: List[Question] = prob.get("subquestions", [])
                self.logger.info(f"解答大题 {prob_id}，包含 {len(subqs)} 个小问")

                # 构建多模态 content：先整题题干（如果有），再每个小问
                content = []
                if prob_text and prob_text.strip():
                    content.append({"type": "text", "text": f"题干（大题 {prob_id}）：\n{prob_text}"})
                for i, sq in enumerate(subqs):
                    # sq 可能是 Question 对象
                    sq_text = sq.text if hasattr(sq, "text") else (sq.get("text", "") if isinstance(sq, dict) else "")
                    content.append({"type": "text", "text": f"小问 {sq.id}：\n{sq_text}"})

                # 添加整题相关图片（如果有）
                for e in prob.get("related_elements", []):
                    if getattr(e, "type", None) in ["image", "page_image"]:
                        content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{e.content}"}})

                # 指令：一次性返回每个小问的答案（JSON），并尽可能在 JSON 中包含 problem_text 字段
                system_prompt = (
                    "你是专业题目解答助手。"
                    "请结合题干按小问逐个给出答案，并在每个小问后给出详细步骤与思路。"
                    "重要：最后严格返回 JSON，格式如下："
                    '{"problem_id":"1","problem_text":"题干文本（如果有）","answers":[{"sub_id":"1(a)","answer":"...","reason":"..."}]}'
                    "不要返回多余说明，若模型需要列出推导过程，请放到 reason 字段。"
                )
                messages = [
                    {"role":"system","content":system_prompt},
                    {"role":"user","content":content}
                ]
                ai_resp = self.safe_api_call(messages)

                # 解析 AI 返回的 JSON（支持 ```json 包裹）
                parsed_answers = None
                model_problem_text = None
                try:
                    if not ai_resp or ai_resp.startswith("❌"):
                        raise ValueError("无效返回")
                    if "```json" in ai_resp:
                        json_str = ai_resp.split("```json")[1].split("```")[0].strip()
                    else:
                        json_candidate = ai_resp[ai_resp.find("{"): ai_resp.rfind("}")+1]
                        json_str = json_candidate.strip()
                    parsed = json.loads(json_str)
                    # 优先读取模型返回的 problem_text（如果有），否则使用从 PDF 提取的题干
                    model_problem_text = parsed.get("problem_text") if isinstance(parsed, dict) else None
                    parsed_answers = parsed.get("answers", []) if isinstance(parsed, dict) else []
                    self.logger.info(f"✅ AI 返回了 {len(parsed_answers)} 个答案（大题 {prob_id}）")
                except Exception as e:
                    # 解析失败的兜底：把模型原文作为 single answer，并按小问顺序分配。
                    self.logger.warning(f"AI 返回解析失败: {e}. 将模型原文作为单条答案并按小问顺序分配。")
                    parsed_answers = []
                    for sq in subqs:
                        parsed_answers.append({"sub_id": sq.id, "answer": ai_resp, "reason": ""})
                    model_problem_text = None

                # 汇总结果：把每个 subquestion 对应的 answer 记录下来，并加入 sub_text/sub_images
                subresults = []
                for idx, ans in enumerate(parsed_answers):
                    # 兼容模型可能未返回 sub_id 的情况：按顺序匹配
                    sub_id = ans.get("sub_id") or (subqs[idx].id if idx < len(subqs) else None)
                    # 找到对应的 Question 对象（优先按 id 匹配）
                    sq_obj = None
                    if sub_id:
                        for s in subqs:
                            if getattr(s, "id", None) == sub_id:
                                sq_obj = s
                                break
                    if sq_obj is None and idx < len(subqs):
                        sq_obj = subqs[idx]  # 退回按序号匹配

                    sub_text = getattr(sq_obj, "text", "") if sq_obj else ""
                    sub_images = getattr(sq_obj, "images", []) if sq_obj else []

                    subresults.append({
                        "problem_id": prob_id,
                        "sub_id": sub_id,
                        "sub_text": sub_text,
                        "sub_images": sub_images,
                        "answer": ans.get("answer"),
                        "reason": ans.get("reason", "")
                    })

                # 如果模型没有返回 subanswers（极端情况），确保仍然返回与小问数量对应的空占位（并包含小题文本）
                if not subresults and subqs:
                    for sq in subqs:
                        subresults.append({
                            "problem_id": prob_id,
                            "sub_id": sq.id,
                            "sub_text": getattr(sq, "text", ""),
                            "sub_images": getattr(sq, "images", []),
                            "answer": "",
                            "reason": ""
                        })

                # 最终结果中把题干写入 problem_text：优先使用模型返回的 problem_text（如果有），否则使用我们提取到的题干
                final_problem_text = model_problem_text if (model_problem_text and model_problem_text.strip()) else prob_text

                all_results.append({
                    "problem_id": prob_id,
                    "problem_text": final_problem_text,
                    "num_subquestions": len(subqs),
                    "subanswers": subresults
                })
            return all_results
    # ----------- 完整处理流程（同名，调用上面改造后的方法） -----------
    def process_homework_complete(self, pdf_path):
        self.logger.info(f"开始智能处理: {pdf_path}")
        elements = self.extract_page_elements(pdf_path)
        if not elements:
            return {"error": "PDF元素提取失败", "step": 1}
        problems_info = self.identify_questions_structure(elements)
        if not problems_info:
            return {"error": "题目识别失败", "step": 2}
        problems = self.match_questions_with_elements(problems_info, elements)
        if not problems:
            return {"error": "题目匹配失败", "step": 3}
        results = self.answer_questions(problems)
        return {
            "success": True,
            "total_elements": len(elements),
            "total_problems": len(problems),
            "results": results
        }

# ================== 文件监控处理 ==================
class SmartFileHandler(FileSystemEventHandler):
    """文件系统事件处理器，监控文件夹变化"""
    def __init__(self, processor, logger):
        self.processor = processor
        self.logger = logger
        self.processing_files = set()  # 正在处理的文件集合

    def on_created(self, event):
        """处理文件创建事件"""
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if file_path.suffix.lower() in Config.SUPPORTED_FORMATS:
            self.logger.info(f"🆕 检测到新文件: {file_path.name}")
            time.sleep(2)  # 等待文件完全写入
            self.process_file(file_path)

    def on_moved(self, event):
        """处理文件移动事件（拖拽操作）"""
        if event.is_directory:
            return
        dest_path = Path(event.dest_path)
        if dest_path.suffix.lower() in Config.SUPPORTED_FORMATS:
            self.logger.info(f"📁 检测到拖入文件: {dest_path.name}")
            time.sleep(1)
            self.process_file(dest_path)

    def process_file(self, file_path):
        """处理检测到的文件"""
        if str(file_path) in self.processing_files:
            return
        try:
            self.processing_files.add(str(file_path))
            # 移动文件到处理文件夹
            processing_path = Path(Config.HOMEWORK_FOLDER) / Config.PROCESSING_FOLDER / file_path.name
            if file_path != processing_path:
                file_path.rename(processing_path)
            # 处理文件
            result = self.processor.process_homework_complete(processing_path)
            # 保存处理结果
            self.save_smart_result(processing_path, result)
            # 移动文件到结果文件夹
            results_path = Path(Config.HOMEWORK_FOLDER) / Config.RESULTS_FOLDER / file_path.name
            
            # 检查目标文件是否已存在
            if results_path.exists():
                # 添加时间戳或序号以避免冲突
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
                results_path = Path(Config.HOMEWORK_FOLDER) / Config.RESULTS_FOLDER / new_name
            
            processing_path.rename(results_path)
            self.logger.info(f"📄 文件已移动到结果文件夹: {results_path.name}")
        finally:
            self.processing_files.discard(str(file_path))

    def save_smart_result(self, pdf_path, result):
        """保存处理结果到JSON文件"""
        result_file = Path(Config.HOMEWORK_FOLDER) / Config.RESULTS_FOLDER / f"{pdf_path.stem}_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        self.logger.info(f"✅ 智能处理结果已保存: {result_file}")

# ================== 主程序入口 ==================
def main():
    """主函数，程序入口点"""
    setup_directories()  # 初始化文件夹
    logger = setup_logging()  # 初始化日志
    processor = SmartHomeworkProcessor(logger)  # 创建处理器
    event_handler = SmartFileHandler(processor, logger)  # 创建文件处理器
    observer = Observer()  # 创建文件监控器
    observer.schedule(event_handler, Config.HOMEWORK_FOLDER, recursive=False)
    observer.start()  # 启动监控
    logger.info("🚀 智能作业系统已启动，开始监控文件夹...")
    try:
        while True:
            time.sleep(1)  # 主循环
    except KeyboardInterrupt:
        observer.stop()  # 处理Ctrl+C中断
    observer.join()

if __name__ == "__main__":
    main()  # 程序入口