import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import streamlit.components.v1 as components

# --- 1. 基本設定 ---
st.set_page_config(page_title="Surf Dashboard Pro", layout="wide", page_icon="🏄‍♂️")

# カスタムCSSで見た目を整える
st.markdown(
    """
    <style>
    .main { background-color: #f0f2f6; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏄‍♂️ Surf Dashboard Pro")
st.caption("170cmサーファー基準のサイズ感 + ポイント別うねり推測")

# ポイント定義
# coast_normal: 沖向き法線（この向きからのうねりが正面）
# swell_window: 反応しやすい許容角（法線からのズレ）
POINTS = {
    "千葉：一宮周辺": {"lat": 35.37, "lon": 140.38, "coast_normal": 95, "swell_window": 85},
    "千葉：御宿ポイント": {"lat": 35.19, "lon": 140.35, "coast_normal": 110, "swell_window": 70},
    "千葉：南房総 白渚ポイント": {"lat": 34.93, "lon": 139.90, "coast_normal": 150, "swell_window": 65},
    "茨城：大竹海岸": {"lat": 36.19, "lon": 140.56, "coast_normal": 95, "swell_window": 80},
    "茨城：鹿島市 明石ポイント": {"lat": 35.97, "lon": 140.74, "coast_normal": 95, "swell_window": 75},
}

point_names = list(POINTS.keys())
st.sidebar.info("ポイント切り替えは画面上部のセレクターから行えます。")
selected_name = st.selectbox("📍 表示ポイントを選択（スマホはここ）", point_names)
st.caption(f"選択中: {selected_name}")
pos = POINTS[selected_name]


# --- 2. 判定ロジック ---
def angular_diff(a, b):
    """2方位角の差を -180〜180 で返す"""
    return ((a - b + 180) % 360) - 180


def degree_to_compass(deg):
    labels = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    idx = int((deg + 11.25) // 22.5) % 16
    return labels[idx]


def get_wind_status(wind_from_deg, coast_normal):
    """ポイント法線に対する風向き判定"""
    onshore_dir = coast_normal
    offshore_dir = (coast_normal + 180) % 360

    if abs(angular_diff(wind_from_deg, offshore_dir)) <= 45:
        return "🔥 オフショア (Good)", "success"
    if abs(angular_diff(wind_from_deg, onshore_dir)) <= 45:
        return "🌬 オンショア (Rough)", "error"
    return "↔️ サイドショア", "warning"


def get_surf_size(height):
    """170cmベースのサイズ感判定"""
    if height < 0.4:
        return "🦵 膝 (Knee)", "hiza.png"
    if height < 0.7:
        return "👖 腰 (Waist)", "koshi.png"
    if height < 1.0:
        return "👕 腹 (Stomach)", "hara.png"
    if height < 1.3:
        return "💖 胸 (Chest)", "mune.png"
    if height < 1.7:
        return "💪 肩〜頭 (Shoulder/Head)", "atama.png"
    return "🤯 頭オーバー (Overhead)", "over.png"


def infer_break_from_swell(wave_dir, wave_period, coast_normal, swell_window):
    """うねり向きから沿岸の波質を簡易推測"""
    if pd.isna(wave_dir):
        return "データなし", None, "うねり向きデータがないため推測できません。"

    delta = angular_diff(float(wave_dir), float(coast_normal))
    abs_delta = abs(delta)

    if abs_delta > swell_window:
        angle_text = "このポイントでは回り込みが必要な向きで、サイズが出にくい可能性があります。"
    elif abs_delta <= 20:
        angle_text = "正面に近いうねりです。反応しやすい反面、ワイドなブレイクも出やすいです。"
    elif abs_delta <= 45:
        angle_text = "斜めに入るうねりです。ピークに向きが出て、形が選びやすい傾向があります。"
    else:
        angle_text = "横寄りの入射です。地形との相性で割れ方にムラが出やすいです。"

    if pd.isna(wave_period):
        period_text = ""
    elif wave_period >= 10:
        period_text = "周期が長めなので、セットで急にサイズアップしやすいです。"
    elif wave_period >= 8:
        period_text = "周期は中程度で、比較的まとまりやすいです。"
    else:
        period_text = "周期が短めで、パワーが分散しやすいです。"

    dir_label = f"{degree_to_compass(float(wave_dir))} ({float(wave_dir):.0f}°)"
    hint = f"{angle_text} {period_text}".strip()
    return dir_label, abs_delta, hint


# --- 3. データ取得 ---
@st.cache_data(ttl=3600)
def get_all_data(lat, lon):
    marine_url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wave_height,wave_period,wave_direction"
        "&timezone=Asia%2FTokyo"
    )
    weather_url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wind_speed_10m,wind_direction_10m"
        "&timezone=Asia%2FTokyo"
    )

    df_m = pd.DataFrame(requests.get(marine_url, timeout=15).json()["hourly"])
    df_w = pd.DataFrame(requests.get(weather_url, timeout=15).json()["hourly"])
    df = pd.merge(df_m, df_w, on="time")
    df["time"] = pd.to_datetime(df["time"])
    return df


# --- 4. メイン表示 ---
try:
    df = get_all_data(pos["lat"], pos["lon"])
    now = datetime.now()
    future_df = df[df["time"] >= now]
    current = future_df.iloc[0] if not future_df.empty else df.iloc[-1]

    # 上部メトリクス
    st.header(f"現在のコンディション: {selected_name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("波高", f"{current['wave_height']} m")
    c2.metric("周期", f"{current['wave_period']} s")
    c3.metric("風速", f"{current['wind_speed_10m']} km/h")

    wind_dir = float(current["wind_direction_10m"])
    wind_label = f"{degree_to_compass(wind_dir)} ({wind_dir:.0f}°)"
    status_text, status_color = get_wind_status(wind_dir, pos["coast_normal"])
    c4.metric("風向き", wind_label)
    c4.write("**風向き判定**")
    if status_color == "success":
        c4.success(status_text)
    elif status_color == "error":
        c4.error(status_text)
    else:
        c4.warning(status_text)

    # サイズ感 + うねり推測
    st.divider()
    col_img, col_map = st.columns([1, 2])

    with col_img:
        size_text, img_file = get_surf_size(current["wave_height"])
        st.subheader("👕 サイズ感 (170cm基準)")
        st.info(f"現在の目安: **{size_text}**")

        # 画像ファイルがある場合のみ表示
        if os.path.exists(img_file):
            st.image(img_file, use_container_width=True)

        st.subheader("🌊 うねりからの推測")
        swell_label, entry_diff, swell_hint = infer_break_from_swell(
            current.get("wave_direction", float("nan")),
            current.get("wave_period", float("nan")),
            pos["coast_normal"],
            pos["swell_window"],
        )
        if entry_diff is None:
            st.caption(f"うねり向き: {swell_label}")
        else:
            st.caption(
                f"うねり向き: {swell_label} / 法線差: {entry_diff:.0f}° / 許容角: ±{pos['swell_window']}°"
            )
        st.write(swell_hint)

    with col_map:
        st.subheader("🌐 Windy リアルタイム")
        windy_url = (
            "https://embed.windy.com/embed2.html"
            f"?lat={pos['lat']}&lon={pos['lon']}"
            "&zoom=9&level=surface&overlay=waves&menu=&message=&marker="
            "&calendar=&pressure=&type=map&location=coordinates&detail="
            f"&detailLat={pos['lat']}&detailLon={pos['lon']}"
            "&metricWind=default&metricTemp=default&radarRange=-1"
        )
        components.html(
            f'<iframe width="100%" height="350" src="{windy_url}" frameborder="0"></iframe>',
            height=370,
        )

    # 予測グラフ
    st.divider()
    st.subheader("📈 48時間の予測データ")
    t1, t2 = st.tabs(["波高推移", "風速推移"])
    with t1:
        fig_w = px.area(
            df.head(48),
            x="time",
            y="wave_height",
            labels={"wave_height": "波高(m)"},
            color_discrete_sequence=["#00d1ff"],
        )
        st.plotly_chart(fig_w, use_container_width=True)
    with t2:
        fig_s = px.line(
            df.head(48),
            x="time",
            y="wind_speed_10m",
            labels={"wind_speed_10m": "風速(km/h)"},
            color_discrete_sequence=["#ff4b4b"],
        )
        st.plotly_chart(fig_s, use_container_width=True)

except Exception:
    st.error("データの読み込み中にエラーが発生しました。")
    st.info("APIの制限または通信環境を確認してください。")
