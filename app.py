import streamlit as st
import pandas as pd
import numpy as np
import io
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────
# [0] 페이지 기본 설정
# ─────────────────────────────────────────────────────────
st.set_page_config(page_title="도시가스 통합 관리 시스템", layout="wide")

# [스타일] CSS 적용
st.markdown("""
   <style>
   div[data-testid="stMetric"] {
       background-color: #F0F2F6;
       border-radius: 10px;
       padding: 15px;
       min-height: 200px;
       display: flex;
       flex-direction: column;
       justify-content: center;
    }
   </style>
""", unsafe_allow_html=True)

def set_korean_font():
    ttf = Path(__file__).parent / "NanumGothic-Regular.ttf"
    if ttf.exists():
        try:
            mpl.font_manager.fontManager.addfont(str(ttf))
            mpl.rcParams["font.family"] = "NanumGothic"
            mpl.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass
set_korean_font()

# ─────────────────────────────────────────────────────────
# [NEW] 기상청 API 호출 함수 (대구: 143)
# ─────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_daegu_temperature(target_date_str):
    API_KEY = "YPnuBBk5fCP55U/+PF8HS2ifcwDclA2+WghIxuodBYRwi58ONaiMm8ATkzzaZSk1nP3dfXBFfEGboryZuZy9IQ=="
    url = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
    params = {
        "serviceKey": API_KEY, "pageNo": "1", "numOfRows": "10", "dataType": "JSON",
        "dataCd": "ASOS", "dateCd": "DAY", "startDt": target_date_str, "endDt": target_date_str, "stnIds": "143"
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        items = data['response']['body']['items']['item']
        if items: return float(items[0]['avgTa'])
    except: return None
    return None

# ─────────────────────────────────────────────────────────
# [공통 함수 1] 실적 데이터 로드 (형님께서 지정하신 구글 시트 연동)
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=300) # 5분마다 갱신
def load_historical_data_common():
    sheet_id = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    
    try:
        df = pd.read_csv(sheet_url)
        df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
        
        col_date = next((c for c in df.columns if "일자" in c or "날짜" in c or "date" in c.lower()), None)
        col_mj = next((c for c in df.columns if ("실적" in c or "공급량" in c) and ("MJ" in c or "GJ" in c)), None)
        col_m3 = next((c for c in df.columns if ("실적" in c or "공급량" in c) and ("M3" in c or "m3" in c)), None)
        
        if not col_date: return None
        
        df[col_date] = pd.to_datetime(df[col_date], errors='coerce')
        df = df.dropna(subset=[col_date])
        
        if col_mj:
            df['val_gj'] = pd.to_numeric(df[col_mj].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            if "MJ" in col_mj.upper(): df['val_gj'] = df['val_gj'] / 1000.0
        else:
            df['val_gj'] = 0.0
            
        if col_m3:
            df['val_m3'] = pd.to_numeric(df[col_m3].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        else:
            df['val_m3'] = 0.0
        
        if "평균기온(℃)" not in df.columns:
             df["평균기온(℃)"] = np.nan
        else:
             df["평균기온(℃)"] = pd.to_numeric(df["평균기온(℃)"], errors='coerce')

        return df[['val_gj', 'val_m3', col_date, '평균기온(℃)']].rename(columns={col_date: '일자'})
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return None

# ─────────────────────────────────────────────────────────
# [공통 함수 2] 2026년 계획 데이터 로드
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_2026_plan_data_common():
    path = Path(__file__).parent / "2026_연간_일별공급계획_2.xlsx"
    if not path.exists(): return None
    try:
        raw = pd.read_excel(path, sheet_name='연간', header=None)
        header_idx = -1
        for i, row in raw.iterrows():
            if '연' in row.astype(str).values and '월' in row.astype(str).values:
                header_idx = i; break
        if header_idx == -1: return None
        df = raw.iloc[header_idx+1:].copy()
        df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
        col_map = {}
        for c in df.columns:
            if '연' in c: col_map['y'] = c
            elif '월' in c: col_map['m'] = c
            elif '일' in c: col_map['d'] = c
            elif ('계획' in c or '예상' in c) and 'GJ' in c: col_map['p_gj'] = c
            elif ('계획' in c or '예상' in c) and 'm3' in c: col_map['p_m3'] = c
        df['날짜'] = pd.to_datetime({'year': pd.to_numeric(df[col_map['y']]), 'month': pd.to_numeric(df[col_map['m']]), 'day': pd.to_numeric(df[col_map['d']])}, errors='coerce')
        df = df.dropna(subset=['날짜'])
        df['plan_gj'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
        df['plan_m3'] = pd.to_numeric(df[col_map.get('p_m3')], errors='coerce').fillna(0)
        return df[['날짜', 'plan_gj', 'plan_m3']]
    except: return None

# ==============================================================================
# [탭 1] 도시가스 공급실적 관리
# ==============================================================================
def run_tab1_management():
    if 'tab1_df' not in st.session_state:
        df_hist = load_historical_data_common()
        if df_hist is not None and not df_hist.empty:
            init_df = df_hist.rename(columns={'일자': '날짜', 'val_gj': '실적(GJ)', 'val_m3': '실적(m3)'})
            init_df['계획(GJ)'] = 0.0
            init_df['계획(m3)'] = 0.0
            st.session_state.tab1_df = init_df
        else:
            st.session_state.tab1_df = pd.DataFrame({
                '날짜': [pd.to_datetime('today').normalize()],
                '계획(GJ)': [0.0], '실적(GJ)': [0.0], '계획(m3)': [0.0], '실적(m3)': [0.0], '평균기온(℃)': [np.nan]
            })

    df = st.session_state.tab1_df

    df_plan_file = load_2026_plan_data_common()
    if df_plan_file is not None and not df_plan_file.empty:
        plan_gj_map = df_plan_file.set_index('날짜')['plan_gj']
        plan_m3_map = df_plan_file.set_index('날짜')['plan_m3']
        df['계획(GJ)'] = df['날짜'].map(plan_gj_map).fillna(0.0)
        df['계획(m3)'] = df['날짜'].map(plan_m3_map).fillna(0.0)
        st.session_state.tab1_df = df

    st.sidebar.header("📂 [관리] 데이터 파일")
    st.sidebar.file_uploader("연간계획 엑셀 업로드", type=['xlsx'], key="u1")
    
    st.title("🔥 도시가스 공급실적 관리")

    # --------------------------------------------------------------------------
    # [수정된 부분] 날짜 선택 로직 완벽 복구
    # --------------------------------------------------------------------------
    col_date, col_refresh = st.columns([1, 4])
    with col_date:
        # 실제 실적이 0보다 크게 입력된 유효한 데이터만 추려냅니다.
        valid_df = df[df['실적(GJ)'] > 0]
        
        if not valid_df.empty:
            # 실적이 존재하는 가장 최신(마지막) 날짜를 디폴트로 잡습니다.
            default_date = valid_df['날짜'].max().date()
        else:
            # 실적 데이터가 아예 없는 상황이라면 오늘 날짜를 디폴트로 합니다.
            default_date = pd.to_datetime("today").date()
            
        selected_date = st.date_input("조회 기준일", value=default_date)
        
    target_date = pd.to_datetime(selected_date)

    mask_day = df['날짜'] == target_date
    current_row = df[mask_day]

    if current_row.empty:
        p_gj, p_m3 = 0, 0
        if df_plan_file is not None:
            p_match = df_plan_file[df_plan_file['날짜'] == target_date]
            if not p_match.empty:
                p_gj, p_m3 = p_match['plan_gj'].iloc[0], p_match['plan_m3'].iloc[0]
        
        new_row = pd.DataFrame([{'날짜': target_date, '계획(GJ)': p_gj, '실적(GJ)': 0, '계획(m3)': p_m3, '실적(m3)': 0, '평균기온(℃)': np.nan}])
        df = pd.concat([df, new_row], ignore_index=True)
        st.session_state.tab1_df = df
        current_row = df[df['날짜'] == target_date]

    if pd.isna(current_row['평균기온(℃)'].iloc[0]):
        api_temp = get_daegu_temperature(target_date.strftime("%Y%m%d"))
        if api_temp is not None:
            df.loc[mask_day, '평균기온(℃)'] = api_temp
            st.session_state.tab1_df = df
            st.toast(f"⛅ {target_date.strftime('%Y-%m-%d')} 대구 기온({api_temp}℃) 자동 입력됨")

    current_val_gj = float(current_row['실적(GJ)'].iloc[0])
    plan_val_gj = float(current_row['계획(GJ)'].iloc[0])
    
    st.markdown("### 🔥 열량 실적 (GJ)")
    col_g1, col_g2, col_g3 = st.columns(3)
    
    with col_g1:
        diff_gj = current_val_gj - plan_val_gj
        rate_gj = (current_val_gj / plan_val_gj * 100) if plan_val_gj > 0 else 0
        st.metric(label=f"일간 달성률 {rate_gj:.1f}%", value=f"{int(current_val_gj):,} GJ", delta=f"{int(diff_gj):+,} GJ")
        st.caption(f"계획: {int(plan_val_gj):,} GJ")

    with col_g2:
        mask_mtd = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month) & (df['날짜'] <= target_date)
        mtd_data = df[mask_mtd]
        a_mtd, p_mtd = mtd_data['실적(GJ)'].sum(), mtd_data['계획(GJ)'].sum()
        rate_mtd = (a_mtd/p_mtd*100) if p_mtd > 0 else 0
        st.metric(label=f"월간 누적 달성률 {rate_mtd:.1f}%", value=f"{int(a_mtd):,} GJ", delta=f"{int(a_mtd-p_mtd):+,} GJ")

    with col_g3:
        mask_ytd = (df['날짜'].dt.year == target_date.year) & (df['날짜'] <= target_date)
        ytd_data = df[mask_ytd]
        a_ytd, p_ytd = ytd_data['실적(GJ)'].sum(), ytd_data['계획(GJ)'].sum()
        rate_ytd = (a_ytd/p_ytd*100) if p_ytd > 0 else 0
        st.metric(label=f"연간 누적 달성률 {rate_ytd:.1f}%", value=f"{int(a_ytd):,} GJ", delta=f"{int(a_ytd-p_ytd):+,} GJ")

    st.markdown("---")
    st.subheader(f"📝 {target_date.month}월 실적 입력")
    
    mask_month = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
    view_df = df[mask_month].sort_values('날짜').copy()
    view_df['날짜'] = view_df['날짜'].dt.strftime("%Y-%m-%d")

    edited_df = st.data_editor(
        view_df[['날짜', '평균기온(℃)', '계획(GJ)', '실적(GJ)']],
        column_config={
            "날짜": st.column_config.TextColumn("공급일자", disabled=True),
            "평균기온(℃)": st.column_config.NumberColumn("평균기온(℃) ✏️", step=0.1),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", min_value=0),
        },
        hide_index=True, use_container_width=True, key="editor_tab1"
    )

    if not edited_df.equals(view_df[['날짜', '평균기온(℃)', '계획(GJ)', '실적(GJ)']]):
        df.loc[mask_month, '실적(GJ)'] = edited_df['실적(GJ)'].values
        df.loc[mask_month, '평균기온(℃)'] = edited_df['평균기온(℃)'].values
        st.session_state.tab1_df = df
        st.rerun()

    st.sidebar.button("🔄 구글 시트 새로고침", on_click=lambda: st.cache_data.clear())

# ==============================================================================
# [탭 2] 공급량 분석 및 메인 실행부
# ==============================================================================
def run_tab2_analysis():
    st.title("📊 도시가스 공급량 분석")
    st.info("실적 관리 탭에서 입력된 데이터를 바탕으로 정밀 분석을 수행합니다.")

st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석"])

if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
else:
    run_tab2_analysis()
