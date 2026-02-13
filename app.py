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

# --- 备选模型名单 (按优先级排序) ---
# 既然 72B 贵、InternVL 关了，我们只试那些便宜且大概率在线的
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-7B-Instruct",        # 首选：Qwen 7B (极便宜/免费，稳)
    "deepseek-ai/deepseek-vl-7b-chat",  # 备选：DeepSeek VL (备用)
    "TeleAI/TeleMM",                    # 备选：TeleMM (备用)
    "Qwen/Qwen2-VL-72B-Instruct"        #以此垫底：万一你有钱了，它也能跑
]

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

def analyze_image_auto_switch(image_bytes, mime_type):
    """
    自动轮询所有可用模型，直到成功
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    last_error = ""

    # 循环尝试列表里的每个模型
    for model_name in CANDIDATE_MODELS:
        # 显示正在尝试哪个
        status_msg = st.empty()
        status_msg.caption(f"🔄 正在尝试连接模型: `{model_name}` ...")
        
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
            response = requests.post(API_URL, headers=headers, json=data, timeout=30)
            
            # === 成功 (200) ===
            if response.status_code == 200:
                status_msg.caption(f"✅ 成功连接: `{model_name}`")
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s = clean.find('{')
                e = clean.rfind('}') + 1
                return json.loads(clean[s:e]) if s != -1 else json.loads(clean)
            
            # === 余额不足 (403 + insufficient balance) ===
            elif response.status_code == 403 and "balance" in response.text:
                status_msg.empty() # 清除尝试信息
                # 如果 7B 都报余额不足，那就是真的没钱了，直接抛出异常让用户知道
                if "7B" in model_name: 
                    raise Exception("💰 您的 SiliconFlow 免费额度已完全耗尽。请注册新账号获取额度，或充值(几块钱可以用很久)。")
                continue # 换下一个试试
            
            # === 模型禁用/不存在 (400/404) ===
            else:
                last_error = f"{model_name} 报错: {response.status_code}"
                status_msg.empty()
                continue # 换下一个

        except Exception as e:
            if "免费额度" in str(e): raise e # 如果是余额问题，直接中断
            last_error = str(e)
            continue
            
    # 如果循环完了都没成功
    raise Exception(f"所有模型均不可用。最后报错: {last_error}")

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (扫货版)", layout="wide")
st.title("🧾 AI 发票助手 (自动扫货版)")
st.info("💡 自动在 Qwen-7B / DeepSeek 等模型中寻找可用的免费/低价通道。")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
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

            # 调用自动切换函数
            result = analyze_image_auto_switch(process_bytes, mime_type)
            
            if result:
                try:
                    raw_amt = str(result.get('Total', 0)).replace('¥','').replace(',','')
                    amt = float(raw_amt)
                except:
                    amt = 0.0
                
                data_list.append({
                    "文件名": file.name,
                    "日期": result.get('Date', ''),
                    "项目": result.get('Item', ''),
                    "金额": amt
                })
                st.toast(f"✅ {file.name} 成功")
            
        except Exception as e:
            st.error(f"❌ {file.name} 失败: {e}")
            # 如果是余额不足，直接停止后续处理，别浪费时间了
            if "额度" in str(e):
                st.stop()
        
        progress_bar.progress((index + 1) / len(uploaded_files))

    # 结果展示
    if data_list:
        df = pd.DataFrame(data_list)
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总金额", f"¥ {df['金额'].sum():,.2f}")
        
        df.loc[len(df)] = ['合计', '', '', df['金额'].sum()]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel", output.getvalue(), "发票汇总.xlsx", type="primary")
