import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# 1. 파일 업로드 섹션 (3번째 사진 요청 반영)
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("실적 엑셀 파일을 업로드하세요", type=["xlsx"])

# 데이터 로드 함수
def load_data(file):
    # '연간' 시트에서 데이터를 읽어온다고 가정합니다.
    df = pd.read_excel(file, sheet_name='연간')
    df['날짜'] = pd.to_datetime(df['날짜'])
    return df

# 파일 소스 결정
if uploaded_file is not None:
    df = load_data(uploaded_file)
    st.sidebar.success("업로드된 파일을 사용 중입니다.")
else:
    # 깃허브에 올릴 기본 파일명 (예: data.xlsx)
    try:
        df = load_data("2026_연간_일별공급계획_2.xlsx")
        st.sidebar.info("기본 데이터를 사용 중입니다.")
    except:
        st.error("데이터 파일을 찾을 수 없습니다. 엑셀을 업로드하거나 GitHub 경로를 확인하세요.")
        st.stop()

# 2. 날짜 선택 (1번째 사진 요청 반영)
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
selected_date = pd.to_datetime(selected_date)

# 3. 누적 데이터 계산 (2번째 요청: 진도율 개념 반영)
def calculate_metrics(df, target_date):
    # 연간 누적 (1월 1일부터 선택일까지)
    ytd_mask = (df['날짜'] <= target_date) & (df['날짜'].dt.year == target_date.year)
    # 월간 누적 (해당 월 1일부터 선택일까지)
    mtd_mask = (df['날짜'] <= target_date) & (df['날짜'].dt.month == target_date.month) & (df['날짜'].dt.year == target_date.year)
    # 일간 (선택일 당일)
    daily_mask = (df['날짜'] == target_date)

    results = {}
    for label, mask in zip(['일간', '월간누계', '연간누계'], [daily_mask, mtd_mask, ytd_mask]):
        plan_gj = df.loc[mask, '계획(GJ)'].sum()
        actual_gj = df.loc[mask, '실적(GJ)'].sum()
        plan_m3 = df.loc[mask, '계획(m3)'].sum() / 1000 # 천 m3 단위 환산
        actual_m3 = df.loc[mask, '실적(m3)'].sum() / 1000
        
        achievement = (actual_gj / plan_gj * 100) if plan_gj > 0 else 0
        results[label] = {
            'plan_gj': plan_gj, 'actual_gj': actual_gj, 
            'plan_m3': plan_m3, 'actual_m3': actual_m3, 
            'achieve': achievement
        }
    return results

metrics = calculate_metrics(df, selected_date)

# 4. 화면 표시
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("오늘 대비 실적 (GJ)", f"{metrics['일간']['actual_gj']:,.0f}", f"{metrics['일간']['achieve']-100:.1f}%")
    st.caption(f"목표: {metrics['일간']['plan_gj']:,.0f} GJ")

with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['achieve']:.1f}%", f"목표대비 {metrics['월간누계']['actual_gj'] - metrics['월간누계']['plan_gj']:,.0f} GJ")
    st.write(f"실적: {metrics['월간누계']['actual_m3']:,.0f} (천 m3)")

with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['achieve']:.1f}%")
    st.write(f"계획: {metrics['연간누계']['plan_gj']:,.0f} GJ")

st.divider()
st.subheader("📋 상세 데이터 (선택일 기준)")
st.dataframe(df[df['날짜'] == selected_date])
