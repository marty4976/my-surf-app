import os
from datetime import datetime, timedelta

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
# front_window: 正面に近いとみなす角度
# wind_window: オン/オフ判定角度
POINTS = {
    "千葉：一宮周辺": {
        "lat": 35.37,
        "lon": 140.38,
        "coast_normal": 95,
        "swell_window": 85,
        "front_window": 22,
        "wind_window": 45,
        "ideal_swell": "東〜南東",
        "best_tide": "上げ〜満潮前",
        "note": "地形変化が早く、うねり方向で割れ方が変わりやすいポイント",
    },
    "千葉：御宿ポイント": {
        "lat": 35.19,
        "lon": 140.35,
        "coast_normal": 110,
        "swell_window": 70,
        "front_window": 18,
        "wind_window": 40,
        "ideal_swell": "東〜南東",
        "best_tide": "ミドル〜上げ",
        "note": "斜めうねりでピークがまとまりやすい傾向",
    },
    "千葉：南房総 白渚ポイント": {
        "lat": 34.93,
        "lon": 139.90,
        "coast_normal": 150,
        "swell_window": 65,
        "front_window": 16,
        "wind_window": 38,
        "ideal_swell": "南東〜南",
        "best_tide": "上げ始め〜上げ",
        "note": "回り込み成分が強いと反応が落ちやすいポイント",
    },
    "茨城：大竹海岸": {
        "lat": 36.19,
        "lon": 140.56,
        "coast_normal": 95,
        "swell_window": 80,
        "front_window": 20,
        "wind_window": 45,
        "ideal_swell": "東〜北東",
        "best_tide": "下げ〜上げ始め",
        "note": "風の影響を受けやすく、オフショアでまとまりやすい",
    },
    "茨城：鹿島市 明石ポイント": {
        "lat": 35.97,
        "lon": 140.74,
        "coast_normal": 95,
        "swell_window": 75,
        "front_window": 18,
        "wind_window": 42,
        "ideal_swell": "東〜北東",
        "best_tide": "上げ3分〜満潮前",
        "note": "潮位でワイド/ダンパー傾向が変わりやすい",
    },
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


def get_wind_status(wind_from_deg, coast_normal, wind_window):
    """ポイント法線に対する風向き判定"""
    onshore_dir = coast_normal
    offshore_dir = (coast_normal + 180) % 360

    if abs(angular_diff(wind_from_deg, offshore_dir)) <= wind_window:
        return "🔥 オフショア (Good)", "success"
    if abs(angular_diff(wind_from_deg, onshore_dir)) <= wind_window:
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


def infer_break_from_swell(wave_dir, wave_period, coast_normal, swell_window, front_window):
    """うねり向きから沿岸の波質を簡易推測"""
    if pd.isna(wave_dir):
        return "データなし", None, "うねり向きデータがないため推測できません。"

    delta = angular_diff(float(wave_dir), float(coast_normal))
    abs_delta = abs(delta)
    side_window = (front_window + swell_window) / 2

    if abs_delta > swell_window:
        angle_text = "このポイントでは回り込みが必要な向きで、サイズが出にくい可能性があります。"
    elif abs_delta <= front_window:
        angle_text = "正面に近いうねりです。反応しやすい反面、ワイドなブレイクも出やすいです。"
    elif abs_delta <= side_window:
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


def format_hhmm(dt_value):
    if pd.isna(dt_value):
        return "--:--"
    return pd.to_datetime(dt_value).strftime("%H:%M")


def pick_today_sun_times(sun_df, now_dt):
    if sun_df.empty:
        return "--:--", "--:--"

    today = now_dt.date()
    row = sun_df[sun_df["date"] == today]
    if row.empty:
        row = sun_df.iloc[[0]]

    sunrise_text = format_hhmm(row["sunrise"].iloc[0])
    sunset_text = format_hhmm(row["sunset"].iloc[0])
    return sunrise_text, sunset_text


def detect_tide_events(tide_df):
    src = tide_df.dropna(subset=["sea_level_height_msl"]).reset_index(drop=True)
    if len(src) < 3:
        return []

    values = src["sea_level_height_msl"].tolist()
    times = src["time"].tolist()
    events = []
    for i in range(1, len(values) - 1):
        prev_v, cur_v, next_v = values[i - 1], values[i], values[i + 1]
        if cur_v >= prev_v and cur_v > next_v:
            events.append(("満潮", times[i], cur_v))
        elif cur_v <= prev_v and cur_v < next_v:
            events.append(("干潮", times[i], cur_v))
    return events


def summarize_next_tide_events(df, now_dt, limit=4):
    tide_scope = df[(df["time"] >= now_dt - timedelta(hours=1)) & (df["time"] <= now_dt + timedelta(hours=36))]
    events = detect_tide_events(tide_scope[["time", "sea_level_height_msl"]])
    future_events = [event for event in events if event[1] >= now_dt]
    return future_events[:limit]


def get_tide_phase(future_df):
    tide_values = future_df["sea_level_height_msl"].dropna().head(2).tolist()
    if len(tide_values) < 2:
        return "不明"

    diff = tide_values[1] - tide_values[0]
    if diff > 0.03:
        return "上げ潮"
    if diff < -0.03:
        return "下げ潮"
    return "潮止まり付近"


# --- 3. データ取得 ---
@st.cache_data(ttl=1800)
def get_all_data(lat, lon):
    marine_url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wave_height,wave_period,wave_direction,sea_level_height_msl"
        "&timezone=Asia%2FTokyo"
    )
    marine_fallback_url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wave_height,wave_period,wave_direction"
        "&timezone=Asia%2FTokyo"
    )
    weather_url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wind_speed_10m,wind_direction_10m"
        "&daily=sunrise,sunset"
        "&forecast_days=3"
        "&timezone=Asia%2FTokyo"
    )

    marine_res = requests.get(marine_url, timeout=15).json()
    if "hourly" not in marine_res:
        marine_res = requests.get(marine_fallback_url, timeout=15).json()

    weather_res = requests.get(weather_url, timeout=15).json()

    df_m = pd.DataFrame(marine_res.get("hourly", {}))
    df_w = pd.DataFrame(weather_res.get("hourly", {}))
    df = pd.merge(df_m, df_w, on="time")
    df["time"] = pd.to_datetime(df["time"])

    if "sea_level_height_msl" not in df.columns:
        df["sea_level_height_msl"] = pd.NA

    sun_df = pd.DataFrame(weather_res.get("daily", {}))
    if not sun_df.empty and {"time", "sunrise", "sunset"}.issubset(sun_df.columns):
        sun_df = sun_df[["time", "sunrise", "sunset"]].rename(columns={"time": "date"})
        sun_df["date"] = pd.to_datetime(sun_df["date"], errors="coerce").dt.date
        sun_df["sunrise"] = pd.to_datetime(sun_df["sunrise"], errors="coerce")
        sun_df["sunset"] = pd.to_datetime(sun_df["sunset"], errors="coerce")
    else:
        sun_df = pd.DataFrame(columns=["date", "sunrise", "sunset"])

    return df, sun_df


# --- 4. メイン表示 ---
try:
    df, sun_df = get_all_data(pos["lat"], pos["lon"])
    now = datetime.now()
    future_df = df[df["time"] >= now]
    current = future_df.iloc[0] if not future_df.empty else df.iloc[-1]

    # 上部メトリクス
    st.header(f"現在のコンディション: {selected_name}")
    st.caption(f"ベストうねり: {pos['ideal_swell']} / ねらい目潮位: {pos['best_tide']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("波高", f"{current['wave_height']} m")
    c2.metric("周期", f"{current['wave_period']} s")
    c3.metric("風速", f"{current['wind_speed_10m']} km/h")

    wind_dir = float(current["wind_direction_10m"])
    wind_label = f"{degree_to_compass(wind_dir)} ({wind_dir:.0f}°)"
    status_text, status_color = get_wind_status(wind_dir, pos["coast_normal"], pos["wind_window"])
    c4.metric("風向き", wind_label)
    c4.write("**風向き判定**")
    if status_color == "success":
        c4.success(status_text)
    elif status_color == "error":
        c4.error(status_text)
    else:
        c4.warning(status_text)

    # タイド + 日照情報
    st.subheader("🕒 タイド・日照")
    sunrise_text, sunset_text = pick_today_sun_times(sun_df, now)
    if pd.notna(current.get("sea_level_height_msl")):
        tide_now_text = f"{float(current['sea_level_height_msl']):.2f} m"
    else:
        tide_now_text = "データなし"

    s1, s2, s3 = st.columns(3)
    s1.metric("日の出", sunrise_text)
    s2.metric("日の入り", sunset_text)
    s3.metric("現在の潮位(推定)", tide_now_text)
    st.caption(f"潮汐トレンド: {get_tide_phase(future_df)} / このポイントの狙い: {pos['best_tide']}")

    next_tides = summarize_next_tide_events(df, now)
    if next_tides:
        tide_text = " / ".join([f"{name} {time.strftime('%H:%M')} ({height:.2f}m)" for name, time, height in next_tides])
        st.write(f"次の潮汐目安: {tide_text}")
    else:
        st.caption("満潮/干潮の推定イベントを取得できませんでした。")

    st.caption(f"ポイント別メモ: {pos['note']}")

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
            pos["front_window"],
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
    t1, t2, t3 = st.tabs(["波高推移", "風速推移", "潮位推移(推定)"])
    with t1:
        fig_w = px.area(
            df[df["time"] >= now].head(48),
            x="time",
            y="wave_height",
            labels={"wave_height": "波高(m)"},
            color_discrete_sequence=["#00d1ff"],
        )
        st.plotly_chart(fig_w, use_container_width=True)
    with t2:
        fig_s = px.line(
            df[df["time"] >= now].head(48),
            x="time",
            y="wind_speed_10m",
            labels={"wind_speed_10m": "風速(km/h)"},
            color_discrete_sequence=["#ff4b4b"],
        )
        st.plotly_chart(fig_s, use_container_width=True)
    with t3:
        tide_48 = df[df["time"] >= now].head(48)
        if tide_48["sea_level_height_msl"].notna().any():
            fig_t = px.line(
                tide_48,
                x="time",
                y="sea_level_height_msl",
                labels={"sea_level_height_msl": "海面高度(m)"},
                color_discrete_sequence=["#2a9d8f"],
            )
            st.plotly_chart(fig_t, use_container_width=True)
        else:
            st.info("この地点では潮位データを取得できませんでした。")

except Exception:
    st.error("データの読み込み中にエラーが発生しました。")
    st.info("APIの制限または通信環境を確認してください。")
