import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# 1. 데이터 로드 함수 (헤더 자동 탐색형)
def load_data(file_source):
    # 시트 이름이 '연간'인 것을 먼저 찾고, 없으면 첫 번째 시트 로드
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # '날짜'라는 단어가 포함된 행을 찾아 헤더로 설정
    header_row = 0
    for i, row in raw_df.iterrows():
        if '날짜' in row.values:
            header_row = i
            break
    
    # 찾은 헤더 행을 기준으로 데이터프레임 재설정
    df = raw_df.iloc[header_row+1:].copy()
    df.columns = raw_df.iloc[header_row].values
    df.columns = [str(c).strip() for c in df.columns] # 공백 제거
    
    # 필요한 컬럼만 추출 및 정제
    df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
    df = df.dropna(subset=['날짜'])
    
    cols_to_fix = ['계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']
    for col in cols_to_fix:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        else:
            df[col] = 0
            
    return df

# 2. 파일 소스 결정
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("새로운 실적 엑셀 파일을 업로드하세요 (옵션)", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file is not None:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드 파일 사용 중")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 파일 사용 중")
except Exception as e:
    st.error(f"⚠️ 데이터 로드 실패: {e}")
    st.stop()

# 3. 날짜 선택 및 계산 로직
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

def get_metrics(df, t_date):
    # 날짜 필터링
    ytd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)
    mtd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)
    daily_mask = (df['날짜'] == t_date)
    
    res = {}
    for label, mask in zip(['일간', '월간누계', '연간누계'], [daily_mask, mtd_mask, ytd_mask]):
        p_gj = df.loc[mask, '계획(GJ)'].sum()
        a_gj = df.loc[mask, '실적(GJ)'].sum()
        a_m3 = df.loc[mask, '실적(m3)'].sum() / 1000 
        
        # 0으로 나누기 방지
        ach = (a_gj / p_gj * 100) if p_gj != 0 else 0
        res[label] = {'p_gj': p_gj, 'a_gj': a_gj, 'a_m3': a_m3, 'ach': ach}
    return res

metrics = get_metrics(df, target_date)

# 4. 시각화 (형님의 요청 스타일 반영)
col1, col2, col3 = st.columns(3)
with col1:
    diff = metrics['일간']['ach'] - 100 if metrics['일간']['p_gj'] > 0 else 0
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a_gj']:,.0f}", f"{diff:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p_gj']:,.0f} GJ")

with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", 
              delta=f"{metrics['월간누계']['a_gj'] - metrics['월간누계']['p_gj']:,.0f} GJ",
              delta_color="normal")
    st.write(f"누적실적: {metrics['월간누계']['a_m3']:,.1f} (천 m3)")

with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"연간계획: {metrics['연간누계']['p_gj']:,.0f} GJ")

st.divider()
st.subheader("📋 상세 데이터 (선택일)")
st.dataframe(df[df['날짜'] == target_date], use_container_width=True)
