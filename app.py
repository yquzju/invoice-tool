import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- ⚠️ 配置你的 API Key ---
API_KEY = "你的_sk_开头_KEY" 

CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct",
    "Qwen/Qwen2-VL-7B-Instruct",
    "TeleAI/TeleMM"
]
API_URL = "https://api.siliconflow.cn/v1/chat/completions"

# --- 1. 注入自定义 CSS 复刻截图 3 的 UI 风格 ---
def local_css():
    st.markdown("""
    <style>
    /* 隐藏上传组件下方默认出现的文件列表 [截图1红框内容] */
    [data-testid='stFileUploader'] section > div:nth-child(2) {
        display: none !important;
    }
    
    /* 优化上传区域 UI [参考截图3] */
    div[data-testid="stFileUploaderDropzone"] {
        border: 2px dashed #d1d5db;
        border-radius: 16px;
        background-color: #fcfcfc;
        padding: 40px 20px;
    }
    
    .stApp { background-color: #F7F9FB; }

    /* 统计卡片样式 */
    .metric-card {
        background: white;
        padding: 24px;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        border: 1px solid #edf2f7;
        text-align: left;
    }
    .card-label { font-size: 14px; color: #64748b; margin-bottom: 8px; }
    .card-value { font-size: 28px; font-weight: 700; color: #1e293b; }
    
    /* 底部按钮栏 */
    .bottom-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

def analyze_image(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    for model in CANDIDATE_MODELS:
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "提取发票：1.Item(项目) 2.Date(YYYY-MM-DD) 3.Total(纯数字)。返回JSON:{\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=30)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except: continue
    return None

# --- 2. 主页面逻辑 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
local_css()

# 初始化状态
if 'db' not in st.session_state: st.session_state.db = pd.DataFrame(columns=["序号", "文件名", "项目名称", "开票日期", "金额", "状态", "uid"])
if 'cache' not in st.session_state: st.session_state.cache = {}

# --- 占位符：用于将卡片显示在上传组件下方，但逻辑上后渲染以实现“实时更新” ---
header_section = st.empty()

# --- 截图 3 风格的大上传区 ---
uploaded_files = st.file_uploader("点击或拖拽上传发票文件 (支持 JPG/PNG/PDF)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    new_data = []
    for file in uploaded_files:
        uid = f"{file.name}_{file.size}"
        # 避免重复处理已存在或已识别的文件
        if uid not in st.session_state.cache and uid not in st.session_state.db['uid'].values:
            with st.spinner(f"正在识别: {file.name}..."):
                try:
                    f_bytes = file.read()
                    m_type = file.type
                    if m_type == "application/pdf":
                        img = convert_from_bytes(f_bytes)[0]
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                    
                    res = analyze_image(f_bytes, m_type)
                    if res:
                        row = {
                            "序号": len(st.session_state.db) + len(new_data) + 1,
                            "文件名": file.name,
                            "项目名称": res.get('Item', '未知'),
                            "开票日期": res.get('Date', '-'),
                            "金额": float(str(res.get('Total', 0)).replace(',','')),
                            "状态": "✅ 完成",
                            "uid": uid
                        }
                        new_data.append(row)
                        st.session_state.cache[uid] = row
                except: pass
    
    if new_data:
        st.session_state.db = pd.concat([st.session_state.db, pd.DataFrame(new_data)], ignore_index=True)

# --- 表格明细区 [对应截图 2] ---
st.markdown("##### 📄 发票明细列表")
if not st.session_state.db.empty:
    # 核心：使用 st.data_editor 开启行删除功能
    # num_rows="dynamic" 会在最后一列自动生成 "x" 删除按钮
    edited_db = st.data_editor(
        st.session_state.db,
        column_config={
            "uid": None, # 彻底隐藏内部 ID
            "状态": st.column_config.TextColumn(disabled=True),
            "文件名": st.column_config.TextColumn(disabled=True),
            "序号": st.column_config.NumberColumn(width="small", disabled=True),
            "金额": st.column_config.NumberColumn(format="¥ %.2f"),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic", # 开启行增加和删除(截图2红框处的X按钮)
        key="main_editor"
    )
    
    # 同步修改和删除
    if len(edited_db) != len(st.session_state.db):
        st.session_state.db = edited_db
        st.rerun() # 触发重绘以实时更新顶部卡片
    st.session_state.db = edited_db # 更新编辑后的内容(如手动改金额)
else:
    st.info("暂无数据，请上传发票")

# --- 顶部卡片渲染 (逻辑后置以确保数据实时) ---
current_total = st.session_state.db['金额'].sum()
current_count = len(st.session_state.db)

with header_section:
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="metric-card"><div class="card-label">发票总数</div><div class="card-value">{current_count} 张</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-card"><div class="card-label">识别成功</div><div class="card-value">{len(st.session_state.db[st.session_state.db["状态"]=="✅ 完成"])} 张</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="metric-card"><div class="card-label">合计金额</div><div class="card-value">¥ {current_total:,.2f}</div></div>', unsafe_allow_html=True)

# --- 底部操作栏 ---
col_space, col_clear, col_dl = st.columns([6, 1.5, 1.5])
with col_clear:
    if st.button("🗑️ 清空全部", use_container_width=True):
        st.session_state.db = st.session_state.db.iloc[0:0]
        st.session_state.cache = {}
        st.rerun()

with col_dl:
    if not st.session_state.db.empty:
        csv = st.session_state.db.drop(columns=['uid']).to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 导出表格", data=csv, file_name="invoice_summary.csv", type="primary", use_container_width=True)
