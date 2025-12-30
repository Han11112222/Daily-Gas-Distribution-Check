import streamlit as st
import pandas as pd

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# 1. 파일 로드 로직
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("새로운 실적 엑셀 파일을 업로드하세요 (옵션)", type=["xlsx"])

def load_data(file_source):
    # 헤더가 2번째 줄에 있을 수 있으므로 header=1로 설정하거나, 
    # 데이터 구조에 따라 자동으로 헤더를 찾도록 처리합니다.
    df = pd.read_excel(file_source, sheet_name='연간', header=1) # 2행부터 읽기
    
    # 컬럼명 정리 (공백 제거)
    df.columns = [str(c).strip() for c in df.columns]
    
    # 필수 컬럼 존재 확인 및 데이터 정제
    df['날짜'] = pd.to_datetime(df['날짜'])
    # 실적 데이터가 비어있으면(NaN) 0으로 채움
    df['실적(GJ)'] = df['실적(GJ)'].fillna(0)
    df['실적(m3)'] = df['실적(m3)'].fillna(0)
    
    return df

DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file is not None:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드된 파일을 사용 중입니다.")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 데이터를 사용 중입니다.")
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# 2. 날짜 선택 및 계산
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

# 진도율 계산 로직
def get_metrics(df, t_date):
    ytd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)
    mtd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)
    daily_mask = (df['날짜'] == t_date)
    
    res = {}
    for label, mask in zip(['일간', '월간누계', '연간누계'], [daily_mask, mtd_mask, ytd_mask]):
        p_gj = df.loc[mask, '계획(GJ)'].sum()
        a_gj = df.loc[mask, '실적(GJ)'].sum()
        p_m3 = df.loc[mask, '계획(m3)'].sum() / 1000 
        a_m3 = df.loc[mask, '실적(m3)'].sum() / 1000
        
        achieve = (a_gj / p_gj * 100) if p_gj > 0 else 0
        res[label] = {'p_gj': p_gj, 'a_gj': a_gj, 'p_m3': p_m3, 'a_m3': a_m3, 'ach': achieve}
    return res

metrics = get_metrics(df, target_date)

# 3. 화면 표시 (1번째 사진 스타일 반영)
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a_gj']:,.0f}", f"{metrics['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p_gj']:,.0f} GJ")
with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", f"목표대비 {metrics['월간누계']['a_gj'] - metrics['월간누계']['p_gj']:,.0f} GJ")
    st.write(f"실적: {metrics['월간누계']['a_m3']:,.1f} (천 m3)")
with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"누적계획: {metrics['연간누계']['p_gj']:,.0f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.dataframe(df[df['날짜'] == target_date])
