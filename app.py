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
# 既然刚才 72B 成功了，我们把它放在第一位，如果没钱了它会自动切到 7B
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct",       # 优先尝试大模型 (效果最好)
    "Qwen/Qwen2-VL-7B-Instruct",        # 备选小模型 (便宜/免费)
    "deepseek-ai/deepseek-vl-7b-chat",  # 备选 DeepSeek
    "TeleAI/TeleMM"                     # 备选 TeleMM
]

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

def analyze_image_auto_switch(image_bytes, mime_type):
    """
    自动轮询模型，直到成功
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    last_error = ""

    for model_name in CANDIDATE_MODELS:
        # 在界面上显示正在尝试哪个模型（只在第一次运行时显示）
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在尝试: {model_name} ...")
        
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
                status_placeholder.empty() # 清除提示
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s = clean.find('{')
                e = clean.rfind('}') + 1
                return json.loads(clean[s:e]) if s != -1 else json.loads(clean)
            
            elif response.status_code == 403:
                status_placeholder.empty()
                if "7B" in model_name: # 如果连最便宜的都报 403
                    raise Exception("余额不足，请检查 SiliconFlow 账号。")
                continue # 换下一个便宜的试试
                
            else:
                status_placeholder.empty()
                continue

        except Exception as e:
            status_placeholder.empty()
            last_error = str(e)
            continue
            
    raise Exception(f"所有模型均不可用。最后报错: {last_error}")

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (最终完美版)", layout="wide")
st.title("🧾 AI 发票助手(QwenVL版)")

# 🟢 关键修改 1：初始化“永久记忆”
# 只要你不关闭网页标签页，这个字典就会一直存着识别结果
if 'invoice_cache' not in st.session_state:
    st.session_state.invoice_cache = {}

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 找出哪些是“新来的”文件（没在缓存里的）
    new_files = []
    for file in uploaded_files:
        file_id = f"{file.name}_{file.size}"
        if file_id not in st.session_state.invoice_cache:
            new_files.append(file)
    
    # 如果有新文件，才显示进度条
    if new_files:
        progress_bar = st.progress(0)
        st.info(f"检测到 {len(new_files)} 张新发票，准备开始识别...")
    
    # 遍历所有上传的文件
    current_data_list = []
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        
        # 🟢 关键修改 2：优先查字典
        if file_id in st.session_state.invoice_cache:
            # 【命中缓存】直接拿结果，跳过 API 调用！
            result = st.session_state.invoice_cache[file_id]
            # 这里没有任何网络请求，瞬间完成
        else:
            # 【未命中】才去调 AI
            try:
                # 预处理
                file_bytes = file.read()
                process_bytes = file_bytes
                mime_type = file.type
                
                if file.type == "application/pdf":
                    images = convert_from_bytes(file_bytes)
                    if images:
                        img_buffer = io.BytesIO()
                        images[0].save(img_buffer, format="JPEG")
                        process_bytes = img_buffer.getvalue()
                        mime_type = "image/jpeg"
                if mime_type == 'image/jpg': mime_type = 'image/jpeg'

                # 调用 AI
                result = analyze_image_auto_switch(process_bytes, mime_type)
                
                # 🟢 关键修改 3：存入字典
                if result:
                    st.session_state.invoice_cache[file_id] = result
                    st.toast(f"✅ {file.name} 识别成功")
                
                # 更新进度条 (只针对新文件)
                if file in new_files:
                    curr_progress = (new_files.index(file) + 1) / len(new_files)
                    progress_bar.progress(curr_progress)

            except Exception as e:
                st.error(f"❌ {file.name} 失败: {e}")
                result = None

        # 整理数据用于显示
        if result:
            try:
                raw_amt = str(result.get('Total', 0)).replace('¥','').replace(',','').replace('元','')
                amt = float(raw_amt)
            except:
                amt = 0.0
            
            current_data_list.append({
                "文件名": file.name,
                "日期": result.get('Date', ''),
                "项目": result.get('Item', ''),
                "金额": amt
            })

    # 结果展示
    if current_data_list:
        df = pd.DataFrame(current_data_list)
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总金额", f"¥ {df['金额'].sum():,.2f}")
        
        # 导出 Excel
        df_export = df.copy()
        df_export.loc[len(df_export)] = ['合计', '', '', df['金额'].sum()]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        # 🟢 现在点这个按钮，代码虽然会重跑，但会瞬间走到“命中缓存”的分支
        # 既不会转圈，也不会扣费
        st.download_button(
            label="📥 下载 Excel 表格", 
            data=output.getvalue(), 
            file_name="发票汇总.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
