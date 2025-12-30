import streamlit as st
import pandas as pd
import numpy as np

# 페이지 설정을 'wide' 모드로 해서 시원하게 보여줍니다.
st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# --- 1. 데이터 로드 함수 (연/월/일 컬럼 병합 방식 유지) ---
def load_data(file_source):
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # '연', '월', '일'이 모두 포함된 행 찾기
    header_idx = None
    for i, row in raw_df.iterrows():
        row_str = row.astype(str).values
        if '연' in row_str and '월' in row_str and '일' in row_str:
            header_idx = i
            break
            
    if header_idx is None:
        st.error("❌ 데이터 양식을 읽을 수 없습니다. (연/월/일 컬럼 필요)")
        st.stop()

    df = raw_df.iloc[header_idx+1:].copy()
    df.columns = raw_df.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()

    col_map = {}
    for col in df.columns:
        if '연' in col and len(col) < 3: col_map['year'] = col
        elif '월' in col and len(col) < 3: col_map['month'] = col
        elif '일' in col and len(col) < 3: col_map['day'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 날짜 병합 및 데이터 정제
    try:
        y = pd.to_numeric(df[col_map['year']], errors='coerce')
        m = pd.to_numeric(df[col_map['month']], errors='coerce')
        d = pd.to_numeric(df[col_map['day']], errors='coerce')
        df['날짜'] = pd.to_datetime({'year': y, 'month': m, 'day': d}, errors='coerce')
        df = df.dropna(subset=['날짜'])
        
        for key in ['p_gj', 'a_gj', 'a_m3']:
            df[key] = pd.to_numeric(df[col_map[key]], errors='coerce').fillna(0)
    except Exception as e:
        st.error(f"데이터 변환 중 오류: {e}")
        st.stop()
            
    return df

# --- 2. 메인 화면 구성 ---
st.title("🔥 도시가스 공급계획 대비 실적 분석")

# 사이드바 설정
st.sidebar.header("📂 데이터 관리")
uploaded_file = st.sidebar.file_uploader("실적 파일 업로드", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

if uploaded_file:
    df = load_data(uploaded_file)
    st.sidebar.success("✅ 파일 적용됨")
else:
    try:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ 기본 데이터 사용")
    except:
        st.error("기본 파일을 찾을 수 없습니다.")
        st.stop()

# --- 3. [요청 반영] 날짜 선택 버튼 사이즈 조절 ---
st.write("### 📅 조회 기준일 설정")
# 컬럼을 [1, 4] 비율로 나눠서 왼쪽(좁은 쪽)에만 달력을 넣습니다.
col_date, col_dummy = st.columns([1, 4]) 

with col_date:
    selected_date = st.date_input("날짜를 선택하세요", value=df['날짜'].min(), label_visibility="collapsed")

target_date = pd.to_datetime(selected_date)

# --- 4. [핵심] 형님이 강조한 진도율 로직 계산 ---
def calculate_metrics(df, t_date):
    # (1) 일간: 해당 날짜 하루치
    day = df[df['날짜'] == t_date]
    
    # (2) 월간 누계: 해당 월 1일 ~ 선택한 날짜까지만 합산 (월 전체 X)
    mtd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)]
    
    # (3) 연간 누계: 1월 1일 ~ 선택한 날짜까지만 합산 (연 전체 X)
    ytd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)]
    
    res = {}
    for label, d in zip(['일간', '월간', '연간'], [day, mtd, ytd]):
        p = d['p_gj'].sum()      # 계획 누계 (선택일까지)
        a = d['a_gj'].sum()      # 실적 누계 (선택일까지)
        m3 = d['a_m3'].sum() / 1000 # 천 m3 단위
        
        # 진도율 계산 (계획이 0이면 에러 방지용 0 처리)
        rate = (a / p * 100) if p > 0 else 0
        
        res[label] = {'p': p, 'a': a, 'm3': m3, 'rate': rate}
    return res

metrics = calculate_metrics(df, target_date)

# --- 5. [요청 반영] 대시보드 시각화 (단위: GJ, 천 m3) ---
st.markdown("---")
col1, col2, col3 = st.columns(3)

# 스타일링: 형님이 원했던 '계획 대비 실적'이 명확히 보이도록 구성
with col1:
    st.subheader("📆 일일 실적 (Daily)")
    st.metric(
        label="오늘 공급량 (GJ)",
        value=f"{metrics['일간']['a']:,.0f} GJ",
        delta=f"{metrics['일간']['rate']:.1f}% (계획대비)",
    )
    st.caption(f"🎯 당일 계획: {metrics['일간']['p']:,.0f} GJ")

with col2:
    st.subheader("📅 월간 누계 진도 (MTD)")
    # 형님 요청: 15일이면 15일치 계획과 비교 -> 100% 달성 시 100% 표기
    st.metric(
        label="누적 달성률",
        value=f"{metrics['월간']['rate']:.1f}%",
        delta=f"{metrics['월간']['a'] - metrics['월간']['p']:,.0f} GJ (차이)",
    )
    st.caption(f"🔥 누적 계획: {metrics['월간']['p']:,.0f} GJ")
    st.text(f"💧 실적(부피): {metrics['월간']['m3']:,.1f} 천 m³")

with col3:
    st.subheader("📈 연간 누계 진도 (YTD)")
    st.metric(
        label="연간 누적 달성률",
        value=f"{metrics['연간']['rate']:.1f}%",
        delta=f"{metrics['연간']['a'] - metrics['연간']['p']:,.0f} GJ (차이)",
    )
    st.caption(f"🔥 누적 계획: {metrics['연간']['p']:,.0f} GJ")

# 상세 데이터 테이블
st.markdown("---")
st.subheader(f"📋 {target_date.strftime('%Y-%m-%d')} 상세 데이터")
st.dataframe(df[df['날짜'] == target_date].style.format({
    'p_gj': '{:,.0f}', 
    'a_gj': '{:,.0f}', 
    'a_m3': '{:,.1f}'
}))
