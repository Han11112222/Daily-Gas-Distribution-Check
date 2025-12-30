import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

def load_data(file_source):
    # 1. 엑셀을 읽되 시트 이름이 '연간'인 것을 먼저 찾습니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜' 단어가 포함된 행을 찾아 헤더로 설정 (데이터 시작 위치 자동 탐색)
    header_idx = None
    for i, row in raw_df.iterrows():
        if row.astype(str).str.contains('날짜').any():
            header_idx = i
            break
    
    if header_idx is None:
        st.error("❌ '연간' 시트에서 '날짜' 제목을 찾을 수 없습니다. 시트 양식을 확인해주세요.")
        st.stop()

    # 3. 데이터 추출 및 컬럼명 공백 제거
    df = raw_df.iloc[header_idx+1:].copy()
    headers = raw_df.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
    df.columns = headers

    # 4. 유연한 컬럼 매칭 (이름이 조금 달라도 핵심 단어로 인식)
    col_map = {}
    for col in df.columns:
        if '날짜' in col: col_map['date'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '계획' in col and 'm3' in col: col_map['p_m3'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 5. 데이터 정제 (숫자 변환 및 빈칸 0 처리)
    final_df = pd.DataFrame()
    final_df['날짜'] = pd.to_datetime(df[col_map['date']], errors='coerce')
    final_df = final_df.dropna(subset=['날짜']) # 날짜 없는 줄 제거
    
    for key in ['p_gj', 'a_gj', 'p_m3', 'a_m3']:
        if key in col_map:
            final_df[key] = pd.to_numeric(df[col_map[key]], errors='coerce').fillna(0)
        else:
            final_df[key] = 0
            
    return final_df

# 파일 관리 로직 (GitHub 파일 우선, 업로드 시 교체)
st.sidebar.header("📂 데이터 관리")
uploaded_file = st.sidebar.file_uploader("새로운 엑셀 업로드 (옵션)", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    df = load_data(uploaded_file if uploaded_file else DEFAULT_FILE)
    if uploaded_file: st.sidebar.success("✅ 업로드 파일 적용 완료")
    else: st.sidebar.info("ℹ️ 기본 데이터 사용 중")
except Exception as e:
    st.error(f"⚠️ 데이터 로드 실패: {e}")
    st.stop()

# 화면 구성
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일 선택", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

# 6. 진도율 계산 로직 (형님이 요청하신 진도율 개념 적용)
def get_metrics(df, t_date):
    # 당일 실적
    day = df[df['날짜'] == t_date]
    # 월간 누계 (해당 월 1일부터 선택일까지의 계획만 합산)
    mtd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)]
    # 연간 누계 (1월 1일부터 선택일까지의 계획만 합산)
    ytd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)]
    
    res = {}
    for label, d in zip(['일간', '월간누계', '연간누계'], [day, mtd, ytd]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        # 천 m3 환산
        m3_actual = d['a_m3'].sum() / 1000 
        # 0으로 나누기 방지
        ach = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3_actual, 'ach': ach}
    return res

m = get_metrics(df, target_date)

# 7. 메트릭 레이아웃 출력
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("오늘 실적 (GJ)", f"{m['일간']['a']:,.0f}", f"{m['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {m['일간']['p']:,.0f} GJ")

with c2:
    st.metric("월간 진도율 (MTD)", f"{m['월간누계']['ach']:.1f}%", f"{m['월간누계']['a'] - m['월간누계']['p']:,.0f} GJ")
    st.write(f"누적 실적: {m['월간누계']['m3']:,.1f} (천 m3)")

with c3:
    st.metric("연간 진도율 (YTD)", f"{m['연간누계']['ach']:.1f}%")
    st.write(f"누적 계획: {m['연간누계']['p']:,.0f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.table(df[df['날짜'] == target_date])
