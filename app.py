import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

def load_data(file_source):
    # 1. 헤더 없이 일단 통째로 읽어옵니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜'라는 글자가 들어있는 행을 자동으로 찾아 헤더로 설정합니다.
    header_idx = None
    for i, row in raw_df.iterrows():
        if row.astype(str).str.contains('날짜').any():
            header_idx = i
            break
    
    if header_idx is None:
        st.error("❌ 엑셀 시트에서 '날짜' 컬럼을 찾을 수 없습니다. 시트 이름을 확인해주세요.")
        st.stop()

    # 3. 찾은 행을 컬럼명으로 지정하고 데이터 본체를 추출합니다.
    df = raw_df.iloc[header_idx+1:].copy()
    headers = raw_df.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
    df.columns = headers

    # 4. 유연한 컬럼 매칭 (단어만 포함되어 있으면 가져옴)
    col_map = {}
    for i, col in enumerate(df.columns):
        if '날짜' in col: col_map['date'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 5. 필수 데이터 정제 (숫자로 강제 변환)
    final_df = pd.DataFrame()
    final_df['날짜'] = pd.to_datetime(df[col_map['date']], errors='coerce')
    final_df = final_df.dropna(subset=['날짜']) # 날짜 없는 행 제거
    
    for key in ['p_gj', 'a_gj', 'a_m3']:
        if key in col_map:
            final_df[key] = pd.to_numeric(df[col_map[key]], errors='coerce').fillna(0)
        else:
            final_df[key] = 0
            
    return final_df, col_map

# 파일 로드
st.sidebar.header("📂 데이터 설정")
uploaded_file = st.sidebar.file_uploader("새로운 엑셀 업로드 (옵션)", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    df, c_map = load_data(uploaded_file if uploaded_file else DEFAULT_FILE)
    if uploaded_file: st.sidebar.success("✅ 업로드 파일 적용")
    else: st.sidebar.info("ℹ️ GitHub 기본 파일 사용")
except Exception as e:
    st.error(f"⚠️ 데이터 로드 실패: {e}")
    st.stop()

# 화면 표시
st.title("🔥 도시가스 공급실적 분석 대시보드")
selected_date = st.date_input("조회 기준일 선택", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

# 6. 진도율 계산 (형님의 '진도율' 로직: 당일 누적 계획 vs 실적)
def get_metrics(df, t_date):
    ytd = df[df['날짜'] <= t_date]
    mtd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)]
    day = df[df['날짜'] == t_date]
    
    res = {}
    for label, d in zip(['일간', '월간누계', '연간누계'], [day, mtd, ytd]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        m3 = d['a_m3'].sum() / 1000 # 천 m3 환산
        ach = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3, 'ach': ach}
    return res

metrics = get_metrics(df, target_date)

# 7. 지표 카드 출력
col1, col2, col3 = st.columns(3)
with col1:
    diff = metrics['일간']['ach'] - 100
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a']:,.0f}", f"{diff:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p']:,.0f} GJ")

with col2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", f"{metrics['월간누계']['a'] - metrics['월간누계']['p']:,.0f} GJ")
    st.write(f"누적실적: {metrics['월간누계']['m3']:,.1f} (천 m3)")

with col3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"누적계획: {metrics['연간누계']['p']:,.0f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.dataframe(df[df['날짜'] == target_date], use_container_width=True)

# 하단에 디버깅 정보 (문제가 있을 때만 확인하세요)
with st.expander("🛠️ 시스템 인식 정보 (에러 시 확인용)"):
    st.write("컬럼 매칭 정보:", c_map)
    st.write("인식된 데이터 샘플:", df.head())
