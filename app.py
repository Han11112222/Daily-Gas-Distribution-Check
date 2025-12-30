import streamlit as st
import pandas as pd

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# 1. 파일 로드 로직
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("새로운 실적 엑셀 파일을 업로드하세요 (옵션)", type=["xlsx"])

def load_data(file_source):
    # 헤더 위치를 찾기 위해 우선 읽어옵니다. 
    # 엑셀 파일의 구조에 따라 header=1 또는 header=2로 조정될 수 있습니다.
    # 제공된 이미지를 참고하여 header=1 (엑셀의 2행)을 기본값으로 설정합니다.
    df = pd.read_excel(file_source, sheet_name='연간', header=1) 
    
    # 컬럼명 앞뒤 공백 제거 및 문자열 변환
    df.columns = [str(c).strip() for c in df.columns]
    
    # 만약 '날짜' 컬럼이 안보인다면 디버깅을 위해 컬럼명을 화면에 표시 (에러 발생 시)
    if '날짜' not in df.columns:
        st.error(f"엑셀에서 '날짜' 컬럼을 찾을 수 없습니다. 현재 컬럼명: {list(df.columns)}")
        st.info("엑셀 파일의 2행에 '날짜', '계획(GJ)' 등의 제목이 있는지 확인해주세요.")
        st.stop()
        
    # 날짜 데이터 정제
    df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
    df = df.dropna(subset=['날짜']) # 날짜가 없는 행 제거
    
    # 실적 데이터 정제 (NaN을 0으로)
    for col in ['계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    return df

DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file is not None:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드된 파일을 사용 중입니다.")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 파일을 사용 중입니다.")
except Exception as e:
    st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
    st.stop()

# 2. 날짜 선택 및 계산 (형님의 요청 반영)
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

# 진도율 계산 함수 (일대비 100%면 월대비 100% 로직)
def get_metrics(df, t_date):
    ytd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)
    mtd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)
    daily_mask = (df['날짜'] == target_date)
    
    res = {}
    for label, mask in zip(['일간', '월간누계', '연간누계'], [daily_mask, mtd_mask, ytd_mask]):
        p_gj = df.loc[mask, '계획(GJ)'].sum()
        a_gj = df.loc[mask, '실적(GJ)'].sum()
        # 천 m3 단위 환산 요청 반영
        p_m3 = df.loc[mask, '계획(m3)'].sum() / 1000 
        a_m3 = df.loc[mask, '실적(m3)'].sum() / 1000
        
        ach = (a_gj / p_gj * 100) if p_gj > 0 else 0
        res[label] = {'p_gj': p_gj, 'a_gj': a_gj, 'p_m3': p_m3, 'a_m3': a_m3, 'ach': ach}
    return res

metrics = get_metrics(df, target_date)

# 3. 메트릭 대시보드 표시
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a_gj']:,.0f}", f"{metrics['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p_gj']:,.0f} GJ")
with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", f"계획비 {metrics['월간누계']['a_gj'] - metrics['월간누계']['p_gj']:,.0f} GJ")
    st.write(f"누적실적: {metrics['월간누계']['a_m3']:,.1f} (천 m3)")
with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"연간계획: {metrics['연간누계']['p_gj']:,.0f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.dataframe(df[df['날짜'] == target_date])
