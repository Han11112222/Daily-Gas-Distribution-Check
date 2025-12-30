import streamlit as st
import pandas as pd

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

# 1. 파일 로드 로직
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("새로운 실적 엑셀 파일을 업로드하세요 (옵션)", type=["xlsx"])

def load_data(file_source):
    # 엑셀 시트 읽기 (시트 이름 확인 필수)
    try:
        # header=1(2행)이 안 맞을 경우를 대비해 header=0으로 읽고 필터링하는 방식 시도
        df = pd.read_excel(file_source, sheet_name='연간', header=1) 
    except:
        df = pd.read_excel(file_source, sheet_name=0, header=1) # 시트 이름 에러 대비

    # 컬럼명 정리
    df.columns = [str(c).strip() for c in df.columns]
    
    # '날짜' 컬럼이 없는 경우 대비 (헤더 위치 자동 조정 로직)
    if '날짜' not in df.columns:
        st.warning("'날짜' 컬럼을 찾는 중... 헤더 위치를 재조정합니다.")
        # 헤더가 1행(header=0)에 있을 경우 다시 시도
        df = pd.read_excel(file_source, sheet_name='연간', header=0)
        df.columns = [str(c).strip() for c in df.columns]

    # 데이터 정제
    df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
    df = df.dropna(subset=['날짜']) # 날짜 없는 행 삭제
    
    # 숫자 데이터 정제 및 0 채우기
    cols = ['계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        else:
            df[col] = 0 # 컬럼이 아예 없으면 0으로 생성
            
    return df

DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file is not None:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드 파일 적용 완료")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 파일 사용 중")
except Exception as e:
    st.error(f"⚠️ 파일 로드 중 에러: {e}")
    st.stop()

# 2. 날짜 선택 및 계산
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

def get_metrics(df, t_date):
    ytd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)
    mtd_mask = (df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)
    daily_mask = (df['날짜'] == t_date)
    
    res = {}
    for label, mask in zip(['일간', '월간누계', '연간누계'], [daily_mask, mtd_mask, ytd_mask]):
        p_gj = df.loc[mask, '계획(GJ)'].sum()
        a_gj = df.loc[mask, '실적(GJ)'].sum()
        a_m3 = df.loc[mask, '실적(m3)'].sum() / 1000 
        
        # ZeroDivisionError 방지 로직 (나누기 0 체크)
        ach = (a_gj / p_gj * 100) if p_gj != 0 else 0
        res[label] = {'p_gj': p_gj, 'a_gj': a_gj, 'a_m3': a_m3, 'ach': ach}
    return res

metrics = get_metrics(df, target_date)

# 3. 화면 표시
col1, col2, col3 = st.columns(3)
with col1:
    # 달성률(ach)이 0일 경우 대비
    diff = metrics['일간']['ach'] - 100 if metrics['일간']['p_gj'] > 0 else 0
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a_gj']:,.0f}", f"{diff:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p_gj']:,.0f} GJ")
with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", f"계획비 {metrics['월간누계']['a_gj'] - metrics['월간누계']['p_gj']:,.0f} GJ")
    st.write(f"누적실적: {metrics['월간누계']['a_m3']:,.1f} (천 m3)")
with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"연간계획: {metrics['연간누계']['p_gj']:,.0f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.table(df[df['날짜'] == target_date])
