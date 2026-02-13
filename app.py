import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes

# --- ⚠️ 必填: 你的 SiliconFlow Key (sk-开头) ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# --- 核心修改：换用 InternVL2-26B (书生·浦语) ---
# 这是一个 260亿参数的强力视觉模型，中文 OCR 能力极强，且通常在 SiliconFlow 上可用
MODEL_NAME = "OpenGVLab/InternVL2-26B" 
API_URL = "https://api.siliconflow.cn/v1/chat/completions"

def analyze_image_internvl(image_bytes, mime_type):
    """
    使用 InternVL2 进行识别
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # InternVL 的 Prompt 格式
    data = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": "请分析这张发票，提取以下3项信息并以严格JSON格式返回：\n1. Item (发票项目名称)\n2. Date (开票日期 YYYY-MM-DD)\n3. Total (价税合计，纯数字)\n\n示例格式：{\"Item\": \"办公用品\", \"Date\": \"2023-01-01\", \"Total\": 100.00}\n请直接返回JSON，不要包含Markdown标记。"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1
    }

    try:
        response = requests.post(API_URL, headers=headers, json=data, timeout=60)
        
        # 调试用：打印状态码 (你可以看页面右上角的 Running 小人)
        # print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            # 清洗数据
            clean = content.replace("```json", "").replace("```", "").strip()
            s = clean.find('{')
            e = clean.rfind('}') + 1
            if s != -1 and e != -1:
                return json.loads(clean[s:e])
            return json.loads(clean)
        
        elif response.status_code == 400:
            # 如果 InternVL2-26B 也不在，我们尝试备用的 8B 版本
            raise Exception(f"模型 {MODEL_NAME} 未找到，可能需要切换其他模型。")
        else:
            raise Exception(f"API请求失败 {response.status_code}: {response.text}")
            
    except Exception as e:
        raise e

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (InternVL版)", layout="wide")
st.title("🧾 AI 发票助手 (InternVL2-26B 版)")
st.info(f"当前使用模型：`{MODEL_NAME}` (中文 OCR 强力模型)")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        status_text = st.empty()
        status_text.text(f"正在识别: {file.name} ...")
        
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

            # 调用
            result = analyze_image_internvl(process_bytes, mime_type)
            
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
        
        progress_bar.progress((index + 1) / len(uploaded_files))

    # 结果展示
    if data_list:
        status_text.text("处理完毕！")
        df = pd.DataFrame(data_list)
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总金额", f"¥ {df['金额'].sum():,.2f}")
        
        # 导出 Excel
        df.loc[len(df)] = ['合计', '', '', df['金额'].sum()]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel", output.getvalue(), "发票汇总.xlsx", type="primary")
