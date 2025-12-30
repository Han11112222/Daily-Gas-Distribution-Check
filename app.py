import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# 1. 파일 로드 로직 (GitHub 기본 파일 vs 사용자 업로드)
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("새로운 실적 엑셀 파일을 업로드하세요 (옵션)", type=["xlsx"])

def load_data(file_source):
    # 엑셀의 첫 몇 줄이 비어있을 수 있으므로 header=0 또는 데이터 시작 위치를 확인해야 합니다.
    # 만약 에러가 지속되면 header=1 등으로 조정이 필요할 수 있습니다.
    df = pd.read_excel(file_source, sheet_name='연간')
    
    # 공백 제거 및 컬럼명 정리
    df.columns = [c.strip() for c in df.columns]
    
    # 날짜 형식 변환
    df['날짜'] = pd.to_datetime(df['날짜'])
    return df

# 파일 소스 결정 (업로드 파일 우선, 없으면 GitHub의 기본 파일 사용)
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file is not None:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드된 파일을 사용 중입니다.")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 데이터를 사용 중입니다.")
except Exception as e:
    st.error(f"데이터 로드 중 오류가 발생했습니다: {e}")
    st.info("엑셀 파일의 시트 이름이 '연간'인지, 컬럼명이 정확한지 확인해 주세요.")
    st.stop()

# 2. 날짜 선택 및 메트릭 계산
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

# 진도율 계산 함수 (형님의 '일대비 100%면 월대비 100%' 로직 반영)
def get_metrics(df, t_date):
    # 필터 생성
    ytd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)
    mtd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)
    daily_mask = (df['날짜'] == t_date)
    
    res = {}
    for label, mask in zip(['일간', '월간누계', '연간누계'], [daily_mask, mtd_mask, ytd_mask]):
        # 컬럼명에 GJ나 m3가 포함된 것을 동적으로 찾습니다 (오타 방지)
        p_gj = df.loc[mask, '계획(GJ)'].sum()
        a_gj = df.loc[mask, '실적(GJ)'].sum()
        p_m3 = df.loc[mask, '계획(m3)'].sum() / 1000 # 천 m3 단위
        a_m3 = df.loc[mask, '실적(m3)'].sum() / 1000
        
        achieve = (a_gj / p_gj * 100) if p_gj > 0 else 0
        res[label] = {'p_gj': p_gj, 'a_gj': a_gj, 'p_m3': p_m3, 'a_m3': a_m3, 'ach': achieve}
    return res

metrics = get_metrics(df, target_date)

# 3. 화면 표시
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a_gj']:,.0f}", f"{metrics['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p_gj']:,.0f} GJ")
with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", f"계획비 {metrics['월간누계']['a_gj'] - metrics['월간누계']['p_gj']:,.0f} GJ")
    st.write(f"실적: {metrics['월간누계']['a_m3']:,.0f} (천 m3)")
with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"누적계획: {metrics['연간누계']['p_gj']:,.2f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.table(df[df['날짜'] == target_date])
