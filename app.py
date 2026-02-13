import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
# 确保 API_KEY 填写正确
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
# 使用 Qwen2-VL-7B，速度快且更稳定
MODEL_NAME = "Qwen/Qwen2-VL-7B-Instruct"

# --- 2. 注入 CSS：美化 UI，修复按钮和金额布局 ---
st.markdown("""
    <style>
    /* 隐藏原有的上传列表，让界面更干净 */
    [data-testid='stFileUploader'] section > div:nth-child(2) { display: none !important; }
    
    /* 高级蓝色下载按钮样式 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.5rem !important;
        border-radius: 8px !important;
        width: auto !important;
        min-width: 140px;
    }
    
    /* 底部对齐容器：金额和按钮同行靠右 */
    .bottom-container {
        display: flex;
        justify-content: flex-end;
        align-items: center;
        gap: 20px;
        margin-top: 20px;
    }
    .total-label { font-size: 1rem; color: #666; }
    .total-value { font-size: 1.8rem; font-weight: bold; color: #1e1e1e; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 核心识别函数 ---
def analyze_invoice(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract invoice as JSON: {\"Item\":\"x\", \"Date\":\"YYYY-MM-DD\", \"Total\":0.0}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]
        }],
        "temperature": 0.1
    }
    try:
        response = requests.post(API_URL, headers=headers, json=data, timeout=45)
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            clean = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean[clean.find('{'):clean.rfind('}')+1])
    except Exception:
        return None
    return None

# --- 4. 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 版)")

if 'results' not in st.session_state: st.session_state.results = {}
if 'ignored' not in st.session_state: st.session_state.ignored = set()

uploaded_files = st.file_uploader("请上传发票文件", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    # 统计新文件
    new_files = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.results and f"{f.name}_{f.size}" not in st.session_state.ignored]
    
    if new_files:
        msg = st.info(f"🚀 正在识别 {len(new_files)} 张新发票...")
        p_bar = st.progress(0)
        
        for i, f in enumerate(new_files):
            f_id = f"{f.name}_{f.size}"
            try:
                f_bytes = f.read()
                m_type = f.type
                if m_type == "application/pdf":
                    imgs = convert_from_bytes(f_bytes)
                    buf = io.BytesIO()
                    imgs[0].save(buf, format="JPEG")
                    f_bytes, m_type = buf.getvalue(), "image/jpeg"
                
                res = analyze_invoice(f_bytes, m_type)
                if res:
                    st.session_state.results[f_id] = {
                        "文件名": f.name,
                        "日期": res.get('Date', ''),
                        "项目": res.get('Item', ''),
                        "金额": float(str(res.get('Total', 0)).replace(',',''))
                    }
                else:
                    st.session_state.ignored.add(f_id)
            except: pass
            p_bar.progress((i + 1) / len(new_files))
        msg.empty()
        p_bar.empty()

    # 5. 显示表格与可编辑功能
    display_list = [v for k, v in st.session_state.results.items()]
    if display_list:
        df = pd.DataFrame(display_list)
        edited_df = st.data_editor(df, use_container_width=True, hide_index=True, num_rows="dynamic")
        
        # 计算总额
        total_sum = edited_df['金额'].sum() if not edited_df.empty else 0.0
        
        # 6. 底部布局：总金额与下载按钮同行靠右
        st.markdown("<br>", unsafe_allow_html=True)
        col_left, col_right = st.columns([6, 4])
        
        with col_right:
            # 使用 HTML 实现金额与按钮在同一水平线上
            st.markdown(f"""
                <div class="bottom-container">
                    <div class="total-label">💰 总计金额合计</div>
                    <div class="total-value">¥ {total_sum:,.2f}</div>
                </div>
            """, unsafe_allow_html=True)
            
            # 下载逻辑
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                edited_df.to_excel(writer, index=False)
            
            st.download_button(
                label="📥 下载 excel",
                data=output.getvalue(),
                file_name="发票汇总.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
