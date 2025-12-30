import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 실적 현황", layout="wide")

def load_data(file_source):
    # 1. 엑셀을 헤더 없이 통째로 읽어옵니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜'라는 글자가 들어있는 행을 찾습니다. (데이터 시작점 찾기)
    header_idx = None
    for i, row in raw_df.iterrows():
        # 행의 값들을 문자로 합쳐서 '날짜'가 있는지 확인
        if '날짜' in row.astype(str).values:
            header_idx = i
            break
    
    if header_idx is None:
        st.error("❌ '날짜'가 적힌 행을 찾을 수 없습니다.")
        st.stop()

    # 3. 데이터 본체 추출
    # 헤더 다음 줄부터 데이터를 가져옵니다.
    df = raw_df.iloc[header_idx+1:].copy()
    
    # [핵심] 컬럼 이름을 믿지 않고, 순서대로 강제 이름을 붙입니다.
    # 형님의 파일 순서: 날짜 | 계획(GJ) | 실적(GJ) | 계획(m3) | 실적(m3)
    # 데이터가 5개 컬럼 이상이라고 가정합니다.
    try:
        df = df.iloc[:, :5] # 앞의 5개 컬럼만 자릅니다.
        df.columns = ['date', 'p_gj', 'a_gj', 'p_m3', 'a_m3']
    except Exception as e:
        st.error(f"❌ 데이터 컬럼 개수가 부족합니다. (최소 5열 필요): {e}")
        st.write("현재 인식된 데이터:", df.head())
        st.stop()

    # 4. 데이터 강제 형변환 (에러 방지)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']) # 날짜가 없는 행은 삭제
    
    # 숫자로 변환 (빈값은 0으로)
    cols = ['p_gj', 'a_gj', 'p_m3', 'a_m3']
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
    return df

# --- 메인 로직 ---
st.title("🔥 도시가스 공급실적 분석")

# 파일 업로드 (사이드바)
st.sidebar.header("📂 파일 설정")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 업로드", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드 파일 적용됨")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ 기본 파일 사용 중")
except Exception as e:
    st.error(f"⚠️ 시스템 에러: {e}")
    st.stop()

# 날짜 선택
selected_date = st.date_input("조회 기준일", value=df['date'].min())
target_date = pd.to_datetime(selected_date)

# 계산 로직
def calculate_metrics(df, t_date):
    day = df[df['date'] == t_date]
    mtd = df[(df['date'] <= t_date) & (df['date'].dt.month == t_date.month) & (df['date'].dt.year == t_date.year)]
    ytd = df[(df['date'] <= t_date) & (df['date'].dt.year == t_date.year)]
    
    res = {}
    for label, d in zip(['일간', '월간', '연간'], [day, mtd, ytd]):
        p_gj = d['p_gj'].sum()
        a_gj = d['a_gj'].sum()
        a_m3 = d['a_m3'].sum() / 1000 # 천 m3
        
        rate = (a_gj / p_gj * 100) if p_gj > 0 else 0
        res[label] = {'p': p_gj, 'a': a_gj, 'm3': a_m3, 'rate': rate}
    return res

metrics = calculate_metrics(df, target_date)

# 결과 표시
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("오늘 실적 (GJ)", 
              f"{metrics['일간']['a']:,.0f}", 
              f"{metrics['일간']['rate']-100:.1f}%")
    st.caption(f"계획: {metrics['일간']['p']:,.0f}")

with col2:
    st.metric("월간 진도율 (MTD)", 
              f"{metrics['월간']['rate']:.1f}%",
              f"{metrics['월간']['a'] - metrics['월간']['p']:,.0f} GJ")
    st.write(f"실적: {metrics['월간']['m3']:,.1f} (천 m3)")

with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간']['rate']:.1f}%")
    st.write(f"계획: {metrics['연간']['p']:,.0f} GJ")

st.divider()

# 디버깅용 (형님만 보세요)
with st.expander("🛠️ 데이터가 이상하면 여기를 눌러보세요"):
    st.write("읽어온 데이터 샘플 (상위 5개):")
    st.dataframe(df.head())
