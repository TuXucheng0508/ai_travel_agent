import streamlit as st
from datetime import date, timedelta

from txc_agent import build_trip

st.set_page_config(page_title="AI旅行管家", page_icon="🌍")
st.title("🌍 AI私人旅行管家")

st.caption("目的地 + 往返日期 → 通过 Google MCP 查真实机票/酒店 → 豆包生成攻略")

col1, col2 = st.columns(2)
with col1:
    origin = st.text_input("出发地（城市或机场代码）", placeholder="例如：北京 / PEK")
    outbound = st.date_input("去程日期", value=date.today() + timedelta(days=14))
with col2:
    dest = st.text_input("目的地（城市或机场代码）", placeholder="例如：杭州 / 东京 / HND")
    return_ = st.date_input("回程日期", value=date.today() + timedelta(days=17))

if st.button("🚀 生成旅行攻略", use_container_width=True):
    if not (origin and dest):
        st.warning("请填写出发地和目的地哦～")
        st.stop()
    if return_ <= outbound:
        st.warning("回程日期必须晚于去程日期～")
        st.stop()

    with st.spinner("正在通过 MCP 查询机票/酒店，并生成攻略..."):
        try:
            result = build_trip(
                origin, dest,
                outbound.strftime("%Y-%m-%d"),
                return_.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            st.error(f"出错了：{e}")
            st.stop()

    # 去程机票
    st.subheader("✈️ 低价机票 · 去程 Top3")
    if result["flights_out"]:
        for f in result["flights_out"]:
            line = (
                f"- **{f.get('airline', '—')}** ｜ 价格 **{f.get('price', '—')}** ｜ "
                f"出发 {f.get('depart_time', '—')} → 到达 {f.get('arrive_time', '—')} ｜ "
                f"时长 {f.get('duration', '—')} ｜ 经停 {f.get('stops', '—')}"
            )
            if f.get("link"):
                line += f" ｜ [在 Google Flights 查看]({f['link']})"
            st.markdown(line)
    else:
        st.info("未查到去程机票数据。")

    # 回程机票
    st.subheader("✈️ 低价机票 · 回程 Top3")
    if result["flights_ret"]:
        for f in result["flights_ret"]:
            line = (
                f"- **{f.get('airline', '—')}** ｜ 价格 **{f.get('price', '—')}** ｜ "
                f"出发 {f.get('depart_time', '—')} → 到达 {f.get('arrive_time', '—')} ｜ "
                f"时长 {f.get('duration', '—')} ｜ 经停 {f.get('stops', '—')}"
            )
            if f.get("link"):
                line += f" ｜ [在 Google Flights 查看]({f['link']})"
            st.markdown(line)
    else:
        st.info("未查到回程机票数据。")

    # 酒店
    st.subheader("🏨 推荐酒店 · 好评优先 Top5")
    if result["hotels"]:
        for h in result["hotels"]:
            line = (
                f"- **{h.get('name', '—')}** ｜ 评分 **{h.get('rating', '—')}** ｜ "
                f"价格 {h.get('price', '—')}"
            )
            if h.get("link"):
                line += f" ｜ [查看/预订]({h['link']})"
            st.markdown(line)
    else:
        st.info("未查到酒店数据。")

    # 攻略
    st.subheader("📋 旅行攻略")
    st.markdown(result["plan"])
