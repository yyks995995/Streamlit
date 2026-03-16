import streamlit as st
import requests
import re
from openai import OpenAI

st.set_page_config(page_title="Twitch VOD 弹幕 AI 舆情分析", page_icon="🎮", layout="wide")

st.title("🎮 Twitch 录播(VOD) 弹幕舆情分析台")
st.markdown("通过输入 Twitch VOD 链接，一键抓取历史弹幕，并严格按照《DF海外 KOL 弹幕分析模型》生成结构化舆情报告。")

# ================= 侧边栏配置 =================
with st.sidebar:
    st.header("⚙️ 全局设置")
    default_key = st.secrets.get("OPENAI_API_KEY", "")
    openai_api_key = st.text_input("填入你的 OpenAI API Key", value=default_key, type="password")
    model_choice = st.selectbox("选择大模型版本", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])
    st.markdown("---")
    st.markdown("### 📝 内置分析模板")
    st.info("已完全对齐《xQc弹幕分析》报告标准：\n1. 核心结论提取\n2. 观点分布与二级表达结构\n3. 弹幕结构总结\n4. 主播四象限归类 (玩法/情绪驱动)")

# ================= 核心抓取逻辑 (Twitch GQL API) =================
def get_vod_id(url):
    """从链接中提取 VOD ID"""
    match = re.search(r'videos/(\d+)', url)
    return match.group(1) if match else None

def fetch_twitch_chat(vod_id, max_msgs):
    """直接请求 Twitch API，彻底绕开任何第三方库和终端环境限制"""
    # Twitch Public Client ID (公开通用的)
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko" 
    
    headers = {
        'Client-ID': client_id,
        'Content-Type': 'text/plain;charset=UTF-8'
    }
    
    # 构造请求数据 (模拟网页端请求)
    payload = [{
        "operationName": "VideoCommentsByOffsetOrCursor",
        "variables": {
            "videoID": str(vod_id),
            "contentOffsetSeconds": 0
        },
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb738245d05f087b5b5020ba"
            }
        }
    }]

    messages = []
    cursor = None
    
    # 一次请求大概返回 40-50 条，设定上限循环防止死循环
    max_loops = (int(max_msgs) // 40) + 5
    
    for _ in range(max_loops):
        # 翻页逻辑：如果有游标，则使用游标
        if cursor:
            payload[0]["variables"]["cursor"] = cursor
            if "contentOffsetSeconds" in payload[0]["variables"]:
                del payload[0]["variables"]["contentOffsetSeconds"]
                
        try:
            response = requests.post("https://gql.twitch.tv/gql", headers=headers, json=payload, timeout=10)
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络连接出错: {str(e)}")
            
        if response.status_code != 200:
            raise Exception(f"Twitch 接口拒绝请求: {response.status_code}")
            
        json_data = response.json()
        if not json_data or "data" not in json_data[0]:
            break
            
        data_body = json_data[0]["data"].get("video")
        if not data_body or not data_body.get("comments"):
            break
            
        comments = data_body["comments"]["edges"]
        if not comments:
            break
            
        for edge in comments:
            node = edge.get("node", {})
            
            # 提取时间
            content_offset = node.get("contentOffsetSeconds", 0)
            m, s = divmod(content_offset, 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            
            # 提取用户名
            author = "Unknown"
            if node.get("commenter") and node["commenter"].get("displayName"):
                author = node["commenter"]["displayName"]
                
            # 提取消息文本内容（包含表情和文字片段拼接）
            text_fragments = node.get("message", {}).get("fragments", [])
            text = "".join([frag.get("text", "") for frag in text_fragments if frag.get("text")])
            
            # 过滤垃圾信息
            if len(text.strip()) > 1:
                messages.append(f"[{time_str}] {author}: {text}")
                
            if len(messages) >= max_msgs:
                return messages
                
        # 获取下一页游标以供翻页
        page_info = data_body["comments"].get("pageInfo", {})
        if page_info.get("hasNextPage") and comments:
            cursor = comments[-1].get("cursor")
        else:
            break
            
    return messages

# ================= 界面与流程交互 =================
vod_url = st.text_input("📺 输入 Twitch VOD 链接 (例如: https://www.twitch.tv/videos/123456789)")
max_messages = st.number_input("📥 抓取弹幕数量上限 (建议 5000-10000 避免超出大模型理解上限)", min_value=100, max_value=50000, value=8000, step=1000)

if st.button("🚀 开始抓取并生成报告"):
    if not openai_api_key:
        st.error("请先在左侧配置 OpenAI API Key！")
        st.stop()
    if not vod_url:
        st.error("请输入 Twitch 链接！")
        st.stop()

    vod_id = get_vod_id(vod_url)
    if not vod_id:
        st.error("无法从链接中识别 VOD ID，请确认链接格式。格式应包含 /videos/后面接数字。")
        st.stop()

    client = OpenAI(api_key=openai_api_key)

    # ================= 阶段 1：扒取弹幕 =================
    st.subheader("1️⃣ 正在抓取 Twitch 弹幕...")
    
    with st.spinner(f"正在通过原生的 GraphQL API 从视频 {vod_id} 抽取数据，这需要十几秒，请耐心等待..."):
        try:
            chat_messages = fetch_twitch_chat(vod_id, max_messages)
            st.success(f"✅ 成功抓取了 {len(chat_messages)} 条有效弹幕数据！")
        except Exception as e:
            st.error(f"网络抓取失败: {str(e)}")
            st.stop()

    if len(chat_messages) == 0:
        st.warning("抓取完成，但未提取到任何弹幕。可能是该视频未开启弹幕或被设为仅订阅者可见。")
        st.stop()

    raw_chat_text = "\n".join(chat_messages)
    st.download_button(
        label="📥 下载原始弹幕 (TXT文本)",
        data=raw_chat_text,
        file_name=f"twitch_vod_{vod_id}_chat.txt",
        mime="text/plain"
    )

    # ================= 阶段 2：AI 舆情分析 =================
    st.subheader("2️⃣ ChatGPT 深度分析中 (严格遵循内置模板)...")
    
    system_prompt = """你是一个专业的游戏行业 KOL 舆情分析专家。
你的任务是根据用户提供的 Twitch 录播弹幕（Chat Logs），严格按照提供的专业模板输出舆情分析报告。请保持客观、专业。

【必须严格遵循的 Markdown 输出格式】：

# [替换为主播名字] 弹幕分析

## 一、核心结论
总结该场直播最重要的3个结论。
* **结论1：** [核心发现，如：XXX成为直播互动核心节点]
  * [具体表现与数据支撑]
  * **启示：** [对产品发行的启示]
* **结论2：** [关于主播行为或内容节奏的发现]
  * [具体表现与典型弹幕]
  * **启示：** [启示]
* **结论3：** [关于 Gameplay 体验或产品讨论的发现]
  * [具体表现与典型弹幕]
  * **启示：** [启示]

## 二、核心观点分布
提取弹幕中最核心的 4-5 个观点进行拆解。

* **观点一「[核心主题词]」**（占比约 XX%）
  * **出现时间/场景：** [如：战斗阶段/开箱阶段]
  * **二级表达结构：**
    1. [类型1，如煽动型]：[列举2-3条典型原声弹幕]
    2. [类型2，如吐槽型]：[列举2-3条典型原声弹幕]
  * **观察：** [深度分析该观点的互动特征]
*(继续列举观点二、观点三...)*

**弹幕结构总结：**
[一句话总结，例如：整体呈现 娱乐事件驱动 >> Gameplay讨论 的特征]

## 三、主播类型四象限模型归类
基于弹幕表现，将主播定位在【玩法驱动 vs 情绪驱动】与【娱乐体验 vs 产品理解】的十字模型中。
* **所属象限：** [例如：娱乐体验 × 情绪驱动]
* **特征观察：** [解释其在此象限的依据]
* **典型弹幕：** [列举该象限的标志性弹幕]
"""
    
    user_prompt = f"以下是该 VOD 的弹幕记录采样：\n\n{raw_chat_text[:80000]}"

    try:
        with st.spinner("AI 正在根据四象限模型和核心观点进行拆解，大约需要 1 分钟..."):
            response = client.chat.completions.create(
                model=model_choice,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                max_tokens=3000
            )
            
        analysis_result = response.choices[0].message.content
        st.success("✅ 舆情报告生成完毕！")
        
        st.markdown("---")
        st.markdown(analysis_result)
        
        st.download_button(
            label="📄 下载舆情分析报告 (Markdown)",
            data=analysis_result,
            file_name=f"Twitch_Analysis_VOD_{vod_id}.md",
            mime="text/markdown"
        )
        
    except Exception as e:
        st.error(f"AI 分析阶段报错: {str(e)}")
