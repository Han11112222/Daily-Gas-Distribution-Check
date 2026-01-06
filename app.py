import streamlit as st
import pandas as pd
import numpy as np
import io
import matplotlib as mpl
import matplotlib.font_manager as fm
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.api as sm # [중요] 추세선 그리기용 라이브러리
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────────────────
# [0] 페이지 기본 설정
# ─────────────────────────────────────────────────────────
st.set_page_config(page_title="도시가스 통합 관리 시스템", layout="wide", page_icon="🔥")

# [Han형님 정보] 구글 시트 ID (에러 방지를 위해 URL 방식 사용)
SHEET_ID = "1GLyrA8snj7ffku8ff-3nJ_G4tjBC6SRWBMOInadjgrQ"
PLAN_FILE_2026 = "2026_연간_일별공급계획_2.xlsx" # 이건 로컬에 있어도 됨

# [스타일]
st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: #F8F9FA;
        border: 1px solid #E9ECEF;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

# [폰트]
def set_korean_font():
    ttf = Path(__file__).parent / "NanumGothic-Regular.ttf"
    if ttf.exists():
        fm.fontManager.addfont(str(ttf))
        mpl.rcParams["font.family"] = "NanumGothic"
    else:
        font_list = [f.name for f in fm.fontManager.ttflist]
        if 'AppleGothic' in font_list: mpl.rcParams["font.family"] = 'AppleGothic'
        elif 'Malgun Gothic' in font_list: mpl.rcParams["font.family"] = 'Malgun Gothic'
        else: mpl.rcParams["font.family"] = 'sans-serif'
    mpl.rcParams["axes.unicode_minus"] = False

set_korean_font()

# ─────────────────────────────────────────────────────────
# [메뉴 구조] 사이드바 통합 메뉴
# ─────────────────────────────────────────────────────────
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석"])
st.sidebar.markdown("---")

# ─────────────────────────────────────────────────────────
# [공통 기능] 데이터 소스 선택기
# ─────────────────────────────────────────────────────────
st.sidebar.header("📡 데이터 원본 선택")
data_source_option = st.sidebar.radio(
    "어떤 데이터를 사용할까요?",
    ("1. 구글 스프레드시트 (Live)", "2. 직접 업로드 (Excel)")
)

uploaded_user_file = None
if "직접 업로드" in data_source_option:
    uploaded_user_file = st.sidebar.file_uploader("엑셀 파일 업로드 (.xlsx)", type=['xlsx'])

# ─────────────────────────────────────────────────────────
# [핵심] 데이터 로드 함수 (클라우드 에러 방지용 URL 방식)
# ─────────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def load_data_flexible(sheet_type="daily"):
    df = None
    
    # 1. 구글 스프레드시트 (CSV 방식 - 가장 안전함)
    if "구글" in data_source_option:
        try:
            # gid=0 (첫번째 시트)
            csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
            df = pd.read_csv(csv_url)
            # 컬럼명 공백 제거
            df.columns = [str(c).strip() for c in df.columns]
        except Exception as e:
            st.sidebar.error(f"⚠️ 구글 시트 로드 실패: {e}")
            return None

    # 2. 업로드
    elif "직접 업로드" in data_source_option:
        if uploaded_user_file is not None:
            try:
                sheet_keyword = "일별" if sheet_type == "daily" else "월별"
                xls = pd.ExcelFile(uploaded_user_file, engine="openpyxl")
                target_sheet = next((s for s in xls.sheet_names if sheet_keyword in s), xls.sheet_names[0])
                df = pd.read_excel(xls, sheet_name=target_sheet)
            except Exception as e:
                st.sidebar.error(f"업로드 파일 오류: {e}")
    
    return df

# ─────────────────────────────────────────────────────────
# [공통 함수] 데이터 전처리
# ─────────────────────────────────────────────────────────
def process_daily_data(df):
    if df is None or df.empty: return pd.DataFrame()

    df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
    
    col_date = next((c for c in df.columns if "일자" in c or "date" in c.lower()), None)
    col_mj = next((c for c in df.columns if "실적" in c and ("MJ" in c or "GJ" in c)), None)
    if not col_mj:
        col_mj = next((c for c in df.columns if "공급량" in c and ("MJ" in c or "GJ" in c)), None)
    col_m3 = next((c for c in df.columns if ("실적" in c or "공급량" in c) and ("M3" in c or "m3" in c)), None)
    
    if not col_date or not col_mj: return pd.DataFrame() 

    df[col_date] = pd.to_datetime(df[col_date], errors='coerce')
    df = df.dropna(subset=[col_date])
    
    def clean_number(x):
        if isinstance(x, str): x = x.replace(',', '')
        return pd.to_numeric(x, errors='coerce')

    df['val_gj'] = df[col_mj].apply(clean_number).fillna(0)
    if "MJ" in col_mj.upper(): df['val_gj'] = df['val_gj'] / 1000.0
        
    if col_m3: df['val_m3'] = df[col_m3].apply(clean_number).fillna(0)
    else: df['val_m3'] = 0
        
    if "평균기온(℃)" in df.columns:
        df["평균기온(℃)"] = df["평균기온(℃)"].apply(clean_number)
    else:
        df["평균기온(℃)"] = np.nan

    result = df[[col_date, 'val_gj', 'val_m3', '평균기온(℃)']].rename(columns={col_date: '날짜', 'val_gj': '실적(GJ)', 'val_m3': '실적(m3)'})
    return result

# ─────────────────────────────────────────────────────────
# [공통 함수] 2026 계획 파일
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_2026_plan_data():
    path = Path(__file__).parent / PLAN_FILE_2026
    if not path.exists(): return pd.DataFrame()
    try:
        raw = pd.read_excel(path, sheet_name='연간', header=None)
        header_idx = None
        for i, row in raw.iterrows():
            vals = row.astype(str).values
            if '연' in vals and '월' in vals:
                header_idx = i
                break
        
        if header_idx is None: return pd.DataFrame()
        
        df = raw.iloc[header_idx+1:].copy()
        df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
        
        col_y = next((c for c in df.columns if '연' == c), None)
        col_m = next((c for c in df.columns if '월' == c), None)
        col_d = next((c for c in df.columns if '일' == c), None)
        col_p_gj = next((c for c in df.columns if ('계획' in c or '예상' in c) and ('GJ' in c or 'MJ' in c)), None)
        col_p_m3 = next((c for c in df.columns if ('계획' in c or '예상' in c) and ('m3' in c or 'M3' in c)), None)

        if not (col_y and col_m and col_d): return pd.DataFrame()

        df['날짜'] = pd.to_datetime({
            'year': pd.to_numeric(df[col_y], errors='coerce'),
            'month': pd.to_numeric(df[col_m], errors='coerce'),
            'day': pd.to_numeric(df[col_d], errors='coerce')
        }, errors='coerce')
        
        df = df.dropna(subset=['날짜'])
        
        df['계획(GJ)'] = pd.to_numeric(df[col_p_gj], errors='coerce').fillna(0)
        if col_p_gj and "MJ" in col_p_gj.upper(): df['계획(GJ)'] = df['계획(GJ)'] / 1000.0
        if col_p_m3: df['계획(m3)'] = pd.to_numeric(df[col_p_m3], errors='coerce').fillna(0)
        else: df['계획(m3)'] = 0
            
        return df[['날짜', '계획(GJ)', '계획(m3)']]
    except:
        return pd.DataFrame()

# ==============================================================================
# [탭 1] 도시가스 공급실적 관리
# ==============================================================================
def run_tab1_management():
    raw_df = load_data_flexible("daily")
    df = process_daily_data(raw_df)
    
    if df.empty:
        st.warning("⚠️ 데이터를 불러올 수 없습니다. 구글 시트 연결 상태를 확인해주세요.")
        df = pd.DataFrame(columns=['날짜', '실적(GJ)', '실적(m3)', '평균기온(℃)'])

    df_plan = load_2026_plan_data()
    if not df_plan.empty:
        df = pd.merge(df_plan, df, on='날짜', how='outer', suffixes=('_plan', '_act'))
        df['실적(GJ)'] = df['실적(GJ)'].fillna(0)
        df['실적(m3)'] = df['실적(m3)'].fillna(0)
        df['계획(GJ)'] = df['계획(GJ)'].fillna(0)
        df['계획(m3)'] = df['계획(m3)'].fillna(0)
    else:
        df['계획(GJ)'] = 0
        df['계획(m3)'] = 0

    st.title("🔥 도시가스 공급실적 관리")

    col_date, _ = st.columns([1, 4])
    with col_date:
        valid_dates = df[df['실적(GJ)'] > 10]['날짜']
        last_act_date = valid_dates.max() if not valid_dates.empty else datetime.now().date()
        target_date = st.date_input("조회 기준일", value=last_act_date)
    
    target_date = pd.to_datetime(target_date)
    current_row = df[df['날짜'] == target_date]
    vals = current_row.iloc[0].to_dict() if not current_row.empty else {'실적(GJ)': 0, '계획(GJ)': 0, '실적(m3)': 0, '계획(m3)': 0}

    st.markdown("### 🔥 열량 실적 (GJ)")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        act = vals.get('실적(GJ)', 0)
        plan = vals.get('계획(GJ)', 0)
        delta = act - plan
        rate = (act / plan * 100) if plan > 0 else 0
        st.metric(label=f"일간 달성률 {rate:.1f}%", value=f"{int(act):,} GJ", delta=f"{int(delta):+,} GJ")
        st.caption(f"계획: {int(plan):,} GJ")

    with col2:
        mask_month = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month) & (df['날짜'] <= target_date)
        month_data = df[mask_month]
        act_m = month_data['실적(GJ)'].sum()
        plan_m = month_data['계획(GJ)'].sum()
        delta_m = act_m - plan_m
        rate_m = (act_m / plan_m * 100) if plan_m > 0 else 0
        st.metric(label=f"월간 누적 달성률 {rate_m:.1f}%", value=f"{int(act_m):,} GJ", delta=f"{int(delta_m):+,} GJ")
        st.caption(f"누적 계획: {int(plan_m):,} GJ")

    with col3:
        mask_year = (df['날짜'].dt.year == target_date.year) & (df['날짜'] <= target_date)
        year_data = df[mask_year]
        act_y = year_data['실적(GJ)'].sum()
        plan_y = year_data['계획(GJ)'].sum()
        delta_y = act_y - plan_y
        rate_y = (act_y / plan_y * 100) if plan_y > 0 else 0
        st.metric(label=f"연간 누적 달성률 {rate_y:.1f}%", value=f"{int(act_y):,} GJ", delta=f"{int(delta_y):+,} GJ")
        st.caption(f"누적 계획: {int(plan_y):,} GJ")
    
    st.markdown("---")
    st.markdown("### 💧 부피 실적 (천 m³)")
    col_m1, col_m2, col_m3 = st.columns(3)
    def to_thou(val): return val / 1000.0
        
    with col_m1:
        act_v = vals.get('실적(m3)', 0)
        plan_v = vals.get('계획(m3)', 0)
        st.metric(label="일간 실적", value=f"{int(to_thou(act_v)):,} (천 m³)", delta=f"{int(to_thou(act_v - plan_v)):+,}")
    with col_m2:
        act_vm = month_data['실적(m3)'].sum()
        st.metric(label="월간 누적", value=f"{int(to_thou(act_vm)):,} (천 m³)")
    with col_m3:
        act_vy = year_data['실적(m3)'].sum()
        st.metric(label="연간 누적", value=f"{int(to_thou(act_vy)):,} (천 m³)")

    if act > 10 and not df.empty:
        rank_all = (df['실적(GJ)'] > act).sum() + 1
        st.markdown("---")
        st.markdown(f"##### 🏆 {target_date.strftime('%Y-%m-%d')} 기록: 역대 {int(rank_all)}위 공급량")
        if rank_all == 1: st.balloons()

# ==============================================================================
# [탭 2] 공급량 분석
# ==============================================================================
def run_tab2_analysis():
    st.title("📊 공급량 분석")
    
    raw_df = load_data_flexible("daily")
    df = process_daily_data(raw_df)
    
    if df.empty:
        st.error("데이터가 없습니다.")
        return

    df['연'] = df['날짜'].dt.year
    df['월'] = df['날짜'].dt.month
    df['일'] = df['날짜'].dt.day

    # -------------------------------------------------------------
    # 1. 월별 비교 차트
    # -------------------------------------------------------------
    st.subheader("📈 연도별 월간 실적 비교")
    monthly_agg = df.groupby(['연', '월'])['실적(GJ)'].sum().reset_index()
    monthly_agg['실적(GJ)'] = monthly_agg['실적(GJ)'].round(0)
    
    fig = px.line(monthly_agg, x='월', y='실적(GJ)', color='연', markers=True, title="연도별 월간 공급량 추이", symbol='연')
    fig.update_layout(xaxis=dict(tickmode='linear', dtick=1))
    st.plotly_chart(fig, use_container_width=True)

    # -------------------------------------------------------------
    # 2. 기온 vs 공급량 상관관계 (추세선 포함)
    # -------------------------------------------------------------
    st.markdown("---")
    st.subheader("🌡️ 기온과 공급량의 관계")
    scatter_df = df.dropna(subset=['평균기온(℃)', '실적(GJ)'])
    scatter_df = scatter_df[scatter_df['실적(GJ)'] > 10]
    
    if not scatter_df.empty:
        try:
            fig_scatter = px.scatter(scatter_df, x='평균기온(℃)', y='실적(GJ)', 
                                     color='연', hover_data=['날짜'],
                                     trendline="ols", # statsmodels 필요
                                     title="기온에 따른 일일 공급량 분포")
            st.plotly_chart(fig_scatter, use_container_width=True)
        except Exception as e:
            st.warning(f"추세선을 그리려면 requirements.txt에 statsmodels를 추가하세요. (에러: {e})")
            fig_scatter_simple = px.scatter(scatter_df, x='평균기온(℃)', y='실적(GJ)', color='연', hover_data=['날짜'])
            st.plotly_chart(fig_scatter_simple, use_container_width=True)
            

    # -------------------------------------------------------------
    # 3. [요청하신 기능] 기온 매트릭스 (툴팁 수정 완료)
    # -------------------------------------------------------------
    st.markdown("---")
    st.subheader("🌡️ 기온 매트릭스 (일별 평균기온)")
    
    years = sorted(df["연"].unique().tolist())
    if not years: return
    
    c1, c2 = st.columns([2, 1])
    with c1: 
        yr_range = st.slider("연도 범위", min_value=years[0], max_value=years[-1], value=(years[0], years[-1]))
    with c2: 
        sel_m = st.selectbox("월 선택", list(range(1, 13)), index=0)

    sub = df[(df["연"].between(yr_range[0], yr_range[1])) & (df["월"] == sel_m)]
    
    if not sub.empty:
        # 피벗: 행(일), 열(연도), 값(기온)
        pivot = sub.pivot_table(index="일", columns="연", values="평균기온(℃)")
        pivot = pivot.reindex(range(1, 32)) # 1일~31일 강제 고정

        fig_heat = px.imshow(pivot, aspect="auto", color_continuous_scale="RdBu_r", origin='upper')
        
        # [수정된 부분] 툴팁(마우스오버)에 날짜와 기온 표시
        fig_heat.update_traces(
            hovertemplate="<b>📅 %{x}년 " + str(sel_m) + "월 %{y}일</b><br>🌡️ 기온: <b>%{z:.1f}℃</b><extra></extra>"
        )
        
        fig_heat.update_layout(
            height=600,
            xaxis=dict(title="연도", side="bottom"),
            yaxis=dict(title="일", dtick=1),
            title=f"{sel_m}월 일별 기온 분포"
        )
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("선택한 기간에 데이터가 없습니다.")

# ==============================================================================
# [메인 실행 라우터]
# ==============================================================================
if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
elif menu == "2. 공급량 분석":
    run_tab2_analysis()
