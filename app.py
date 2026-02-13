import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
# ⚠️ 填入你的 Key
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# 建议切换到 7B 模型，识别发票足够准，且几乎免费/极便宜，不容易欠费
# 如果你想用回超强的 72B，把下面这行注释掉，解开 72B 那行的注释
MODEL_NAME = "Qwen/Qwen2-VL-7B-Instruct" 
# MODEL_NAME = "Qwen/Qwen2-VL-72B-Instruct" # <--- 72B 更强但更贵

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

def analyze_image_qwen(image_bytes, mime_type):
    """Qwen API 调用函数"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "提取发票信息为JSON：1.Item(项目名称) 2.Date(YYYY-MM-DD) 3.Total(价税合计纯数字)。例:{\"Item\":\"服务费\",\"Date\":\"2023-01-01\",\"Total\":100.00}"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1
    }

    for attempt in range(2): # 失败重试 2 次
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content']
                clean_content = content.replace("```json", "").replace("```", "").strip()
                # 简单的 JSON 提取容错
                s = clean_content.find('{')
                e = clean_content.rfind('}') + 1
                return json.loads(clean_content[s:e]) if s != -1 else json.loads(clean_content)
            elif response.status_code == 403:
                st.error("余额不足 (403)。请检查 SiliconFlow 账户余额，或切换为免费的 7B 模型。")
                return None
            else:
                time.sleep(1)
        except Exception:
            time.sleep(1)
    return None

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (防重跑版)", layout="wide")
st.title("🧾 AI 发票助手 (智能缓存版)")

# 🟢 核心修改 1：初始化缓存
# 就像给系统装了个记事本，记下处理过的文件
if 'processed_cache' not in st.session_state:
    st.session_state.processed_cache = {}

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 用来临时存放本次展示的数据
    current_display_data = []
    
    # 进度条逻辑
    # 我们先计算一下有哪些文件是“真正”需要调 API 的（没缓存的）
    files_to_process = []
    for file in uploaded_files:
        file_key = f"{file.name}_{file.size}" # 生成唯一ID
        if file_key not in st.session_state.processed_cache:
            files_to_process.append(file)
            
    # 如果有新文件，显示进度条；全是旧文件就不显示
    if files_to_process:
        progress_bar = st.progress(0)
        st.toast(f"开始处理 {len(files_to_process)} 个新文件...")
    
    # === 开始循环处理 ===
    for index, file in enumerate(uploaded_files):
        file_key = f"{file.name}_{file.size}"
        
        # 🟢 核心修改 2：先查缓存
        if file_key in st.session_state.processed_cache:
            # 命中缓存！直接拿结果，不调 API，不花钱，不报错
            result = st.session_state.processed_cache[file_key]
            # print(f"Hit cache for {file.name}") # 调试用
        else:
            # 没缓存，才去调 API
            # 预处理图片
            file_bytes = file.read()
            process_bytes = file_bytes
            mime_type = file.type
            
            try:
                if file.type == "application/pdf":
                    images = convert_from_bytes(file_bytes)
                    if images:
                        img_buffer = io.BytesIO()
                        images[0].save(img_buffer, format="JPEG")
                        process_bytes = img_buffer.getvalue()
                        mime_type = "image/jpeg"
                if mime_type == 'image/jpg': mime_type = 'image/jpeg'
                
                # 调用 AI
                result = analyze_image_qwen(process_bytes, mime_type)
                
                # 存入缓存
                if result:
                    st.session_state.processed_cache[file_key] = result
                    st.toast(f"✅ {file.name} 识别成功")
                
                # 更新进度条 (只针对新文件更新)
                if files_to_process:
                     # 计算当前是第几个新文件
                     current_new_idx = files_to_process.index(file) + 1 if file in files_to_process else 0
                     if current_new_idx > 0:
                        progress_bar.progress(current_new_idx / len(files_to_process))

            except Exception as e:
                st.error(f"{file.name} 处理出错: {e}")
                result = None

        # 整理数据用于展示
        if result:
            try:
                raw_amt = str(result.get('Total', 0))
                raw_amt = raw_amt.replace('¥', '').replace('￥', '').replace(',', '').replace('元', '')
                amt = float(raw_amt)
            except:
                amt = 0.0
            
            current_display_data.append({
                "文件名": file.name,
                "开票日期": result.get('Date', ''),
                "发票项目": result.get('Item', ''),
                "价税合计": amt
            })

    # === 展示结果 ===
    if current_display_data:
        df = pd.DataFrame(current_display_data)
        total = df['价税合计'].sum()
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        
        # 导出 Excel
        df_export = df.copy()
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        # 🟢 现在你点这个按钮，代码虽然会重跑，但会直接走缓存，瞬间完成，不会报错
        st.download_button(
            "📥 下载 Excel 表格", 
            output.getvalue(), 
            "发票汇总.xlsx", 
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            type="primary"
        )
