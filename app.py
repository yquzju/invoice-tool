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
# 备选模型优先级
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct", 
    "Qwen/Qwen2-VL-7B-Instruct",
    "TeleAI/TeleMM"
]

# --- 2. 注入 CSS (美化日志与按钮) ---
st.markdown("""
    <style>
    /* 高级蓝色按钮 */
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

    /* 底部总金额样式 */
    .total-container {
        display: flex;
        align-items: baseline;
        justify-content: flex-end;
        gap: 15px;
        height: 100%;
    }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    
    /* 实时日志样式 */
    .log-success { color: #28a745; font-weight: bold; }
    .log-error { color: #dc3545; font-weight: bold; }
    .log-info { color: #007bff; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 核心识别逻辑 (带详细反馈) ---
def analyze_invoice(image_bytes, mime_type, log_placeholder):
    """
    log_placeholder: 用于在界面上打印实时步骤
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    final_error = ""
    
    for model in CANDIDATE_MODELS:
        # 🟢 实时反馈：告诉用户正在连哪个模型
        log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;🔄 正在请求模型：`{model}` ...")
        
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
                # 成功！
                log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;✅ 模型 `{model}` 识别成功！")
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
            
            elif resp.status_code == 403:
                # 针对 403 限流的特殊提示
                log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;⚠️ 模型 `{model}` 繁忙 (HTTP 403)，正在切换备用模型...")
                time.sleep(1) # 遇到限流，主动冷却一下
            else:
                log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;⚠️ 模型 `{model}` 返回错误: {resp.status_code}")
                
        except Exception as e:
            log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;❌ 连接错误: {str(e)}")
            continue
            
    return None

# --- 4. 页面主程序 ---
st.set_page_config(page_title="AI 发票助手 (可视化版)", layout="wide")
st.title("🧾 AI 发票助手 (可视化控制台版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 1. 筛选待处理任务
    files_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        # 如果未处理过，或上次失败了，都需要处理
        if fid not in st.session_state.invoice_cache or st.session_state.invoice_cache[fid].get('status') == 'failed':
            files_to_process.append(f)

    # 2. 批量处理循环 (核心交互优化)
    if files_to_process:
        # 创建一个显眼的控制台区域
        with st.status("🚀 正在启动识别任务...", expanded=True) as status_box:
            st.write(f"检测到 {len(files_to_process)} 张待处理发票，开始队列处理...")
            progress_bar = st.progress(0)
            
            # 创建动态日志占位符
            current_file_info = st.empty()
            process_log = st.empty()
            
            for i, file in enumerate(files_to_process):
                fid = f"{file.name}_{file.size}"
                
                # 更新当前文件名，让用户知道卡在哪张图
                status_box.update(label=f"正在处理 ({i+1}/{len(files_to_process)}): {file.name}")
                current_file_info.info(f"📄 **当前文件**: `{file.name}`")
                
                try:
                    # 文件预处理
                    file.seek(0)
                    f_bytes = file.read()
                    m_type = file.type
                    
                    if m_type == "application/pdf":
                        process_log.markdown("&nbsp;&nbsp;&nbsp;&nbsp;📄 检测到 PDF，正在转换为图像...")
                        images = convert_from_bytes(f_bytes)
                        if images:
                            buf = io.BytesIO()
                            images[0].save(buf, format="JPEG")
                            f_bytes, m_type = buf.getvalue(), "image/jpeg"
                    elif m_type == 'image/jpg': m_type = 'image/jpeg'

                    # 调用识别 (传入 process_log 以实时打印步骤)
                    result = analyze_invoice(f_bytes, m_type, process_log)
                    
                    if result:
                        st.session_state.invoice_cache[fid] = {'status': 'success', 'data': result}
                        st.toast(f"✅ {file.name} 完成！")
                    else:
                        st.session_state.invoice_cache[fid] = {'status': 'failed'}
                        st.error(f"❌ {file.name} 最终识别失败")
                
                except Exception as e:
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
                    st.error(f"❌ {file.name} 发生异常: {e}")

                # 更新大进度条
                progress_bar.progress((i + 1) / len(files_to_process))
                time.sleep(0.5) # 稍微停顿，防止视觉跳变太快
            
            status_box.update(label="✅ 所有任务处理完毕！正在生成报表...", state="complete", expanded=False)
            time.sleep(1)
            st.rerun()

    # --- 3. 结果展示 ---
    table_data = []
    has_failed = False
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        cache = st.session_state.invoice_cache.get(fid)
        
        if cache and cache['status'] == 'success':
            res = cache['data']
            try: amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
            except: amt = 0.0
            table_data.append({
                "文件名": file.name, "日期": res.get('Date', ''), "项目": res.get('Item', ''), 
                "金额": amt, "状态": "✅ 成功", "file_id": fid
            })
        elif cache and cache['status'] == 'failed':
            has_failed = True
            table_data.append({
                "文件名": file.name, "日期": "-", "项目": "-", 
                "金额": 0.0, "状态": "❌ 失败", "file_id": fid
            })

    if table_data:
        df = pd.DataFrame(table_data)
        
        # 失败重试入口
        if has_failed:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning("⚠️ 部分发票识别失败，请点击右侧按钮重试。")
            with c2: 
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True):
                    st.rerun()

        # 表格
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None,
                "金额": st.column_config.NumberColumn(format="%.2f"),
                "状态": st.column_config.TextColumn(width="small", disabled=True),
                "文件名": st.column_config.TextColumn(disabled=True)
            },
            num_rows="dynamic", use_container_width=True, key="invoice_editor"
        )
        
        # 同步操作
        current_ids = set(edited_df["file_id"])
        original_ids = set(df["file_id"])
        if len(current_ids) != len(original_ids):
            st.session_state.ignored_files.update(original_ids - current_ids)
            st.rerun()
            
        for index, row in edited_df.iterrows():
            fid = row['file_id']
            if fid in st.session_state.invoice_cache and st.session_state.invoice_cache[fid]['status'] == 'success':
                 st.session_state.invoice_cache[fid]['data']['Total'] = row['金额']

        # 底部统计与导出
        total = edited_df[edited_df['状态'] == "✅ 成功"]['金额'].sum()
        
        col_s1, col_main, col_s2 = st.columns([2.5, 5, 2.5])
        with col_main:
            inner_l, inner_r = st.columns([1.5, 1])
            with inner_l:
                st.markdown(f"""
                    <div class="total-container">
                        <span class="total-label">💰 总金额合计</span>
                        <span class="total-value">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            with inner_r:
                output = io.BytesIO()
                df_exp = edited_df.drop(columns=["file_id"])
                df_exp.loc[len(df_exp)] = ['合计', '', '', total, '']
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_exp.to_excel(writer, index=False)
                st.download_button("导出 excel", output.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
