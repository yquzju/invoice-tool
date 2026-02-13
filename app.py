import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes

# --- 1. 基础配置 ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
# 优先使用更省点数且稳定的 7B 模型
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-7B-Instruct", "Qwen/Qwen2-VL-72B-Instruct"]

# --- 2. 注入 CSS (修复按钮样式与对齐) ---
st.markdown("""
    <style>
    /* 高级蓝色按钮 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.5rem !important;
        border-radius: 8px !important;
        width: auto !important;
    }
    /* 同行居中对齐 */
    .footer-container {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 20px;
        margin-top: 30px;
    }
    .total-label { font-size: 1.1rem; color: #666; }
    .total-value { font-size: 2rem; font-weight: bold; color: #333; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 识别函数 (带自动重试) ---
def analyze_invoice(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    for model in CANDIDATE_MODELS:
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Extract invoice: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except:
            continue
    return None

# --- 4. 页面主体 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
st.title("🧾 AI 发票助手 (修复版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored' not in st.session_state: st.session_state.ignored = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    valid_files = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.ignored]
    current_data = []
    
    # 进度提示
    progress_bar = st.progress(0)
    
    for i, file in enumerate(uploaded_files):
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.invoice_cache:
            res = st.session_state.invoice_cache[fid]
        else:
            try:
                f_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    img = convert_from_bytes(f_bytes)[0]
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    f_bytes, m_type = buf.getvalue(), "image/jpeg"
                res = analyze_invoice(f_bytes, m_type)
                if res: st.session_state.invoice_cache[fid] = res
            except: res = None
        
        if res:
            amt = float(str(res.get('Total', 0)).replace('¥','').replace(',',''))
            current_data.append({"文件名": file.name, "日期": res.get('Date', ''), "项目": res.get('Item', ''), "金额": amt, "fid": fid})
        progress_bar.progress((i + 1) / len(uploaded_files))

    if current_data:
        df = pd.DataFrame(current_data)
        edited_df = st.data_editor(df, column_config={"fid": None}, use_container_width=True, num_rows="dynamic")
        
        # 居中统计与导出
        total = edited_df['金额'].sum()
        
        # 导出逻辑
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            edited_df.drop(columns='fid').to_excel(writer, index=False)
            
        st.markdown(f"""
            <div class="footer-container">
                <div><span class="total-label">💰 总计金额</span> <span class="total-value">¥ {total:,.2f}</span></div>
            </div>
        """, unsafe_allow_html=True)
        
        st.download_button("导出 excel", output.getvalue(), "发票汇总.xlsx")
