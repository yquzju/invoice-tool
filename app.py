import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes

# --- ⚠️ 必须检查这里！ ---
# 1. 确保是以 "sk-" 开头的长字符串
# 2. 确保没有多余的空格
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# 如果 7B 也不行，可能是账号状态问题，我们先用这个免费且稳的模型测
MODEL_NAME = "Qwen/Qwen2-VL-7B-Instruct" 
API_URL = "https://api.siliconflow.cn/v1/chat/completions"

def test_api_connection():
    """启动时自检：测试 Key 是否有效"""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    # 发送一个极简请求测试连通性
    data = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5
    }
    try:
        response = requests.post(API_URL, headers=headers, json=data, timeout=5)
        if response.status_code == 200:
            return True, "✅ API 连接正常"
        elif response.status_code == 401:
            return False, "❌ Key 无效 (401)。请检查 API_KEY 是否填错，或者是否多复制了空格。"
        elif response.status_code == 403:
            return False, "❌ 余额不足 (403)。即使是免费模型，部分账号如果余额为负也无法调用。请登录 SiliconFlow 检查。"
        else:
            return False, f"❌ 连接失败: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"❌ 网络异常: {e}"

def analyze_image_debug(image_bytes, mime_type):
    """不带重试的直连模式，报错直接抛出"""
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
                    {"type": "text", "text": "提取发票：1.Item(项目) 2.Date(YYYY-MM-DD) 3.Total(纯数字)。JSON格式:{\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1
    }

    # 直接请求，不 Try...Except 隐藏错误
    response = requests.post(API_URL, headers=headers, json=data, timeout=30)
    
    if response.status_code == 200:
        content = response.json()['choices'][0]['message']['content']
        # 简单清洗
        clean = content.replace("```json", "").replace("```", "").strip()
        s = clean.find('{')
        e = clean.rfind('}') + 1
        return json.loads(clean[s:e]) if s != -1 else json.loads(clean)
    else:
        # 抛出详细错误给页面显示
        raise Exception(f"API报错 {response.status_code}: {response.text}")

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (调试版)", layout="wide")
st.title("🔧 AI 发票助手 (故障诊断版)")

# 1. 启动自检
with st.spinner("正在检查 API Key..."):
    is_ok, msg = test_api_connection()
    if is_ok:
        st.success(msg)
    else:
        st.error(msg)
        st.stop() # 如果 Key 都不对，直接停止，不让上传

uploaded_files = st.file_uploader("请上传发票 (调试模式)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    
    for file in uploaded_files:
        st.write(f"▶️ 正在处理: **{file.name}** ...") # 显示当前进度
        
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
            result = analyze_image_debug(process_bytes, mime_type)
            
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
                st.write(f"✅ 成功: {result.get('Item')} - {amt}")
            
        except Exception as e:
            # 🔴 这里会把具体的错误打印出来！
            st.error(f"❌ {file.name} 失败原因: {e}")

    # 结果表
    if data_list:
        st.divider()
        df = pd.DataFrame(data_list)
        st.dataframe(df)
        
        # 简单的导出逻辑
        df.loc[len(df)] = ['合计', '', '', df['金额'].sum()]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel", output.getvalue(), "result.xlsx")
