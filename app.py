import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
# 备选模型列表
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct", 
    "Qwen/Qwen2-VL-7B-Instruct",
    "TeleAI/TeleMM"
]

# --- 2. 注入 CSS：优化按钮、布局与状态显示 ---
st.markdown("""
    <style>
    /* 高级蓝色按钮，自适应宽度 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.2rem !important;
        border-radius: 8px !important;
        transition: all 0.3s ease;
        width: auto !important;
        min-width: unset !important;
        display: inline-flex !important;
        font-weight: 500 !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 12px rgba(0,123,255,0.3) !important;
    }
    button[data-testid="baseButton-primary"] p::before { content: none !important; }

    /* 底部布局容器 */
    .total-container {
        display: flex;
        align-items: baseline;
        justify-content: flex-end;
        gap: 15px;
        height: 100%;
    }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    
    /* 进度状态文字 */
    .status-text { font-size: 14px; color: #007bff; margin-bottom: 5px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 核心识别函数 (带实时状态反馈) ---
def analyze_invoice(image_bytes, mime_type, status_box):
    """
    status_box: 用于在界面上实时打印当前正在连接哪个模型
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    # 提示词：强制要求提取价税合计
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    last_err = ""
    for model in CANDIDATE_MODELS:
        # 🟢 实时反馈：告诉用户正在尝试哪个模型
        if status_box:
            status_box.markdown(f"🔄 正在请求模型：**{model}** ...")
            
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=30)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
            continue
            
    # 如果所有模型都失败，打印最后一次错误
    if status_box:
        status_box.markdown(f"⚠️ 所有模型尝试失败: {last_err}")
    return None

# --- 4. 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手 (QwenVL)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 实时反馈版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 1. 找出需要处理的文件 (新文件 OR 之前失败的文件)
    files_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 没处理过，或者上次处理失败的，都要加入队列
        if fid not in st.session_state.invoice_cache or st.session_state.invoice_cache[fid].get('status') == 'failed':
            files_to_process.append(f)

    # 2. 批量处理循环 (带可视化反馈)
    if files_to_process:
        # 创建一个固定的状态显示区
        status_container = st.container()
        with status_container:
            st.info(f"🚀 准备处理 {len(files_to_process)} 张发票，请保持网络通畅...")
            main_progress = st.progress(0)
            current_status = st.empty() # 专门用来显示“正在识别 xxx...”
            model_status = st.empty()   # 专门用来显示“正在连接 Qwen...”
        
        for i, file in enumerate(files_to_process):
            fid = f"{file.name}_{file.size}"
            
            # 更新文案：明确告诉用户正在处理哪张图
            current_status.markdown(
