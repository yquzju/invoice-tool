import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- ⚠️ 填入你的 SiliconFlow Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# --- 备选模型名单 ---
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct",
    "Qwen/Qwen2-VL-7B-Instruct",
    "deepseek-ai/deepseek-vl-7b-chat",
    "TeleAI/TeleMM"
]

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

# --- 样式美化函数 (CSS) ---
def local_css():
    st.markdown("""
    <style>
    /* 隐藏 Streamlit 默认的汉堡菜单和页脚 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* 全局字体优化 */
    .stApp {
        background-color: #F8F9FA; /* 浅灰背景 */
    }

    /* 顶部卡片容器样式 */
    .metric-card-container {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        color: white;
        margin-bottom: 20px;
        height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    
    .card-title {
        font-size: 14px;
        opacity: 0.9;
        margin-bottom: 5px;
    }
    
    .card-value {
        font-size: 28px;
        font-weight: bold;
    }
    
    .card-icon {
        font-size: 24px;
        float: right;
        opacity: 0.8;
    }

    /* 颜色定义 */
    .bg-blue { background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%); }
    .bg-green { background: linear-gradient(135deg, #10B981 0%, #059669 100%); }
    .bg-orange { background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%); }

    /* 表格区域样式 */
    .table-container {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* 调整上传组件样式 */
    [data-testid='stFileUploader'] {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        border: 2px dashed #E5E7EB;
    }
    
    </style>
    """, unsafe_allow_html=True)

# --- 核心识别逻辑 (不变) ---
def analyze_image_auto_switch(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    last_error = ""

    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在通过 {model_name} 识别...")
        
        data = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract invoice data into JSON: 1.Item 2.Date 3.Total. JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 512,
            "temperature": 0.1
        }

        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if response.status_code == 200:
                status_placeholder.empty()
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s = clean.find('{')
                e = clean.rfind('}') + 1
                return json.loads(clean[s:e]) if s != -1 else json.loads(clean)
            elif response.status_code == 403:
                status_placeholder.empty()
                if "7B" in model_name: raise Exception("余额不足")
                continue
            else:
                status_placeholder.empty()
                continue
        except Exception as e:
            status_placeholder.empty()
            last_error = str(e)
            continue
    raise Exception(f"识别失败: {last_error}")

# --- 主页面逻辑 ---
st.set_page_config(page_title="智能发票系统", layout="wide", initial_sidebar_state="collapsed")
local_css() # 注入 CSS

# 初始化状态
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

# --- 1. 标题与上传区 ---
st.markdown("### 🧾 智能发票识别系统")

uploaded_files = st.file_uploader("点击或拖拽上传发票 (支持 PDF/JPG/PNG)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

# --- 2. 数据处理 ---
current_data_list = []
if uploaded_files:
    # 进度条逻辑
    new_files = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.invoice_cache and f"{f.name}_{f.size}" not in st.session_state.ignored_files]
    if new_files:
        progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        if file_id in st.session_state.ignored_files: continue

        if file_
